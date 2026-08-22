"""Firm-personalization ranking layer -- inference side.

Re-ranks a report's score toward this user's own accumulated invest/pass
pattern, once `ml/scripts/train_personalization_model.py` has enough
decisions (MIN_DECISIONS there) to fit on. Below that floor -- which is where
a brand-new install always starts -- this honestly reports itself
unavailable with a running count, rather than pretending to personalize
against data that doesn't exist yet.
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).resolve().parent / "models" / "personalization_model.pkl"
_state: dict[str, Any] | None = None
_load_attempted = False


def _load() -> dict[str, Any] | None:
    global _state, _load_attempted
    if _load_attempted:
        return _state
    _load_attempted = True
    try:
        with open(_MODEL_PATH, "rb") as f:
            _state = pickle.load(f)
    except FileNotFoundError:
        _state = None
    except Exception:
        logger.exception("Failed to load personalization model")
        _state = None
    return _state


def personalize(report: dict[str, Any]) -> dict[str, Any]:
    """Never raises. Returns a dict with `available`; when True, also
    `personalized_fit` (0-100, how well this report matches the user's past
    invest pattern) and `note`."""
    state = _load()
    if state is None:
        try:
            from db import count_decisions
            so_far = count_decisions()
        except Exception:
            so_far = None
        from ml.scripts.train_personalization_model import MIN_DECISIONS
        return {
            "available": False,
            "reason": "Not enough recorded decisions yet to personalize.",
            "decisions_so_far": so_far,
            "decisions_needed": MIN_DECISIONS,
        }

    try:
        model = state["model"]
        sections = report.get("sections", {})
        claims = sections.get("claims", {})
        risk = sections.get("risk", {})
        ml_outcome = sections.get("ml_outcome_model", {})
        checked = claims.get("checked", 0) or 0
        supported = claims.get("supported", 0) or 0
        claims_ratio = (supported / checked) if checked else 0.5
        features = [[
            float(report.get("final_score", 50) or 50),
            float(claims_ratio),
            float(risk.get("overall_score", 30) or 30),
            float(ml_outcome.get("probability_survives_or_exits", 0.5) or 0.5),
        ]]
        fit_probability = float(model.predict_proba(features)[0][1])
        return {
            "available": True,
            "personalized_fit": round(fit_probability * 100),
            "trained_on_decisions": state.get("n_decisions"),
            "note": (
                "How closely this report resembles the deals you've personally "
                "marked 'invest' vs. 'pass' so far -- your own pattern, not a "
                "market-wide signal. Refit periodically as you record more decisions."
            ),
        }
    except Exception:
        logger.exception("Personalization inference failed")
        return {"available": False, "reason": "Personalization model raised an unexpected error."}
