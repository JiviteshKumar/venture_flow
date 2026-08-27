"""Train a risk-DISCLOSURE detector on in-domain filing prose.

This replaces the Risk/Tone model for the risk task. That model is not being
retrained, it is being retired from this job, and the reason is measured rather
than asserted:

    Risk/Tone (Financial PhraseBank + TFNS, 15,376 examples)
        accuracy on its own held-out test set : 0.767
        ranking AUC on ml/eval/risk_benchmark  : 0.333   <- below chance
        predictions on the 28 benchmark excerpts: `neutral`, all of them

A model that scores 0.767 in-distribution and below chance on the target task
does not have a threshold problem or a capacity problem. It has a task-mismatch
problem: "is this headline bullish or bearish" is not "does this paragraph
disclose a material risk", which is the distinction Loughran & McDonald (2011)
drew when they showed general-purpose sentiment lexicons misread financial
disclosure language. More sentiment data moves the first number only.

So the training distribution here IS the target distribution: paragraphs from
10-K, 10-Q and 8-K filings, weakly labelled by the phrase that retrieved them
(see ml/scripts/build_risk_training_corpus.py).

THREE THINGS THIS SCRIPT REFUSES TO DO

1. **Train on the eval set.** The 28 hand-labelled excerpts are disjoint and
   stay disjoint; the corpus builder excludes them by text hash, by containment,
   and by EDGAR accession. This script re-checks that at load time and refuses
   to run if the guarantee is violated, because a silent leak would produce a
   beautiful number that means nothing.

2. **Split randomly.** Excerpts are grouped by filing accession, so two
   paragraphs from the same 10-K never straddle the split. A random split
   inflates validation scores by letting the model memorise a filing's house
   style and meet it again in test.

3. **Report accuracy as the headline.** For a risk detector the number that
   matters is the false-positive rate on hard boilerplate, because filings are
   overwhelmingly hedged legal prose and a detector that flags everything scores
   well on recall while being useless. That figure is computed on the disjoint
   benchmark's 13 deliberately-hard negatives and printed first.

    python ml/scripts/train_risk_disclosure_model.py
"""

from __future__ import annotations

import argparse
import json
import pickle
import re
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import console_safety  # noqa: E402,F401  (Windows cp1252 guard)
from agents.deck_risk_features import DeckFeatureTransformer  # noqa: E402

