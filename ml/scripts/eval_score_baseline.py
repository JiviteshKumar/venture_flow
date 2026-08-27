"""Compare the VentureFlow Score against the pre-ML `_legacy_formula_score()`
fallback on the same inputs.

The legacy formula is the honest baseline for the headline number: it is what
this product shipped before any model existed, it still runs whenever the model
file cannot be loaded, and until now nothing had ever measured the two side by
side. "We replaced a hand-tuned formula with a trained model" is a claim, and
this is the file that turns it into a number.

Two measurements, because they answer different questions.

**1. Discrimination (`ml/research/score_baseline_comparison.json` ->
`discrimination`).** Both scorers are run over a held-out sample of real Y
Combinator companies whose outcome is known, with the evidence state held
identical across every company, and each score's ROC-AUC against the true
label is reported. Holding evidence constant is the whole point: it isolates
what each scorer knows about *the company*. The legacy formula reads only
claim counts, a risk score and a data-quality score -- nothing about the
company at all -- so with evidence fixed it returns the same number for every
company and cannot rank them. That is not a gotcha, it is the structural
difference between the two, and it is worth having on record as a number
rather than as an argument.

**2. Sensitivity (`evidence_sensitivity`).** The reverse case: one company,
varying evidence states. Here the legacy formula does move, and the comparison
is about how much and in which direction, so the trade the model makes -- a
much wider evidence swing in the formula, a population prior in the model -- is
visible.

    python ml/scripts/eval_score_baseline.py

Writes `ml/research/score_baseline_comparison.json`, following the artifact
convention of `ml/research/venturescore_experiments.json`: the numbers in any
write-up must be reloadable from a committed file, not trusted from a log.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: F401  (imported for side effect)
from ml import venturescore
from ventureflow_agent import _evidence_penalty, _legacy_formula_score

DATA_PATH = ROOT / "ml" / "data" / "venturescore_dataset.jsonl"
OUT_PATH = ROOT / "ml" / "research" / "score_baseline_comparison.json"
SEED = 42
SAMPLE_N = 300

# A neutral, realistic evidence state: a few claims checked, most unverifiable,
# moderate risk, no revenue disclosed. This is what an early-stage deck
# actually produces, and it is held identical across companies in the
# discrimination test so that only company features vary.
NEUTRAL_EVIDENCE = {
    "refuted": 0,
    "supported": 1,
    "n_claims": 4,
    "risk_score": 35.0,
    "has_revenue": False,
    "quality_score": 55.0,
}

# Evidence states for the sensitivity sweep, worst to best.
EVIDENCE_STATES: list[tuple[str, dict[str, Any]]] = [
    ("no claims extractable", {"refuted": 0, "supported": 0, "n_claims": 0, "risk_score": 60.0, "has_revenue": False, "quality_score": 30.0}),
    ("all claims refuted", {"refuted": 3, "supported": 0, "n_claims": 3, "risk_score": 60.0, "has_revenue": False, "quality_score": 50.0}),
    ("claims unverifiable, high risk", {"refuted": 0, "supported": 0, "n_claims": 4, "risk_score": 60.0, "has_revenue": False, "quality_score": 50.0}),
    ("neutral (the discrimination setting)", dict(NEUTRAL_EVIDENCE)),
    ("claims supported, revenue disclosed", {"refuted": 0, "supported": 3, "n_claims": 4, "risk_score": 20.0, "has_revenue": True, "quality_score": 75.0}),
    ("everything checks out", {"refuted": 0, "supported": 5, "n_claims": 5, "risk_score": 10.0, "has_revenue": True, "quality_score": 90.0}),
]


def roc_auc(scores: list[float], labels: list[int]) -> float | None:
    """Rank-based AUC. Ties count a half, which is what makes a constant
    scorer come out at exactly 0.5 rather than at an artefact of sort order."""
    positives = [s for s, y in zip(scores, labels) if y == 1]
    negatives = [s for s, y in zip(scores, labels) if y == 0]
    if not positives or not negatives:
        return None
    wins = sum(
        1.0 if p > n else 0.5 if p == n else 0.0
        for p in positives for n in negatives
    )
    return round(wins / (len(positives) * len(negatives)), 4)


def load_sample() -> list[dict]:
    rows = [
        json.loads(line)
        for line in DATA_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    labeled = [r for r in rows if r.get("label") in (0, 1) and (r.get("description") or r.get("text"))]
    random.Random(SEED).shuffle(labeled)
    return labeled[:SAMPLE_N]


def score_pair(row: dict, evidence: dict[str, Any]) -> tuple[float | None, float]:
    """(VentureFlow Score, legacy formula score) for one company + evidence state."""
    model_result = venturescore.score_company(
        description=row.get("description") or row.get("text") or "",
        one_liner=row.get("one_liner", "") or "",
        industry=row.get("industry"),
        stage=row.get("stage"),
        location=row.get("location"),
    )
    penalty = _evidence_penalty(**evidence)
    blended = venturescore.blend_with_evidence(model_result, penalty)
    model_score = blended.get("venture_score") if blended.get("available") else None
    legacy = _legacy_formula_score(**evidence)
    return model_score, legacy


def main() -> None:
    if not venturescore.is_available():
        raise SystemExit(
            "The VentureFlow Score model is not loadable; there is nothing to compare "
            "the baseline against. Train it with ml/scripts/train_venturescore_model.py"
        )

    sample = load_sample()
    print(f"Scoring {len(sample)} real labeled YC companies under one fixed evidence state ...")

    model_scores: list[float] = []
    legacy_scores: list[float] = []
    labels: list[int] = []
    for row in sample:
        model_score, legacy = score_pair(row, NEUTRAL_EVIDENCE)
        if model_score is None:
            continue
        model_scores.append(float(model_score))
        legacy_scores.append(float(legacy))
        labels.append(int(row["label"]))

    model_auc = roc_auc(model_scores, labels)
    legacy_auc = roc_auc(legacy_scores, labels)
    distinct_legacy = len(set(round(s, 6) for s in legacy_scores))

    print(f"  n={len(labels)} base rate={sum(labels) / len(labels):.3f}")
    print(f"  VentureFlow Score ROC-AUC : {model_auc}")
    print(f"  Legacy formula    ROC-AUC : {legacy_auc}   "
          f"({distinct_legacy} distinct value(s) across {len(legacy_scores)} companies)")

    print("\nEvidence sensitivity on a single company ...")
    probe = sample[0]
    sensitivity = []
    for label, evidence in EVIDENCE_STATES:
        model_score, legacy = score_pair(probe, evidence)
        sensitivity.append({
            "evidence_state": label,
            "evidence": evidence,
            "venture_score": model_score,
            "legacy_formula_score": round(legacy, 2),
        })
        print(f"  {label:<38} model={model_score}  legacy={legacy:.1f}")

    model_span = [s["venture_score"] for s in sensitivity if s["venture_score"] is not None]
    legacy_span = [s["legacy_formula_score"] for s in sensitivity]

    output = {
        "what_this_compares": (
            "The shipped VentureFlow Score against ventureflow_agent._legacy_formula_score(), "
            "the hand-tuned pre-ML fallback, on identical inputs."
        ),
        "discrimination": {
            "description": (
                "Real YC companies with known outcomes, scored under one identical evidence "
                "state so that only company features differ. ROC-AUC against the true label."
            ),
            "n_companies": len(labels),
            "base_rate": round(sum(labels) / len(labels), 4) if labels else None,
            "fixed_evidence_state": NEUTRAL_EVIDENCE,
            "venturescore_roc_auc": model_auc,
            "legacy_formula_roc_auc": legacy_auc,
            "legacy_formula_distinct_values": distinct_legacy,
            "interpretation": (
                "The legacy formula takes no company feature as input, so with evidence held "
                "fixed it returns one value for every company and its AUC is 0.5 by "
                "construction -- it cannot rank two companies against each other at all. "
                "The comparison is therefore not 'the model is a bit better'; it is that the "
                "baseline has no company-level discrimination to be better than. Whatever "
                "company-level signal the product has comes entirely from the model."
            ),
        },
        "evidence_sensitivity": {
            "description": (
                "One company, six evidence states. This is the axis the legacy formula does "
                "respond on."
            ),
            "probe_company": probe.get("name"),
            "rows": sensitivity,
            "venture_score_span": (
                round(max(model_span) - min(model_span), 2) if model_span else None
            ),
            "legacy_formula_span": round(max(legacy_span) - min(legacy_span), 2),
        },
        "reproduce": "python ml/scripts/eval_score_baseline.py",
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\nSaved to {OUT_PATH}")


if __name__ == "__main__":
    main()
