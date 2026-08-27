"""Calibrated severity for a risk paragraph, from a model trained on filings.

Thin lazy-loading wrapper over `ml/models/risk_disclosure_model.pkl`, following
the same contract as `embeddings.py`: it returns None rather than a default when
the model is unavailable, so a caller can never mistake "no model" for "no
risk". That distinction is the one this codebase keeps having to relearn.

WHAT THIS IS FOR, AND WHAT IT IS NOT FOR

It supplies **severity**, not firing. Measured on the 28-excerpt disjoint
benchmark, giving the model a vote on whether a risk exists raises ranking AUC
from 0.941 to 0.990 and **doubles the boilerplate false-positive rate, 0.077 to
0.154** -- it fires on a risk-free team slide at p=0.691, higher than two of the
three genuine deck red flags. For a detector reading documents that are
overwhelmingly hedged prose, that trade is bad, because recall is cheap to buy
and precision is not.

So the discrete detectors (`risk_detector.detect_signals` for filing vocabulary,
`deck_financials.deck_risk_signals` for deck arithmetic) decide what is flagged,
and this orders what was flagged. Used that way it costs nothing and adds 0.049
of AUC.

SUBGROUP PERFORMANCE, WHICH MUST NOT BE AVERAGED AWAY

    SEC filing prose (n=22) : AUC 0.992   <- the register it was trained on
    deck prose       (n=6)  : AUC 0.667   <- did not transfer

The combined 0.959 is dominated by the larger subgroup. Quoting it as a general
figure would claim deck-register performance this model does not have.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parent.parent / "ml" / "models" / "risk_disclosure_model.pkl"

_bundle: dict | None = None
_load_attempted = False


def _load() -> dict | None:
    global _bundle, _load_attempted
    if _load_attempted:
        return _bundle
    _load_attempted = True
    try:
        with MODEL_PATH.open("rb") as handle:
            _bundle = pickle.load(handle)
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "Risk disclosure model not available (%s) -- severity ranking will be "
            "unavailable; discrete detectors are unaffected.", exc,
        )
        _bundle = None
    return _bundle


def is_available() -> bool:
    return _load() is not None


def severity(text: str) -> float | None:
    """Calibrated P(this paragraph discloses a material risk), or None.

    None means "not scored", never "not risky". Callers must render the absence
    rather than substituting a number.
    """
    bundle = _load()
    if bundle is None or not (text or "").strip():
        return None
    try:
        return float(bundle["model"].predict_proba([text[:6000]])[0][1])
    except Exception:  # noqa: BLE001
        logger.exception("Risk severity scoring failed")
        return None


def model_metadata() -> dict:
    """What the report should say about where this number came from."""
    bundle = _load()
    if bundle is None:
        return {"available": False,
                "reason": "risk_disclosure_model.pkl not present or unreadable"}
    return {
        "available": True,
        "threshold": bundle.get("threshold"),
        "trained_on": "941 SEC 10-K/10-Q/8-K excerpts from 614 filings, weakly "
                      "labelled by retrieval phrase",
        "benchmark_auc_sec_filings": 0.992,
        "benchmark_auc_deck_register": 0.667,
        "role": "severity ranking only; does not decide whether a risk fired",
    }
