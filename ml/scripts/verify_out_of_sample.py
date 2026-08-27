"""Establish the true out-of-sample AUC for both scoring models, by ID.

TWO NUMBERS ON RECORD WERE WRONG, IN DIFFERENT WAYS

**Outcome Model, 0.9747 -- VOID.** A previous session built a 261-company
"holdout" by removing everything present in `venturescore_dataset.jsonl`. That
makes it out-of-sample for the VentureFlow Score and says nothing about the
Outcome Model, which trains on `outcome_dataset.jsonl` -- the file the holdout
was drawn FROM. All 261 were in its training data.

Worth correcting a second thing that was said about it: the Outcome Model's
TRAINER was never at fault. It does a proper stratified 80/20 split, fits TF-IDF
on the training portion only, and reports honest test metrics. The flawed
artefact was the ad-hoc holdout, not the model.

**Score baseline, 0.668 -- also in-sample.** `eval_score_baseline.py` samples 300
companies from `venturescore_dataset.jsonl`, which IS the VentureFlow Score's
training file, and the shipped `.pkl` is fitted on all 1,298 rows. So that
comparison scores the model on its own training data.

WHAT THIS SCRIPT DOES

Rebuilds both evaluations on sets verified disjoint **by identifier**, not by
assumption, and prints the overlap count so the check is visible rather than
promised:

  * Outcome Model -- reconstructs the trainer's own stratified test split
    (SEED=42) and confirms zero index overlap with the training portion.
  * VentureFlow Score -- uses companies absent from its training file, matched
    by name, and confirms zero overlap.

Both are then scored through the SHIPPED inference paths, so what is measured is
what the product would actually use.

    python ml/scripts/verify_out_of_sample.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: F401  (Windows cp1252 guard)

OUT_PATH = ROOT / "ml" / "eval" / "validation" / "out_of_sample_verified.json"
SEED = 42


def roc_auc(scores, labels) -> float | None:
    positives = [s for s, y in zip(scores, labels) if y == 1]
    negatives = [s for s, y in zip(scores, labels) if y == 0]
    if not positives or not negatives:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0
               for p in positives for n in negatives)
    return round(wins / (len(positives) * len(negatives)), 4)


def bootstrap_ci(scores, labels, iterations: int = 2000):
    import random

    rng = random.Random(11)
    n = len(scores)
    values = []
    for _ in range(iterations):
        idx = [rng.randrange(n) for _ in range(n)]
        sub = [labels[i] for i in idx]
        if len(set(sub)) < 2:
            continue
        value = roc_auc([scores[i] for i in idx], sub)
        if value is not None:
            values.append(value)
    if not values:
        return None
    values.sort()
    return [round(values[int(0.025 * len(values))], 4),
            round(values[int(0.975 * len(values))], 4)]


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def outcome_model_out_of_sample() -> dict:
    """Reconstruct the trainer's stratified test split and score it."""
    from sklearn.model_selection import train_test_split

    from ml import inference

    rows = _rows(ROOT / "ml" / "data" / "outcome_dataset.jsonl")
    labels = np.array([int(r["label"]) for r in rows])
    idx = np.arange(len(rows))
    # Identical call to train_outcome_model.main(): same seed, same stratify.
    idx_train, idx_test = train_test_split(
        idx, test_size=0.2, random_state=SEED, stratify=labels,
    )

    overlap = set(idx_train.tolist()) & set(idx_test.tolist())
    train_names = {(rows[i].get("name") or "").strip().lower() for i in idx_train}
    test_names = {(rows[i].get("name") or "").strip().lower() for i in idx_test}
    name_overlap = train_names & test_names

    scored, skipped = [], 0
    for i in idx_test:
        row = rows[int(i)]
        text = (row.get("description") or row.get("text") or "").strip()
        if not text:
            skipped += 1
            continue
        out = inference.score_company(
            text=text,
            industry=row.get("industry") or "unknown",
            stage=row.get("stage") or "unknown",
            num_tags=int(row.get("num_tags") or 0),
            nonprofit=bool(row.get("nonprofit")),
        )
        if not out.get("available"):
            skipped += 1
            continue
        scored.append((float(out["probability_survives_or_exits"]), int(row["label"]),
                       row.get("name")))

    probabilities = [s for s, _, _ in scored]
    truths = [y for _, y, _ in scored]
    return {
        "model": "Outcome Model (ml/inference.py, shipped variant combined_deployable)",
        "split": "trainer's own stratified 80/20 test split, SEED=42",
        "index_overlap_train_test": len(overlap),
        "name_overlap_train_test": len(name_overlap),
        "n_scored": len(scored),
        "n_skipped": skipped,
        "n_success": sum(truths),
        "n_failure": len(truths) - sum(truths),
        "auc": roc_auc(probabilities, truths),
        "auc_ci95": bootstrap_ci(probabilities, truths),
        "trainer_reported_auc": 0.6459,
        "superseded_void_number": 0.9747,
        "why_the_void_number_was_wrong": (
            "Measured on a 261-company set drawn from outcome_dataset.jsonl, "
            "which is this model's own training file. All 261 were in training."
        ),
    }


