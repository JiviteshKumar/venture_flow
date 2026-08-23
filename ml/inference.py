"""
Inference wrapper for the trained VentureFlow Outcome Model.

Loads the LightGBM model + fitted TF-IDF/SVD/encoders saved by
`ml/scripts/train_outcome_model.py` and exposes one function,
`score_company()`, that the rest of the app can call. Import errors and
missing-model-file errors are caught and turned into a clear "unavailable"
result rather than raised, so a missing/untrained model degrades the
analysis pipeline the same way every other optional signal in this app
already does (see `ventureflow_agent.py`'s try/except pattern) — it never
takes the whole report down.
"""

from __future__ import annotations

import json
import pickle
import time
from pathlib import Path
from typing import Any

MODEL_DIR = Path(__file__).resolve().parent / "models"
LOG_PATH = Path(__file__).resolve().parent / "logs" / "outcome_score_log.jsonl"

_state: dict[str, Any] | None = None
_load_error: str | None = None


def _load() -> None:
    global _state, _load_error
    if _state is not None or _load_error is not None:
        return
    try:
        import lightgbm as lgb

        booster = lgb.Booster(model_file=str(MODEL_DIR / "outcome_model_combined.txt"))
        with open(MODEL_DIR / "outcome_model_encoders.pkl", "rb") as f:
            encoders = pickle.load(f)
        _state = {"booster": booster, **encoders}
    except Exception as exc:  # noqa: BLE001 - this must never crash the caller
        _load_error = str(exc)


def is_available() -> bool:
    _load()
    return _state is not None


def score_company(
    text: str,
    industry: str = "unknown",
    stage: str = "unknown",
    team_size: int = 0,
    num_tags: int = 0,
    nonprofit: bool = False,
    age_years: float = 0.0,
) -> dict[str, Any]:
    """Return a calibrated outcome-model probability plus honest caveats.

    This is a weak, coarse signal — trained on ~1,560 Y Combinator companies
    with a binary "acquired or went public" vs. "shut down" proxy label
    (test-set ROC-AUC 0.646, see ml/models/outcome_model_report.json). It is
    NOT a return-multiple prediction, NOT validated on non-YC companies, and
    should never be presented as a standalone verdict — it's one additional,
    labeled-data-backed signal alongside the evidence-grounded LLM analysis
    this app already produces, not a replacement for it.

    **`team_size` and `age_years` are accepted and deliberately ignored.**
    They were features until 23 Aug 2026, and they were hindsight: both are
    recorded at snapshot time, years after the outcome. `team_size` alone
    carried more gain than every other structured feature combined, which is
    the model learning that companies which already grew went on to succeed.
    The VentureFlow Score model excludes exactly these; this one did not, so
    the pipeline was running two models under contradictory methodology.
    Excluding them costs 0.058 ROC-AUC (0.704 -> 0.646) — a real cost, and the
    honest number. The parameters stay in the signature because callers pass
    them and removing them would be a breaking change for a value the model
    should not have been using in the first place.
    """
    _load()
    if _state is None:
        return {
            "available": False,
            "reason": _load_error or "Outcome model not trained yet — run ml/scripts/train_outcome_model.py",
        }

    import numpy as np

    tfidf = _state["tfidf"]
    svd = _state["svd"]
    industry_enc = _state["industry_encoder"]
    stage_enc = _state["stage_encoder"]
    scaler = _state["scaler"]
    booster = _state["booster"]

    text_vec = svd.transform(tfidf.transform([text[:2000]]))

    def _safe_encode(enc, value: str) -> int:
        return int(enc.transform([value])[0]) if value in enc.classes_ else -1

    # Order must match train_outcome_model.DEPLOYABLE_FEATURES exactly. The
    # saved encoders carry the names so a future reordering fails loudly here
    # instead of silently feeding the model the wrong columns.
    expected = _state.get("structured_feature_names")
    if expected and expected != ["industry", "stage", "num_tags", "nonprofit"]:
        return {
            "available": False,
            "reason": f"Model was trained on unexpected features {expected}; retrain with ml/scripts/train_outcome_model.py",
        }
    structured = np.array([[
        _safe_encode(industry_enc, industry),
        _safe_encode(stage_enc, stage),
        num_tags,
        int(nonprofit),
    ]], dtype=float)
    structured_scaled = scaler.transform(structured)

    X = np.hstack([text_vec, structured_scaled])
    probability = float(booster.predict(X)[0])

    if probability >= 0.65:
        band = "favorable"
    elif probability >= 0.4:
        band = "mixed"
    else:
        band = "unfavorable"

    _log_score(probability, industry, stage)

    return {
        "available": True,
        "probability_survives_or_exits": round(probability, 3),
        "band": band,
        "model_test_auc": 0.646,
        "excluded_hindsight_features": ["team_size", "age_years"],
        "trained_on": "1,560 Y Combinator companies (yc-oss/api), 3.5+ years post-launch, "
                       "label = Acquired/Public vs. Inactive, Active/unresolved excluded",
        "caveat": (
            "Weak proxy label, YC-only distribution, not validated outside this population. "
            "One input signal, not an investment verdict. team_size and age_years are "
            "excluded as hindsight features, which costs 0.058 ROC-AUC and is the reason "
            "this number is lower than the 0.70 reported before 23 Aug 2026."
        ),
    }


def _log_score(probability: float, industry: str, stage: str) -> None:
    """Append one line for ml/scripts/check_drift.py. Best-effort: a logging
    failure (e.g. read-only filesystem) must never affect the actual result."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps({
                "ts": time.time(),
                "probability": round(probability, 4),
                "industry": industry,
                "stage": stage,
            }) + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    import json

    result = score_company(
        text="AI-powered due diligence platform for venture capital firms, "
             "automating pitch deck analysis and risk assessment.",
        industry="B2B",
        stage="Early",
        team_size=3,
        num_tags=4,
        nonprofit=False,
        age_years=1.0,
    )
    print(json.dumps(result, indent=2))
