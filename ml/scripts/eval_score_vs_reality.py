"""Does the trained score alone correspond to what actually happened?

WHAT THIS IS, STATED NARROWLY

Only the trained models run here. No Groq, no agents, no claim verification, no
risk LLM, no memo. Extraction uses the REGEX fallback path explicitly rather
than the LLM schema extractor, so nothing in this file touches the provider.

That makes this a test of exactly one claim: **does the VentureFlow Score, on
its own, rank companies that succeeded above companies that did not.** It is
not a test of the product. The pipeline's LLM half -- which is most of what a
user sees, and where the worst bug found so far lived -- is entirely untested by
this and needs a separate run once quota allows.

TWO POPULATIONS, REPORTED SEPARATELY AND NEVER BLENDED

**Deck set (n=7).** Real decks, real outcomes, and a fatal limitation: every
company in it succeeded. With no negative class there is no AUC to compute, so
this arm reports raw scores and a single weak check -- do known-good companies
land above the population median. A model returning a constant 95 passes that.
Train and test splits are printed apart, per SPLIT.lock.json.

**YC holdout (n=261).** Companies absent from venturescore_dataset.jsonl, so
genuinely out-of-sample for the score model, and carrying both classes (91
success, 170 failure). This is the arm that can actually answer the question,
and it exists because the published 0.668 discrimination figure was measured on
300 companies of which 300 are in the training file.

    python ml/scripts/eval_score_vs_reality.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: F401  (Windows cp1252 guard)

VALIDATION_DIR = ROOT / "ml" / "eval" / "validation"
MANIFEST_PATH = VALIDATION_DIR / "validation_manifest.json"
HOLDOUT_PATH = VALIDATION_DIR / "yc_holdout.jsonl"
DECK_DIR = ROOT / "ml" / "eval" / "decks"
OUT_PATH = VALIDATION_DIR / "score_vs_reality_results.json"


def roc_auc(scores: list[float], labels: list[int]) -> float | None:
    """Rank AUC with ties counted a half, so a constant scorer lands on exactly
    0.5 rather than on an artefact of sort order."""
    positives = [s for s, y in zip(scores, labels) if y == 1]
    negatives = [s for s, y in zip(scores, labels) if y == 0]
    if not positives or not negatives:
        return None
    wins = sum(
        1.0 if p > n else 0.5 if p == n else 0.0
        for p in positives for n in negatives
    )
    return round(wins / (len(positives) * len(negatives)), 4)


def bootstrap_auc_ci(scores: list[float], labels: list[int], iterations: int = 2000):
    """Percentile CI, because a point AUC on a small sample invites overreading."""
    import random

    if len({*labels}) < 2:
        return None
    rng = random.Random(11)
    n = len(scores)
    values = []
    for _ in range(iterations):
        idx = [rng.randrange(n) for _ in range(n)]
        sub_labels = [labels[i] for i in idx]
        if len({*sub_labels}) < 2:
            continue
        value = roc_auc([scores[i] for i in idx], sub_labels)
        if value is not None:
            values.append(value)
    if not values:
        return None
    values.sort()
    return [round(values[int(0.025 * len(values))], 4),
            round(values[int(0.975 * len(values))], 4)]



def _industry_mix(scored: list[dict], rows: list[dict]) -> dict:
    """Composition of the holdout, because it explains the numbers."""
    import collections

    by_name = {(r.get("name") or "").lower(): r for r in rows}
    counts = collections.Counter(
        (by_name.get((r["name"] or "").lower(), {}) or {}).get("industry")
        for r in scored
    )
    return {str(k): v for k, v in counts.most_common()}


def score_text(description: str, industry: str | None, stage: str | None) -> dict:
    """The trained models only. Deliberately no evidence blending: this arm is
    about the model's own signal, and an evidence penalty derived from an
    unrun pipeline would be noise dressed as information."""
    from ml import inference, venturescore

    out = {"venture_score": None, "outcome_probability": None}
    model = venturescore.score_company(
        description=description, one_liner=description[:120],
        industry=industry, stage=stage, location=None,
    )
    if model.get("available"):
        out["venture_score"] = float(model["venture_score"])
        out["model_confidence"] = model.get("confidence")

    if inference.is_available():
        outcome = inference.score_company(
            text=description, industry=industry or "unknown", stage=stage or "unknown",
        )
        if outcome.get("available"):
            out["outcome_probability"] = float(outcome["probability_survives_or_exits"])
            out["outcome_band"] = outcome.get("band")
    return out


def evaluate_decks() -> dict:
    from document_extractor import extract_document
    from structured_extractor import _regex_fallback

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    rows = []
    for entry in manifest["decks"]:
        path = DECK_DIR / entry["file"]
        if not path.exists():
            rows.append({"company": entry["company"], "split": entry["split"],
                         "error": "deck file missing"})
            continue

        extracted = extract_document(path.name, path.read_bytes())
        text = (extracted.get("text") or "").strip()
        if not text:
            rows.append({"company": entry["company"], "split": entry["split"],
                         "success": entry["success"],
                         "error": f"no text layer ({extracted.get('text_layer')})"})
            continue

        # REGEX path explicitly -- extract_structured() would call Groq.
        info = _regex_fallback(text)
        description = (info.get("description") or text[:1500]).strip()
        scored = score_text(description, entry.get("industry"), None)
        rows.append({
            "company": entry["company"],
            "split": entry["split"],
            "deck_year": entry.get("deck_year"),
            "outcome": entry["outcome"],
            "success": entry["success"],
            "extracted_chars": len(text),
            "regex_claims_found": len(info.get("claims") or []),
            "regex_revenue": info.get("revenue"),
            **scored,
        })

    per_split = {}
    for split in ("train", "test"):
        subset = [r for r in rows if r.get("split") == split and r.get("venture_score") is not None]
        scores = [r["venture_score"] for r in subset]
        labels = [r["success"] for r in subset]
        per_split[split] = {
            "n": len(subset),
            "n_success": sum(labels),
            "n_failure": len(labels) - sum(labels),
            "scores": scores,
            "mean_score": round(statistics.mean(scores), 2) if scores else None,
            "auc": roc_auc(scores, labels),
            "auc_is_none_because": (
                None if roc_auc(scores, labels) is not None
                else "only one outcome class present -- AUC is undefined, not zero"
            ),
        }
    return {"per_deck": rows, "per_split": per_split}


def evaluate_yc_holdout(limit: int | None) -> dict:
    rows = [json.loads(line) for line in HOLDOUT_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    if limit:
        rows = rows[:limit]

    scored, skipped = [], 0
    for row in rows:
        text = (row.get("description") or row.get("text") or "").strip()
        if not text:
            skipped += 1
            continue
        out = score_text(text, row.get("industry"), row.get("stage"))
        if out["venture_score"] is None:
            skipped += 1
            continue
        scored.append({
            "name": row.get("name"), "label": int(row["label"]),
            "venture_score": out["venture_score"],
            "outcome_probability": out.get("outcome_probability"),
        })

    labels = [r["label"] for r in scored]
    venture = [r["venture_score"] for r in scored]
    outcome = [r["outcome_probability"] for r in scored if r["outcome_probability"] is not None]
    outcome_labels = [r["label"] for r in scored if r["outcome_probability"] is not None]

    successes = [r["venture_score"] for r in scored if r["label"] == 1]
    failures = [r["venture_score"] for r in scored if r["label"] == 0]

    return {
        "n_scored": len(scored),
        "n_skipped": skipped,
        "n_success": sum(labels),
        "n_failure": len(labels) - sum(labels),
        "base_rate": round(sum(labels) / len(labels), 4) if labels else None,
        "venturescore_auc": roc_auc(venture, labels),
        "venturescore_auc_ci95": bootstrap_auc_ci(venture, labels),
        "venturescore_mean_success": round(statistics.mean(successes), 2) if successes else None,
        "venturescore_mean_failure": round(statistics.mean(failures), 2) if failures else None,
        # IN-SAMPLE. Reported so the number is on record with its own
        # invalidation attached, never as a validation result.
        #
        # The holdout was built by removing companies present in
        # venturescore_dataset.jsonl -- which makes it out-of-sample for the
        # VentureFlow Score and NOT for the Outcome Model, because
        # train_outcome_model.py fits on outcome_dataset.jsonl, the file this
        # holdout was drawn FROM. Measured: 261 of 261 holdout companies are in
        # the Outcome Model's training data.
        "outcome_model_auc_IN_SAMPLE_NOT_A_VALIDATION": roc_auc(outcome, outcome_labels) if outcome else None,
        "outcome_model_auc_ci95_IN_SAMPLE": bootstrap_auc_ci(outcome, outcome_labels) if outcome else None,
        "outcome_model_caveat": (
            "This figure is IN-SAMPLE and must not be quoted as validation. All "
            "261 companies are in train_outcome_model.py's training file. A high "
            "value here is what an in-sample measurement looks like, not evidence "
            "of skill."
        ),
        "industry_mix": _industry_mix(scored, rows),
        "scope_caveat": (
            "The holdout is a LEFTOVER, not a random sample, and its composition "
            "shows it: Consumer 162, Healthcare 62, Industrials 28, Real Estate 8 "
            "-- and ZERO B2B and ZERO Fintech. That is the tech-only scope filter "
            "working in reverse. venturescore_dataset.jsonl kept the tech "
            "companies, so what is left over is disproportionately the ones this "
            "product is explicitly NOT designed to evaluate. The VentureFlow "
            "Score AUC below is therefore a genuine out-of-sample measurement on "
            "an OUT-OF-SCOPE population, which is weaker evidence than an "
            "in-scope holdout would be and is the best available today."
        ),
        "per_company": scored,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-holdout", type=int, default=None)
    args = parser.parse_args()

    if not MANIFEST_PATH.exists():
        print("Harness not built. Run ml/scripts/build_validation_harness.py first.")
        return 2

    print("Scoring decks (regex extraction, trained models only -- no Groq)...")
    decks = evaluate_decks()
    print("Scoring the YC holdout (never seen by the score model)...")
    holdout = evaluate_yc_holdout(args.limit_holdout)

    print("\n" + "=" * 74)
    print("DECK SET -- train and test reported separately, never blended")
    print("=" * 74)
    for split in ("train", "test"):
        block = decks["per_split"][split]
        print(f"  {split:<6} n={block['n']}  successes={block['n_success']}  "
              f"failures={block['n_failure']}  mean score={block['mean_score']}")
        if block["auc"] is None:
            print(f"         AUC: undefined -- {block['auc_is_none_because']}")
    print("\n  per deck:")
    for row in decks["per_deck"]:
        if "error" in row:
            print(f"    {row['company']:<10} [{row.get('split','?'):<5}] ERROR: {row['error']}")
        else:
            print(f"    {row['company']:<10} [{row['split']:<5}] score={row['venture_score']:<5} "
                  f"outcome={row['outcome']:<9} chars={row['extracted_chars']:<6} "
                  f"regex_claims={row['regex_claims_found']}")

    print("\n" + "=" * 74)
    print("YC HOLDOUT -- the arm that can actually measure discrimination")
    print("=" * 74)
    print(f"  n={holdout['n_scored']} ({holdout['n_success']} success / "
          f"{holdout['n_failure']} failure, base rate {holdout['base_rate']:.1%})")
    print(f"  VentureFlow Score AUC : {holdout['venturescore_auc']}  "
          f"CI95 {holdout['venturescore_auc_ci95']}")
    print(f"    mean score, success : {holdout['venturescore_mean_success']}")
    print(f"    mean score, failure : {holdout['venturescore_mean_failure']}")
    print(f"  Outcome Model AUC     : "
          f"{holdout['outcome_model_auc_IN_SAMPLE_NOT_A_VALIDATION']} "
          f"<- IN-SAMPLE, NOT A VALIDATION")
    print(f"    (all 261 holdout companies are in the Outcome Model's training file)")
    print(f"  holdout industry mix  : {holdout['industry_mix']}")
    print(f"    ^ zero B2B, zero Fintech: this is the non-tech residue left by the")
    print(f"      tech-only filter, i.e. out of the product's stated scope.")
    print("=" * 74)

    OUT_PATH.write_text(json.dumps({
        "what_this_measures": (
            "Whether the TRAINED SCORE ALONE ranks real companies by their real "
            "outcome. Regex extraction, no Groq, no agents, no claim "
            "verification, no risk LLM, no memo."
        ),
        "what_this_does_not_measure": (
            "The product. Everything a user actually reads is LLM-generated and "
            "none of it ran here. Regex extraction is also materially worse than "
            "the LLM schema extractor, so the deck arm's inputs are degraded "
            "relative to production."
        ),
        "deck_set": decks,
        "deck_set_caveat": (
            "All seven companies succeeded, so AUC is undefined on both splits. "
            "This arm cannot measure discrimination and is reported for "
            "completeness, not as evidence."
        ),
        "yc_holdout": holdout,
        "yc_holdout_note": (
            "Genuinely out-of-sample: every company is absent from "
            "venturescore_dataset.jsonl. Contrast with "
            "ml/eval/score_baseline_comparison.json, whose 300-company sample is "
            "300/300 inside the training file."
        ),
    }, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
