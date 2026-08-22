"""Unit-tests the metrics computation in ml/scripts/eval_claim_verifier.py
against a small synthetic case. No network, no LLM calls -- this can run in
CI without a GROQ_API_KEY. It does not run the live benchmark against
agents/claim_verifier.py; see that script's module docstring for why."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.scripts.eval_claim_verifier import compute_metrics, load_benchmark


def test_benchmark_file_loads_and_has_expected_shape():
    rows = load_benchmark()
    assert len(rows) >= 20
    verdicts = {row["gold_verdict"] for row in rows}
    assert verdicts == {"SUPPORTS", "REFUTES", "NOT_ENOUGH_INFO"}
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)), "benchmark ids must be unique"


def test_compute_metrics_perfect_predictions():
    rows = [
        {"gold": "SUPPORTS", "predicted": "SUPPORTS", "confidence": 0.9},
        {"gold": "REFUTES", "predicted": "REFUTES", "confidence": 0.85},
        {"gold": "NOT_ENOUGH_INFO", "predicted": "NOT_ENOUGH_INFO", "confidence": 0.6},
    ]
    metrics = compute_metrics(rows)
    assert metrics["accuracy"] == 1.0
    for verdict_metrics in metrics["per_class"].values():
        assert verdict_metrics["precision"] == 1.0
        assert verdict_metrics["recall"] == 1.0
        assert verdict_metrics["f1"] == 1.0


def test_compute_metrics_catches_systematic_confusion():
    # A verifier that always says NOT_ENOUGH_INFO should score 0 recall on
    # SUPPORTS/REFUTES and low precision on NOT_ENOUGH_INFO.
    rows = [
        {"gold": "SUPPORTS", "predicted": "NOT_ENOUGH_INFO", "confidence": 0.5},
        {"gold": "REFUTES", "predicted": "NOT_ENOUGH_INFO", "confidence": 0.5},
        {"gold": "NOT_ENOUGH_INFO", "predicted": "NOT_ENOUGH_INFO", "confidence": 0.5},
    ]
    metrics = compute_metrics(rows)
    assert metrics["per_class"]["SUPPORTS"]["recall"] == 0.0
    assert metrics["per_class"]["REFUTES"]["recall"] == 0.0
    assert metrics["per_class"]["NOT_ENOUGH_INFO"]["precision"] == pytest_approx_third()


def pytest_approx_third():
    # 1 true positive out of 3 predicted-as-NOT_ENOUGH_INFO
    return round(1 / 3, 3)


def test_compute_metrics_calibration_direction():
    rows = [
        {"gold": "SUPPORTS", "predicted": "SUPPORTS", "confidence": 0.95},
        {"gold": "REFUTES", "predicted": "REFUTES", "confidence": 0.9},
        {"gold": "SUPPORTS", "predicted": "REFUTES", "confidence": 0.3},
        {"gold": "REFUTES", "predicted": "SUPPORTS", "confidence": 0.2},
    ]
    metrics = compute_metrics(rows)
    calibration = metrics["calibration"]
    assert calibration["mean_confidence_when_correct"] > calibration["mean_confidence_when_incorrect"]
