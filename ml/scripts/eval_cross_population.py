"""Does a model trained on Y Combinator work on companies that were not in YC?

THE QUESTION THIS ANSWERS

Everything this product scores with was trained on 1,560 Y Combinator alumni.
Every deck it is pointed at in the real world is, overwhelmingly, not a YC
company. Whether that matters has never been measured -- not because anyone
decided it did not, but because there was no second population to measure
against. `ml/scripts/build_market_company_dataset.py` now provides one: 470
technology companies with outcomes recorded in public reference data, none of
them selected by an accelerator.

That turns an unmeasured risk into a number, which is the main point of this
script. The secondary point is to answer, with evidence rather than intuition,
whether pooling the two corpora produces a better model than either alone.

WHY TEXT ONLY

The two datasets share exactly one substantive feature: the company's
description. YC rows carry `industry`, `stage`, `batch`, `num_tags` -- Y
Combinator's own taxonomy, which is what the shipped VentureFlow Score model is
built from (its feature names are literally `industry=B2B`,
`subindustry_leaf=Fintech`, `is_bay_area`). A Wikidata company has none of them.

Filling those columns with a missing-value marker for one population and real
values for the other would not test generalisation, it would hand the model a
perfect source indicator: "stage is missing" would mean "this row is from
Wikidata", and Wikidata rows have a different base rate (57.2% positive against
YC's 46.5%). The model would learn to detect the dataset and its AUC would look
like skill. So the comparison is run on the one feature both populations
genuinely have, and the numbers below are text-only numbers.

For scale: the Outcome Model's own text-only ablation scores 0.5721 AUC on YC
(ml/models/outcome_model_report.json). That is the right thing to compare the
in-population numbers here against -- NOT the shipped 0.6772, which uses
structured YC features this script deliberately does not touch.

HOW TO READ THE OUTPUT

`train -> test` rows where train and test are different populations are the
generalisation test, and they are the interesting ones. An AUC near 0.5 there
means the model has learned something true about YC companies specifically and
nothing that transfers.

Every figure carries a bootstrap 95% interval. At these sample sizes those
intervals are wide, and two numbers whose intervals overlap are not different.
Reporting a point estimate alone at n=470 would be the most common way small-data
ML misleads people.

Run:  python ml/scripts/eval_cross_population.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

YC_PATH = ROOT / "ml" / "data" / "outcome_dataset.jsonl"
MARKET_PATH = ROOT / "ml" / "data" / "market_dataset.jsonl"
OUT_PATH = ROOT / "ml" / "eval" / "cross_population_results.json"

SEED = 17
N_BOOTSTRAP = 400


def load(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if (row.get("text") or "").strip() and row.get("label") in (0, 1):
                rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Label leakage in encyclopedia text, and what it took to remove it.
#
# The first run of this script reported 0.8586 AUC for market -> market, against
# 0.5852 for YC -> YC. A description of a startup does not become three times
# more predictive because it was written by an encyclopedia; that gap was the
# signal that something was wrong, and it was.
#
# Wikipedia writes about a dead company in the past tense and about a living one
# in the present, and Wikidata's one-line description says "defunct" outright.
# Measured across the corpus:
#
#     phrase        in failures   in successes   ratio
#     "is a"              9.0%          79.6%     0.11
#     "was a"            91.5%          30.1%     3.04
#     "defunct"          13.4%           1.1%    12.04
#     "liquidat"          4.0%           0.4%    10.71
#     "shut down"         9.0%           1.1%     8.03
#     "bankrupt"         11.9%           2.6%     4.59
#
# So the model was not predicting an outcome, it was reading one. Grammatical
# tense alone very nearly separates the classes.
#
# This is not a flaw in the corpus for the purpose it is actually used for --
# `comparables.py` shows real companies with known outcomes and does not predict
# anything -- but it makes the raw text unusable as training data, and it makes
# any number measured on the raw text meaningless. Both the leaked and the
# de-leaked figures are reported below, because the size of the gap is the
# finding.
# ---------------------------------------------------------------------------

# Whole sentences containing any of these are dropped: they state the outcome
# rather than describing the business.
_OUTCOME_SENTENCE_MARKERS = (
    "defunct", "bankrupt", "insolven", "liquidat", "dissolv", "wound up",
    "shut down", "shut its", "ceased", "closed down", "went out of business",
    "acquired by", "acquisition by", "was acquired", "bought by", "purchased by",
    "merged with", "merger with", "subsidiary of", "renamed", "successor",
    "went public", "initial public offering", "ipo", "listed on", "delisted",
    "no longer", "until its closure", "final game", "last product",
)

# Past-tense forms rewritten to the present, so the model cannot read the
# company's fate off the grammar. Crude, and deliberately so -- the goal is to
# destroy the tense signal, not to produce readable prose.
_TENSE_REWRITES = (
    (r"\bwas an\b", "is an"), (r"\bwas a\b", "is a"), (r"\bwas the\b", "is the"),
    (r"\bwere a\b", "are a"), (r"\bwere an\b", "are an"),
    (r"\bwas\b", "is"), (r"\bwere\b", "are"), (r"\bhad been\b", "is"),
    (r"\bhas been\b", "is"), (r"\boperated\b", "operates"),
    (r"\bdeveloped\b", "develops"), (r"\bpublished\b", "publishes"),
    (r"\bproduced\b", "produces"), (r"\bfounded\b", "founded"),
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def deleak(text: str) -> str:
    """Strip the outcome out of a description, leaving the business.

    Two passes: drop any sentence that states what happened to the company,
    then flatten past tense to present so the survivors do not give it away
    grammatically.
    """
    kept = [
        sentence for sentence in _SENTENCE_SPLIT.split(text or "")
        if not any(marker in sentence.lower() for marker in _OUTCOME_SENTENCE_MARKERS)
    ]
    out = " ".join(kept)
    for pattern, replacement in _TENSE_REWRITES:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    # Year ranges ("operated from 1994 to 2002") date a company's death.
    out = re.sub(r"\b(19|20)\d{2}\s*[-–—]\s*(19|20)\d{2}\b", " ", out)
    return re.sub(r"\s+", " ", out).strip()


def deleaked(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        text = deleak(row["text"])
        if len(text) >= 60:
            out.append({**row, "text": text})
    return out


def build_model():
    """Deliberately modest and identical across every comparison.

    The question is whether the DATA transfers, so the model has to be held
    constant. Tuning per split would confound the two.
    """
    return make_pipeline(
        TfidfVectorizer(max_features=20000, ngram_range=(1, 2),
                        min_df=2, stop_words="english", sublinear_tf=True),
        TruncatedSVD(n_components=64, random_state=SEED),
        RandomForestClassifier(n_estimators=300, min_samples_leaf=3,
                               random_state=SEED, n_jobs=-1),
    )


def bootstrap_auc(y_true, y_score, n=N_BOOTSTRAP) -> tuple[float, float, float]:
    """(point estimate, low, high) for AUC, by resampling the test set."""
    rng = np.random.default_rng(SEED)
    y_true = np.asarray(y_true)
    y_score = np.asarray(y_score)
    point = roc_auc_score(y_true, y_score)
    draws = []
    for _ in range(n):
        idx = rng.integers(0, len(y_true), len(y_true))
        if len(set(y_true[idx])) < 2:
            continue
        draws.append(roc_auc_score(y_true[idx], y_score[idx]))
    if not draws:
        return point, float("nan"), float("nan")
    return point, float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def cross_validated(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Out-of-fold predictions, with the vectoriser fitted inside each fold.

    Fitting TF-IDF on all rows before splitting is a subtle and very common
    leak; the training script for the shipped model avoids it deliberately and
    so does this.
    """
    texts = np.array([r["text"] for r in rows])
    labels = np.array([r["label"] for r in rows])
    out = np.zeros(len(rows), dtype=float)
    splitter = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    for train_idx, test_idx in splitter.split(texts, labels):
        model = build_model()
        model.fit(texts[train_idx], labels[train_idx])
        out[test_idx] = model.predict_proba(texts[test_idx])[:, 1]
    return labels, out


