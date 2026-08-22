"""Evaluation harness for `agents/claim_verifier.py` against a hand-labeled
benchmark (ml/eval/claim_benchmark.jsonl).

This is the actual "claim-verification benchmark + eval framework" ship-list
deliverable: a fixed, labeled test set plus a script that reports precision,
recall, F1 per verdict class, overall accuracy, a confusion matrix, and a
simple confidence-calibration check (is the model's own stated confidence
actually higher when it's correct?).

The metrics computation (`compute_metrics`) is deliberately a pure function
of a list of {claim_id, gold, predicted, confidence} rows, kept separate from
the part that calls the live claim verifier -- see
tests/test_eval_claim_verifier.py, which exercises `compute_metrics` directly
against a small synthetic case with no network or LLM calls at all. That
test can run (and does run, in CI) without a GROQ_API_KEY; actually running
this script end-to-end against the benchmark needs one, plus live internet
access for the DuckDuckGo search `agents/claim_verifier.py` depends on --
neither was available in the sandbox this benchmark was built in (see
ml/README.md's network-constraints note). Run it yourself once you have a
working GROQ_API_KEY configured.

Usage:
    python ml/scripts/eval_claim_verifier.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_PATH = ROOT / "ml" / "eval" / "claim_benchmark.jsonl"
RESULTS_PATH = ROOT / "ml" / "eval" / "claim_benchmark_results.json"
VERDICTS = ["SUPPORTS", "REFUTES", "NOT_ENOUGH_INFO"]


def load_benchmark() -> list[dict[str, Any]]:
    rows = []
    with open(BENCHMARK_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure function: rows are {gold, predicted, confidence (optional)}.
    No network, no LLM calls -- unit-tested directly."""
    n = len(rows)
    confusion = {g: {p: 0 for p in VERDICTS} for g in VERDICTS}
    for row in rows:
        gold, pred = row["gold"], row["predicted"]
        if gold in confusion and pred in confusion[gold]:
            confusion[gold][pred] += 1

    per_class = {}
    for verdict in VERDICTS:
        tp = confusion[verdict][verdict]
        fp = sum(confusion[g][verdict] for g in VERDICTS if g != verdict)
        fn = sum(confusion[verdict][p] for p in VERDICTS if p != verdict)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        per_class[verdict] = {
            "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3),
            "support": sum(confusion[verdict].values()),
        }

    correct = sum(1 for row in rows if row["gold"] == row["predicted"])
    accuracy = correct / n if n else 0.0

    confidences = [row.get("confidence") for row in rows if row.get("confidence") is not None]
    mean_conf_correct = _mean([row["confidence"] for row in rows if row["gold"] == row["predicted"] and row.get("confidence") is not None])
    mean_conf_incorrect = _mean([row["confidence"] for row in rows if row["gold"] != row["predicted"] and row.get("confidence") is not None])

    return {
        "n": n,
        "accuracy": round(accuracy, 3),
        "per_class": per_class,
        "confusion_matrix": confusion,
        "calibration": {
            "mean_confidence_when_correct": round(mean_conf_correct, 3) if mean_conf_correct is not None else None,
            "mean_confidence_when_incorrect": round(mean_conf_incorrect, 3) if mean_conf_incorrect is not None else None,
            "note": (
                "A well-calibrated verifier should show a higher mean confidence "
                "when correct than when incorrect. If these are close or inverted, "
                "the model's stated confidence isn't trustworthy on its own."
            ) if confidences else "No confidence values recorded.",
        },
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def run_benchmark() -> dict[str, Any]:
    from agents.claim_verifier import verify_claim

    benchmark = load_benchmark()
    rows = []
    for item in benchmark:
        result = verify_claim(item["claim"], verbose=False)
        rows.append({
            "id": item["id"],
            "claim": item["claim"],
            "category": item.get("category", ""),
            "gold": item["gold_verdict"],
            "predicted": result.get("verdict", "NOT_ENOUGH_INFO"),
            "confidence": result.get("confidence"),
        })
        time.sleep(0.5)  # be polite to the search backend across ~30 calls

    metrics = compute_metrics(rows)
    output = {"metrics": metrics, "rows": rows}
    RESULTS_PATH.write_text(json.dumps(output, indent=2))
    return output


if __name__ == "__main__":
    result = run_benchmark()
    print(json.dumps(result["metrics"], indent=2))
    print(f"\nFull per-claim results saved to {RESULTS_PATH}")