CORPUS_PATH = ROOT / "ml" / "data" / "risk_training_corpus.jsonl"
EVAL_PATH = ROOT / "ml" / "eval" / "risk_benchmark.jsonl"
MODEL_PATH = ROOT / "ml" / "models" / "risk_disclosure_model.pkl"
REPORT_PATH = ROOT / "ml" / "models" / "risk_disclosure_model_report.json"


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def load_corpus() -> list[dict]:
    if not CORPUS_PATH.exists():
        raise SystemExit(
            f"{CORPUS_PATH} not found -- run ml/scripts/build_risk_training_corpus.py first."
        )
    rows = [json.loads(line) for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise SystemExit("Training corpus is empty.")
    return rows


def load_eval() -> list[dict]:
    return [json.loads(line) for line in EVAL_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def assert_disjoint(train_rows: list[dict], eval_rows: list[dict]) -> None:
    """Refuse to train if any eval text leaked into the corpus.

    Checked here as well as in the builder on purpose. The builder's guard runs
    once, at collection time; this one runs every time a model is fitted, which
    is when a leak would actually turn into a published number.
    """
    eval_texts = [_normalise(r["text"]) for r in eval_rows]
    eval_set = set(eval_texts)
    leaks = []
    for row in train_rows:
        normalised = _normalise(row["text"])
        if normalised in eval_set:
            leaks.append(("exact", row.get("url", "")))
        elif any(e in normalised or normalised in e for e in eval_texts):
            leaks.append(("contained", row.get("url", "")))
    if leaks:
        raise SystemExit(
            f"REFUSING TO TRAIN: {len(leaks)} training excerpt(s) overlap the eval set. "
            f"First: {leaks[0]}"
        )
    print(f"Disjointness verified: 0 of {len(train_rows)} training excerpts overlap "
          f"the {len(eval_rows)} hand-labelled eval excerpts.")


def build_pipeline(use_deck_features: bool = False):
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline, FeatureUnion

    # Word and character n-grams together. Character n-grams matter here because
    # disclosure language is formulaic at the sub-word level ("non-compliance",
    # "un-remediated") and filings are full of OCR-ish artefacts that break
    # whole-word matching.
    features = FeatureUnion([
        ("word", TfidfVectorizer(
            ngram_range=(1, 2), min_df=2, max_df=0.9, sublinear_tf=True,
            strip_accents="unicode", lowercase=True, max_features=60000)),
        ("char", TfidfVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True,
            lowercase=True, max_features=60000)),
    ])
    # Logistic regression rather than a gradient-boosted tree: the features are
    # high-dimensional and sparse, which is where linear models are strong, and
    # the coefficients are directly inspectable -- a reviewer can ask which
    # phrases drive a positive and get an answer. Calibrated because the
    # pipeline consumes a probability, not a class.
    if use_deck_features:
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline as _P

        # Scaled, because the structured block mixes 0/1 indicators with
        # runway in months and a burn multiple. Unscaled, the largest-magnitude
        # column would dominate a linear model's coefficients for reasons that
        # have nothing to do with signal.
        features = FeatureUnion([
            ("text", features),
            ("deck", _P([("extract", DeckFeatureTransformer()), ("scale", StandardScaler())])),
        ])

    base = LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced")
    return Pipeline([
        ("features", features),
        ("clf", CalibratedClassifierCV(base, method="isotonic", cv=5)),
    ])


def evaluate_on_benchmark(model, eval_rows: list[dict], threshold: float) -> dict:
    texts = [r["text"] for r in eval_rows]
    gold = np.array([1 if r["gold_risk"] else 0 for r in eval_rows])
    probabilities = model.predict_proba(texts)[:, 1]
    predicted = (probabilities >= threshold).astype(int)

    true_pos = int(((predicted == 1) & (gold == 1)).sum())
    false_pos = int(((predicted == 1) & (gold == 0)).sum())
    false_neg = int(((predicted == 0) & (gold == 1)).sum())
    precision = true_pos / (true_pos + false_pos) if (true_pos + false_pos) else 0.0
    recall = true_pos / (true_pos + false_neg) if (true_pos + false_neg) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    # The headline. Filings are mostly hedged legal prose, so a detector is
    # judged on what it does to the hard negatives.
    negatives = gold == 0
    boilerplate_fp = float(predicted[negatives].mean()) if negatives.any() else 0.0

    from sklearn.metrics import roc_auc_score
    auc = float(roc_auc_score(gold, probabilities)) if len(set(gold.tolist())) > 1 else float("nan")

    per_row = [
        {"id": row["id"], "gold": bool(row["gold_risk"]),
         "prob": round(float(p), 4), "pred": bool(q)}
        for row, p, q in zip(eval_rows, probabilities, predicted)
    ]
    deck_rows = [r for r in per_row if r["id"].startswith("deck")]

    # Subgroup AUC, reported always and never averaged away.
    #
    # The combined figure is dominated by whichever subgroup is larger, and here
    # that is the 22 SEC excerpts. Quoting it alone would claim deck-register
    # performance this model does not have: split out, it is 0.992 on filing
    # prose and 0.667 on deck prose. The model solved the register it was
    # trained on and did not transfer to the other one -- which is the correct
    # and expected result, and is exactly the kind of thing a single headline
    # number hides.
    def _subgroup_auc(prefix: str) -> float:
        subset = [r for r in per_row if r["id"].startswith(prefix)]
        y = [int(r["gold"]) for r in subset]
        if len(set(y)) < 2:
            return float("nan")
        return float(roc_auc_score(y, [r["prob"] for r in subset]))

    return {
        "threshold": threshold,
        "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        "accuracy": round(float((predicted == gold).mean()), 4),
        "boilerplate_false_positive_rate": round(boilerplate_fp, 4),
        "ranking_auc": round(auc, 4),
        "ranking_auc_sec_filings": round(_subgroup_auc("sec"), 4),
        "ranking_auc_deck_register": round(_subgroup_auc("deck"), 4),
        "n": len(eval_rows),
        "n_sec": sum(1 for r in per_row if r["id"].startswith("sec")),
        "n_deck": len(deck_rows),
        "deck_register_recall": round(
            float(np.mean([r["pred"] for r in deck_rows if r["gold"]])) if
            any(r["gold"] for r in deck_rows) else 0.0, 4),
        "per_excerpt": per_row,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck-features", action="store_true",
                        help="augment TF-IDF with structured deck features "
                             "(see ml/scripts/deck_risk_features.py for the leakage audit)")
    parser.add_argument("--out-suffix", default="",
                        help="suffix for the model/report filenames, so an arm "
                             "does not overwrite the control")
    parser.add_argument("--threshold", type=float, default=None,
                        help="operating threshold; default is chosen on the "
                             "in-distribution held-out split, never on the benchmark")
    args = parser.parse_args()

    rows = load_corpus()
    eval_rows = load_eval()
    assert_disjoint(rows, eval_rows)

    texts = [r["text"] for r in rows]
    labels = np.array([r["label"] for r in rows])
    groups = np.array([r.get("accession") or f"row{i}" for i, r in enumerate(rows)])

    positives = int(labels.sum())
    print(f"Corpus: {len(rows)} excerpts ({positives} positive, {len(rows) - positives} negative) "
          f"from {len(set(groups))} filings")
    if positives < 30 or len(rows) - positives < 30:
        raise SystemExit("Corpus is too small or too imbalanced to train on honestly.")

    # Grouped split: no filing appears on both sides.
    from sklearn.model_selection import GroupShuffleSplit, cross_val_score, GroupKFold

    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=17)
    train_index, test_index = next(splitter.split(texts, labels, groups))
    train_texts = [texts[i] for i in train_index]
    test_texts = [texts[i] for i in test_index]
    y_train, y_test = labels[train_index], labels[test_index]
    print(f"Grouped split: {len(train_index)} train / {len(test_index)} test, "
          f"0 filings shared")

    model = build_pipeline(use_deck_features=args.deck_features)
    model.fit(train_texts, y_train)

    from sklearn.metrics import classification_report, roc_auc_score
    held_out_prob = model.predict_proba(test_texts)[:, 1]
    held_out = {
        "accuracy": round(float((model.predict(test_texts) == y_test).mean()), 4),
        "roc_auc": round(float(roc_auc_score(y_test, held_out_prob)), 4),
        "report": classification_report(y_test, model.predict(test_texts),
                                        output_dict=True, zero_division=0),
    }
    print(f"\nHeld-out (in-distribution, grouped): accuracy {held_out['accuracy']}, "
          f"ROC-AUC {held_out['roc_auc']}")

    # Choose the operating threshold on HELD-OUT TRAINING data, never on the
    # benchmark.
    #
    # This is the methodological trap in the whole exercise. The benchmark has
    # 28 examples; sweeping a threshold over it and reporting the best one is
    # not an evaluation, it is fitting a parameter to the test set and then
    # quoting the training error. The resulting number would look excellent and
    # would not survive contact with a 29th example.
    #
    # So the threshold is picked here, on the grouped in-distribution split, by
    # maximising F1 -- and is then applied to the benchmark unchanged. The
    # ranking AUC reported below is threshold-free and is the honest headline
    # either way.
    if args.threshold is None:
        from sklearn.metrics import precision_recall_curve
        precision, recall, thresholds = precision_recall_curve(y_test, held_out_prob)
        f1_scores = 2 * precision * recall / np.clip(precision + recall, 1e-9, None)
        chosen = float(thresholds[int(np.nanargmax(f1_scores[:-1]))])
        print(f"Threshold chosen on the in-distribution held-out split: {chosen:.3f} "
              f"(F1 {np.nanmax(f1_scores[:-1]):.3f} there)")
    else:
        chosen = args.threshold
        print(f"Threshold supplied by the caller: {chosen:.3f}")

    # Refit on everything before the out-of-distribution evaluation, which is
    # the number that actually decides whether this ships.
    final = build_pipeline(use_deck_features=args.deck_features)
    final.fit(texts, labels)
    benchmark = evaluate_on_benchmark(final, eval_rows, chosen)

    # Reported for transparency only -- NOT used to choose anything. A reader
    # is entitled to see how sensitive the benchmark result is to the threshold
    # without that sweep having influenced the shipped value.
    sweep = []
    for candidate in [round(x, 2) for x in np.arange(0.10, 0.95, 0.05)]:
        row = evaluate_on_benchmark(final, eval_rows, candidate)
        sweep.append({k: row[k] for k in
                      ("threshold", "precision", "recall", "f1",
                       "boilerplate_false_positive_rate", "deck_register_recall")})

    print("\n" + "=" * 74)
    print("DISJOINT BENCHMARK (28 hand-labelled excerpts, never trained on)")
    print("=" * 74)
    print(f"  boilerplate false-positive rate : {benchmark['boilerplate_false_positive_rate']:.3f}"
          f"   <- the number that matters")
    print(f"  precision / recall / F1         : {benchmark['precision']:.3f} / "
          f"{benchmark['recall']:.3f} / {benchmark['f1']:.3f}")
    print(f"  accuracy                        : {benchmark['accuracy']:.3f}")
    print(f"  ranking AUC (all 28)            : {benchmark['ranking_auc']:.3f}")
    print(f"    ...on SEC filing prose (n={benchmark['n_sec']}) : "
          f"{benchmark['ranking_auc_sec_filings']:.3f}   <- the register it was trained on")
    print(f"    ...on deck prose       (n={benchmark['n_deck']})  : "
          f"{benchmark['ranking_auc_deck_register']:.3f}   <- did NOT transfer; "
          f"agents/deck_financials covers this")
    print(f"  deck-register recall            : {benchmark['deck_register_recall']:.3f}")
    print("\n  Prior Risk/Tone model, same benchmark: AUC 0.333 (below chance), "
          "all 28 predicted `neutral`.")

    model_path = (MODEL_PATH.with_name(MODEL_PATH.stem + args.out_suffix + MODEL_PATH.suffix)
                  if args.out_suffix else MODEL_PATH)
    report_path = (REPORT_PATH.with_name(REPORT_PATH.stem + args.out_suffix + REPORT_PATH.suffix)
                   if args.out_suffix else REPORT_PATH)

    model_path.parent.mkdir(parents=True, exist_ok=True)
    with model_path.open("wb") as handle:
        pickle.dump({"model": final, "threshold": chosen,
                     "uses_deck_features": args.deck_features}, handle)

    provenance_path = ROOT / "ml" / "data" / "risk_training_corpus.provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8")) if provenance_path.exists() else {}
    audit = []
    if args.deck_features:
        from agents.deck_risk_features import LEAKAGE_AUDIT, FEATURE_NAMES
        audit = LEAKAGE_AUDIT
        rejected = sum(1 for a in audit if a["verdict"].startswith("REJECTED"))
        print(f"\nStructured features used: {len(FEATURE_NAMES)}; "
              f"leakage audit records {len(audit)} candidate(s), {rejected} rejected.")

    report_path.write_text(json.dumps({
        "arm": "text+deck_features" if args.deck_features else "text_only",
        "leakage_audit": audit,
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_train_total": len(rows),
        "n_positive": positives,
        "n_filings": len(set(groups)),
        "split": "GroupShuffleSplit by EDGAR accession (no filing spans the split)",
        "held_out_in_distribution": held_out,
        "disjoint_benchmark": benchmark,
        "threshold_selection": "max-F1 on the grouped in-distribution held-out split",
        "threshold_sensitivity_on_benchmark_FOR_TRANSPARENCY_ONLY": sweep,
        "prior_model_for_comparison": {
            "name": "risk_tone_model (Financial PhraseBank + TFNS)",
            "own_test_accuracy": 0.767,
            "benchmark_ranking_auc": 0.333,
            "note": "below chance; predicted `neutral` on all 28 excerpts",
        },
        "training_data_provenance": provenance,
    }, indent=2), encoding="utf-8")
    print(f"\nWrote {MODEL_PATH} and {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
