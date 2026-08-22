"""Train the firm-personalization ranking model from the user's own recorded
invest/pass decisions (migrations/005_investment_decisions.sql, captured via
POST /reports/{report_id}/decision).

This is a mechanism, not a claim of results. There is no data yet on day one
of this feature existing -- MIN_DECISIONS below is a floor below which
fitting anything would just be overfitting noise, and ml/personalization.py
reports itself unavailable (with a running count) until that floor is met.
Run this again periodically as decisions accumulate; it always refits from
scratch on the full history, which is the right call at this data scale.

Usage:
    python ml/scripts/train_personalization_model.py
Requires DATABASE_URL to be configured (this reads from the live Neon table).
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from db import list_decisions_with_reports  # noqa: E402

MIN_DECISIONS = 15
FEATURE_NAMES = [
    "final_score",
    "claims_supported_ratio",
    "risk_overall_score",
    "ml_outcome_probability",
]
MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "personalization_model.pkl"


def _features_from_report(raw_output: dict) -> list[float]:
    sections = raw_output.get("sections", {})
    claims = sections.get("claims", {})
    risk = sections.get("risk", {})
    ml_outcome = sections.get("ml_outcome_model", {})

    checked = claims.get("checked", 0) or 0
    supported = claims.get("supported", 0) or 0
    claims_ratio = (supported / checked) if checked else 0.5

    return [
        float(raw_output.get("final_score", 50) or 50),
        float(claims_ratio),
        float(risk.get("overall_score", 30) or 30),
        float(ml_outcome.get("probability_survives_or_exits", 0.5) or 0.5),
    ]


def main() -> None:
    rows = list_decisions_with_reports()
    n = len(rows)
    print(f"Found {n} recorded decision(s).")

    if n < MIN_DECISIONS:
        print(
            f"Need at least {MIN_DECISIONS} decisions to fit anything meaningful "
            f"(have {n}). Not training. Keep recording invest/pass calls via "
            f"POST /reports/{{report_id}}/decision and re-run this later."
        )
        return

    X = np.array([_features_from_report(row["raw_output"]) for row in rows])
    y = np.array([1 if row["decision"] == "invest" else 0 for row in rows])

    if len(set(y.tolist())) < 2:
        print(
            "All recorded decisions are the same class (all invest or all pass) "
            "-- a classifier can't learn anything from single-class data yet. "
            "Not training."
        )
        return

    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(X, y)

    # With N this small, a held-out test split would be noise on top of noise.
    # Report training-set fit honestly labeled as such -- not a claim of
    # generalization, just a sanity check that it learned *something*.
    train_preds = model.predict(X)
    train_proba = model.predict_proba(X)[:, 1]
    train_accuracy = accuracy_score(y, train_preds)
    train_auc = roc_auc_score(y, train_proba) if len(set(y.tolist())) == 2 else None

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({"model": model, "feature_names": FEATURE_NAMES, "n_decisions": n}, f)

    report_path = MODEL_PATH.parent / "personalization_model_report.json"
    report_path.write_text(json.dumps({
        "n_decisions": n,
        "train_accuracy": round(float(train_accuracy), 3),
        "train_auc": round(float(train_auc), 3) if train_auc is not None else None,
        "feature_names": FEATURE_NAMES,
        "coefficients": model.coef_[0].tolist(),
        "note": (
            "Metrics above are TRAINING-set fit, not held-out performance -- "
            "at this sample size a train/test split would be too noisy to "
            "trust either way. Re-evaluate this honestly once there are "
            "enough decisions (50+) to hold out a real test set."
        ),
    }, indent=2))

    print(f"Trained on {n} decisions. Training accuracy: {train_accuracy:.3f}.")
    print(f"Saved model to {MODEL_PATH}")
    print(f"Saved report to {report_path}")


if __name__ == "__main__":
    main()