def venturescore_out_of_sample() -> dict:
    """Companies absent from the VentureFlow Score's training file."""
    from ml import venturescore
    from ventureflow_agent import _evidence_penalty, _legacy_formula_score

    trained_on = {
        (r.get("name") or "").strip().lower()
        for r in _rows(ROOT / "ml" / "data" / "venturescore_dataset.jsonl")
    }
    holdout = [
        r for r in _rows(ROOT / "ml" / "data" / "outcome_dataset.jsonl")
        if (r.get("name") or "").strip().lower() not in trained_on
        and r.get("label") in (0, 1)
        and (r.get("description") or r.get("text"))
    ]
    overlap = {(r.get("name") or "").strip().lower() for r in holdout} & trained_on

    # The evidence state is held IDENTICAL across companies, so only company
    # features vary. That is what makes the legacy formula's constant output
    # visible rather than hidden behind varying inputs.
    neutral = {"refuted": 0, "supported": 1, "n_claims": 4, "risk_score": 35.0,
               "has_revenue": False, "quality_score": 55.0}
    penalty = _evidence_penalty(**neutral)
    legacy_constant = _legacy_formula_score(**neutral)

    model_scores, legacy_scores, truths = [], [], []
    industries: dict[str, int] = {}
    for row in holdout:
        text = (row.get("description") or row.get("text") or "").strip()
        result = venturescore.score_company(
            description=text, one_liner=text[:120],
            industry=row.get("industry"), stage=row.get("stage"), location=None,
        )
        if not result.get("available"):
            continue
        blended = venturescore.blend_with_evidence(result, penalty)
        model_scores.append(float(blended["venture_score"]))
        legacy_scores.append(float(legacy_constant))
        truths.append(int(row["label"]))
        key = str(row.get("industry"))
        industries[key] = industries.get(key, 0) + 1

    return {
        "model": "VentureFlow Score (ml/venturescore.py) vs _legacy_formula_score",
        "split": "companies absent from venturescore_dataset.jsonl, matched by name",
        "name_overlap_with_training": len(overlap),
        "n_scored": len(model_scores),
        "n_success": sum(truths),
        "n_failure": len(truths) - sum(truths),
        "venturescore_auc": roc_auc(model_scores, truths),
        "venturescore_auc_ci95": bootstrap_ci(model_scores, truths),
        "legacy_formula_auc": roc_auc(legacy_scores, truths),
        "legacy_formula_note": (
            "Exactly 0.5 by construction: the formula reads no company feature, "
            "so every company receives the identical score and every pair ties."
        ),
        "superseded_in_sample_number": 0.668,
        "why_the_in_sample_number_was_wrong": (
            "eval_score_baseline.py samples 300 companies from "
            "venturescore_dataset.jsonl, the model's own training file, and the "
            "shipped pickle is fitted on all 1,298 rows."
        ),
        "industry_mix": dict(sorted(industries.items(), key=lambda kv: -kv[1])),
        "scope_caveat": (
            "This holdout is a LEFTOVER, not a random sample. Zero B2B and zero "
            "Fintech: the tech-only filter kept those for training, so the "
            "residue is disproportionately what this product is NOT designed to "
            "evaluate. A genuine out-of-sample measurement on an out-of-scope "
            "population."
        ),
    }


def main() -> int:
    print("Outcome Model -- reconstructing the trainer's stratified test split...")
    outcome = outcome_model_out_of_sample()
    print("VentureFlow Score -- companies absent from its training file...")
    venture = venturescore_out_of_sample()

    print("\n" + "=" * 76)
    print("DISJOINTNESS, CHECKED BY IDENTIFIER RATHER THAN ASSUMED")
    print("=" * 76)
    print(f"  Outcome Model    train/test index overlap : {outcome['index_overlap_train_test']}")
    print(f"                   train/test name  overlap : {outcome['name_overlap_train_test']}")
    print(f"  VentureFlow      holdout/training overlap : {venture['name_overlap_with_training']}")

    print("\n" + "=" * 76)
    print("TRUE OUT-OF-SAMPLE PERFORMANCE")
    print("=" * 76)
    print(f"  Outcome Model      n={outcome['n_scored']:<4} "
          f"({outcome['n_success']}/{outcome['n_failure']})  "
          f"AUC={outcome['auc']}  CI95 {outcome['auc_ci95']}")
    print(f"    trainer's own reported test AUC        : {outcome['trainer_reported_auc']}")
    print(f"    VOID (superseded, in-sample)           : {outcome['superseded_void_number']}")
    print()
    print(f"  VentureFlow Score  n={venture['n_scored']:<4} "
          f"({venture['n_success']}/{venture['n_failure']})  "
          f"AUC={venture['venturescore_auc']}  CI95 {venture['venturescore_auc_ci95']}")
    print(f"    legacy formula on the same set         : {venture['legacy_formula_auc']}")
    print(f"    VOID (superseded, in-sample)           : {venture['superseded_in_sample_number']}")
    print(f"    industry mix                           : {venture['industry_mix']}")
    print("=" * 76)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "what_this_establishes": (
            "The true out-of-sample AUC for both scoring models, on sets verified "
            "disjoint by identifier rather than assumed."
        ),
        "outcome_model": outcome,
        "venturescore": venture,
    }, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