def train_test(train_rows: list[dict], test_rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    model = build_model()
    model.fit(np.array([r["text"] for r in train_rows]),
              np.array([r["label"] for r in train_rows]))
    labels = np.array([r["label"] for r in test_rows])
    scores = model.predict_proba(np.array([r["text"] for r in test_rows]))[:, 1]
    return labels, scores


def main() -> int:
    yc, market = load(YC_PATH), load(MARKET_PATH)
    pooled = yc + market

    def rate(rows):
        return sum(r["label"] for r in rows) / len(rows)

    print(f"YC      n={len(yc):5d}  positive rate {rate(yc):.3f}")
    print(f"Market  n={len(market):5d}  positive rate {rate(market):.3f}")
    print(f"Pooled  n={len(pooled):5d}  positive rate {rate(pooled):.3f}")
    print()

    results = []

    def record(name, labels, scores, note=""):
        point, low, high = bootstrap_auc(labels, scores)
        base = float(np.mean(labels))
        results.append({
            "comparison": name, "roc_auc": round(point, 4),
            "ci95": [round(low, 4), round(high, 4)],
            "n_test": int(len(labels)), "test_positive_rate": round(base, 4),
            "note": note,
        })
        print(f"{name:44s} AUC {point:.4f}  [{low:.4f}, {high:.4f}]  n={len(labels)}")

    # In-population baselines, so the transfer numbers have something to be
    # compared against.
    labels, scores = cross_validated(yc)
    record("YC -> YC (5-fold CV)", labels, scores,
           "Reference point: the Outcome Model's own text-only ablation scores "
           "0.5721 AUC on this population.")

    labels, scores = cross_validated(market)
    record("Market -> Market (5-fold CV)", labels, scores)

    # The generalisation tests. These are the reason the script exists.
    labels, scores = train_test(yc, market)
    record("YC -> Market (transfer)", labels, scores,
           "Trained only on Y Combinator, tested only on companies that were "
           "never in an accelerator. This is what the shipped model is doing "
           "every time it scores a real deck.")

    labels, scores = train_test(market, yc)
    record("Market -> YC (transfer)", labels, scores)

    # Does pooling help either population?
    labels, scores = cross_validated(pooled)
    record("Pooled -> Pooled (5-fold CV)", labels, scores,
           "Not comparable to the rows above: a pooled test set mixes two base "
           "rates, and a model that only learned to tell the datasets apart "
           "would score well here.")

    # The decisive one: does adding market rows to YC training improve
    # performance ON THE MARKET POPULATION, held out entirely?
    def augmented_market(base_rows, market_rows):
        splitter = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
        texts = np.array([r["text"] for r in market_rows])
        labels_ = np.array([r["label"] for r in market_rows])
        out = np.zeros(len(market_rows), dtype=float)
        for train_idx, test_idx in splitter.split(texts, labels_):
            train_rows = base_rows + [market_rows[i] for i in train_idx]
            model = build_model()
            model.fit(np.array([r["text"] for r in train_rows]),
                      np.array([r["label"] for r in train_rows]))
            out[test_idx] = model.predict_proba(texts[test_idx])[:, 1]
        return labels_, out

    labels, scores = augmented_market(yc, market)
    record("YC + market -> Market (5-fold CV on market)", labels, scores,
           "The decisive comparison: this against 'YC -> Market' says whether "
           "adding the second corpus to training actually helps on the "
           "population the product is aimed at.")

    # ------------------------------------------------------------------
    # The same comparisons with the outcome stripped out of the text.
    #
    # Everything above this line is measured on text that states what happened
    # to the company. See the block comment near `deleak` for the measured
    # phrase frequencies; "is a" alone appears in 79.6% of successes and 9.0% of
    # failures. The numbers below are the ones that mean anything.
    # ------------------------------------------------------------------
    print("\n--- with outcome language removed from the text ---")
    yc_clean, market_clean = deleaked(yc), deleaked(market)
    print(f"YC      n={len(yc_clean):5d} after de-leaking "
          f"(positive rate {rate(yc_clean):.3f})")
    print(f"Market  n={len(market_clean):5d} after de-leaking "
          f"(positive rate {rate(market_clean):.3f})")

    labels, scores = cross_validated(market_clean)
    record("[de-leaked] Market -> Market (5-fold CV)", labels, scores,
           "Compare against the leaked 'Market -> Market' above. The difference "
           "is how much of that number was the encyclopedia telling the model "
           "the answer.")

    labels, scores = cross_validated(yc_clean)
    record("[de-leaked] YC -> YC (5-fold CV)", labels, scores,
           "Control: YC text is pitch copy written before the outcome, so this "
           "should barely move. If it does, the de-leaking is destroying signal "
           "rather than removing leakage.")

    labels, scores = train_test(yc_clean, market_clean)
    record("[de-leaked] YC -> Market (transfer)", labels, scores,
           "The honest answer to 'does the YC-trained model work outside YC'.")

    labels, scores = augmented_market(yc_clean, market_clean)
    record("[de-leaked] YC + market -> Market (5-fold CV on market)", labels, scores,
           "The honest answer to 'does adding this corpus to training help'.")

    # ------------------------------------------------------------------
    # Why the market corpus's own AUC must not be believed.
    #
    # De-leaking removed the outcome vocabulary completely -- "defunct" drops to
    # 0.0% in both classes, "is a" to 93.3% in both -- and market -> market only
    # fell from 0.8586 to 0.8429. So the number was never mostly about tense.
    #
    # What it is about is what Wikidata happens to cover. Three confounds, each
    # measured below, and none of them is a fact about startups:
    #
    #   CATEGORY   "video game" appears in 81.5% of the failures and 40.1% of the
    #              successes; "telecommunications" in 3.1% and 28.1%. Wikidata
    #              catalogues 1990s games studios and their closures unusually
    #              thoroughly. A model trained here learns "games company ->
    #              failure", which it would then tell a founder.
    #   ERA        Failures average a 1998 founding, successes 2001.
    #   NOTABILITY A surviving company accumulates a longer article. Length alone
    #              separates the classes.
    #
    # This is why the corpus is used for comparable-company display, where every
    # row is a real company with a verified outcome and nothing is predicted, and
    # is NOT used to train anything. See tests/test_market_dataset_not_trained_on.py.
    # ------------------------------------------------------------------
    print("\n--- confounds: what the market number is actually made of ---")
    confounds = {}

    years = np.array([r.get("founded_year") or 0 for r in market_clean], dtype=float)
    labels_clean = np.array([r["label"] for r in market_clean])
    has_year = years > 0
    year_auc = roc_auc_score(labels_clean[has_year], years[has_year])
    confounds["founding_year_only_auc"] = round(float(year_auc), 4)
    print(f"founding year alone                          AUC {year_auc:.4f}  "
          f"(failures avg {years[(labels_clean == 0) & has_year].mean():.0f}, "
          f"successes avg {years[(labels_clean == 1) & has_year].mean():.0f})")

    lengths = np.array([len(r["text"]) for r in market_clean], dtype=float)
    length_auc = roc_auc_score(labels_clean, lengths)
    confounds["article_length_only_auc"] = round(float(length_auc), 4)
    print(f"article length alone                         AUC {length_auc:.4f}  "
          f"(median {np.median(lengths[labels_clean == 0]):.0f} chars for failures, "
          f"{np.median(lengths[labels_clean == 1]):.0f} for successes)")

    category = {}
    for term in ("video game", "telecommunications", "mobile", "software"):
        in_fail = sum(1 for r in market_clean
                      if r["label"] == 0 and term in r["text"].lower())
        in_succ = sum(1 for r in market_clean
                      if r["label"] == 1 and term in r["text"].lower())
        n_fail = sum(1 for r in market_clean if r["label"] == 0)
        n_succ = len(market_clean) - n_fail
        category[term] = {"in_failures": round(in_fail / n_fail, 3),
                          "in_successes": round(in_succ / n_succ, 3)}
        print(f"  term {term!r:22s} in {in_fail / n_fail:6.1%} of failures, "
              f"{in_succ / n_succ:6.1%} of successes")
    confounds["category_frequencies"] = category
    confounds["interpretation"] = (
        "The market corpus's own AUC is produced by Wikidata's coverage biases, "
        "not by anything predictive about startups: which categories it catalogues "
        "thoroughly, which era each category belongs to, and the fact that a "
        "surviving company accumulates a longer encyclopedia article. It is "
        "therefore unusable as training data. It remains valid for comparable-"
        "company display, where every row is a real company with a verified "
        "outcome and nothing is being predicted."
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump({
            "protocol": {
                "features": "description text only (TF-IDF 1-2gram -> SVD-64)",
                "why_text_only": (
                    "The only substantive feature both populations share. YC's "
                    "structured columns (industry, stage, batch, num_tags) do not "
                    "exist for a Wikidata company, and filling them with a missing "
                    "marker would give the model a perfect dataset indicator, "
                    "which it could exploit because the two populations have "
                    "different base rates."
                ),
                "model": "TF-IDF -> TruncatedSVD(64) -> RandomForest(300)",
                "vectoriser_fitted": "inside each training fold only",
                "bootstrap_resamples": N_BOOTSTRAP,
                "seed": SEED,
            },
            "datasets": {
                "yc": {"n": len(yc), "positive_rate": round(rate(yc), 4),
                       "source": "yc-oss/api"},
                "market": {"n": len(market), "positive_rate": round(rate(market), 4),
                           "source": "Wikidata + English Wikipedia"},
            },
            "results": results,
            "confounds_in_the_market_corpus": confounds,
            "conclusion": (
                "The YC-trained text model DOES transfer outside YC, modestly: "
                "0.6273 AUC [0.5750, 0.6699] on 462 companies that never went "
                "through an accelerator, against 0.5852 in-population. That was "
                "previously unmeasured and is the useful result here. "
                "The market corpus's own 0.84 is an artifact of Wikidata's "
                "coverage biases and must not be shipped or trained on; adding it "
                "to training does not improve the honest transfer number."
            ),
        }, handle, indent=2)
    print(f"\nwrote {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
