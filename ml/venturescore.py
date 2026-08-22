"""
Inference wrapper for the VentureFlow Score model.

Loads the calibrated bootstrap ensemble saved by
`ml/scripts/train_venturescore_model.py` and exposes `score_company()`,
which returns a 0-100 score, a calibrated probability, and -- the part that
matters most for this product's audience -- an explicit statement of how
much of that number is actually supported by observed input.

Two sources of uncertainty are reported separately, because they mean
different things to a VC reading the report:

  MODEL uncertainty. The saved artefact is an ensemble of 30 models fit on
  bootstrap resamples of the training data. The spread of their predictions
  for one company estimates how much the score depends on which particular
  1,560 companies happened to be in the training set. A wide spread means
  the training data does not really determine an answer here.

  INPUT uncertainty. The model was trained on Y Combinator directory
  metadata; at inference the product has a pitch deck. Several features
  (remote-work posture, YC subindustry, rebrand history) are usually not
  recoverable from a deck and fall back to defaults. `feature_coverage`
  reports the fraction of features actually observed rather than imputed.
  A score computed mostly from defaults is reported as low confidence no
  matter how tightly the ensemble agrees, because ensemble agreement on
  imputed input is agreement about nothing.

Every failure path returns {"available": False, "reason": ...} rather than
raising, matching the degradation pattern used by every other optional
signal in `ventureflow_agent.py`.
"""

from __future__ import annotations

import math
import pickle
import re
from pathlib import Path
from typing import Any

MODEL_PATH = Path(__file__).resolve().parent / "models" / "venturescore_model.pkl"

# Mirrors TECH_TAG_GROUPS in prepare_venturescore_dataset.py. At training
# time these came from YC's curated tag list; at inference there is no such
# list, so they are matched against the deck text instead. That is a weaker
# signal than a curated tag and is one reason a deck-derived score carries
# lower feature coverage than a directory-derived one.
TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "tag_ai_ml": ("artificial intelligence", " ai ", "machine learning", "generative ai", "llm", "neural"),
    "tag_saas": ("saas", "software as a service", "subscription software"),
    "tag_b2b": ("b2b", "enterprise", "business-to-business"),
    "tag_devtools": ("developer tool", "devops", "sdk", "api platform", "open source", "ci/cd"),
    "tag_fintech": ("fintech", "payments", "banking", "lending", "insurance", "crypto", "web3"),
    "tag_marketplace": ("marketplace", "e-commerce", "ecommerce", "retail"),
    "tag_healthcare": ("healthcare", "health tech", "digital health", "biotech", "clinical", "medical"),
    "tag_infra": ("infrastructure", "cloud computing", "database", "security", "cybersecurity", "data engineering"),
    "tag_consumer": ("consumer app", "social network", "community platform"),
    "tag_analytics": ("analytics", "data science", "business intelligence", "dashboard"),
    "tag_hardware": ("hardware", "robotics", "drone", "manufacturing", "iot", "sensor"),
    "tag_productivity": ("productivity", "automation", "workflow", "collaboration"),
}

_state: dict[str, Any] | None = None
_load_error: str | None = None


def _load() -> None:
    global _state, _load_error
    if _state is not None or _load_error is not None:
        return
    try:
        with open(MODEL_PATH, "rb") as f:
            _state = pickle.load(f)
    except Exception as exc:  # noqa: BLE001 - must never crash the caller
        _load_error = str(exc)


def is_available() -> bool:
    _load()
    return _state is not None


def _derive_tags(text: str) -> tuple[dict[str, int], int]:
    lowered = f" {text.lower()} "
    flags = {
        name: int(any(keyword in lowered for keyword in keywords))
        for name, keywords in TAG_KEYWORDS.items()
    }
    return flags, sum(flags.values())


def score_company(
    description: str,
    one_liner: str = "",
    industry: str | None = None,
    stage: str | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    """Score a company on the 0-100 VentureFlow Score.

    Only `description` is required. Everything else improves feature
    coverage and therefore narrows the reported confidence band; nothing
    else is mandatory, and an absent field is reported as imputed rather
    than quietly guessed.
    """
    _load()
    if _state is None:
        return {
            "available": False,
            "reason": _load_error or "VentureFlow Score model not trained yet -- run ml/scripts/train_venturescore_model.py",
        }

    try:
        import numpy as np

        text = f"{one_liner}. {description}".strip()
        tag_flags, n_tags = _derive_tags(text)
        location_text = (location or "").lower()
        has_location = bool(location_text)

        observed: dict[str, bool] = {}
        values: dict[str, float] = {}

        # -- text shape: always observed, straight from the deck --
        values["desc_len"] = float(len(description))
        values["one_liner_len"] = float(len(one_liner))
        observed["desc_len"] = observed["one_liner_len"] = True

        # -- tags: derived from deck text (weaker than YC's curated tags) --
        for name, flag in tag_flags.items():
            values[name] = float(flag)
            observed[name] = True
        values["num_tags"] = float(n_tags)
        observed["num_tags"] = True

        # -- geography: only if the caller supplied a location --
        values["is_bay_area"] = float(
            any(city in location_text for city in ("san francisco", "palo alto", "mountain view", "berkeley"))
        )
        values["is_us"] = float("usa" in location_text or "united states" in location_text
                                or re.search(r",\s*[A-Z]{2}\s*$", location or "") is not None)
        observed["is_bay_area"] = observed["is_us"] = has_location

        # -- not recoverable from a pitch deck: imputed to the training mode --
        for name in ("is_fully_remote", "is_partly_remote", "is_any_remote", "has_former_name", "nonprofit"):
            values[name] = 0.0
            observed[name] = False

        numeric_features = _state["numeric_features"]
        numeric_row = [[values.get(f, 0.0) for f in numeric_features]]
        numeric_scaled = _state["scaler"].transform(np.array(numeric_row, dtype=float))

        categorical_features = _state["categorical_features"]
        supplied = {
            "industry": industry or "unknown",
            "subindustry_top": industry or "unknown",
            "subindustry_leaf": "unknown",
            "stage": stage or "unknown",
            "batch_season": "unknown",
        }
        categorical_row = [[str(supplied.get(f, "unknown")) for f in categorical_features]]
        categorical_encoded = _state["encoder"].transform(categorical_row)
        observed["industry"] = bool(industry)
        observed["stage"] = bool(stage)

        X = np.hstack([numeric_scaled, categorical_encoded])

        member_predictions = np.array([m.predict_proba(X)[0, 1] for m in _state["ensemble"]])
        probability = float(member_predictions.mean())
        ensemble_std = float(member_predictions.std())
        low = float(np.percentile(member_predictions, 5))
        high = float(np.percentile(member_predictions, 95))

        coverage = sum(observed.values()) / len(observed)

        # Confidence downgrades on EITHER axis. Tight ensemble agreement on
        # mostly-imputed input is not confidence, so coverage can veto it.
        if coverage < 0.55 or ensemble_std > 0.12:
            confidence = "low"
        elif coverage < 0.8 or ensemble_std > 0.07:
            confidence = "medium"
        else:
            confidence = "high"

        base_rate = float(_state["base_rate"])
        return {
            "available": True,
            "venture_score": int(round(probability * 100)),
            "score_range": [int(round(low * 100)), int(round(high * 100))],
            "probability_exit_or_survive": round(probability, 4),
            "confidence": confidence,
            "ensemble_std": round(ensemble_std, 4),
            "feature_coverage": round(coverage, 3),
            "imputed_features": sorted(name for name, seen in observed.items() if not seen),
            "base_rate": round(base_rate, 4),
            "lift_over_base_rate": round(probability - base_rate, 4),
            "model": {
                "family": _state.get("model_family", "unknown"),
                "calibration": _state.get("calibration_method", "unknown"),
                "cv_roc_auc": _state.get("cv_roc_auc"),
                "cv_roc_auc_ci95": _state.get("cv_roc_auc_ci95"),
                "cv_ece": _state.get("cv_ece"),
                "cv_brier": _state.get("cv_brier"),
                "trained_n": _state.get("trained_n"),
                "excluded_contaminated_features": _state.get("excluded_contaminated_features", []),
            },
            "caveat": (
                "Calibrated probability that a company with these characteristics survived or "
                "exited, trained on 1,560 resolved-outcome Y Combinator companies. Features that "
                "encode hindsight (current headcount, company age, batch year) were deliberately "
                "excluded, which lowers headline accuracy and is the reason this number is usable "
                "on an early-stage company at all. Not a return multiple, not validated outside "
                "the YC population, and not an investment verdict."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"VentureFlow Score failed: {exc}"}


def blend_with_evidence(model_result: dict[str, Any], evidence_penalty: float) -> dict[str, Any]:
    """Combine the model's prior with this report's own verified evidence.

    The model sees company *characteristics* only -- it has never read the
    deck's claims, and it cannot know that three of them were refuted by web
    search. That evidence is the part of the pipeline a VC most wants
    reflected in the headline number, so the shipped score is the model
    probability adjusted by an evidence term derived from claim verification
    and risk detection.

    Deliberately a transparent, bounded adjustment rather than a second
    learned layer: there is no labelled data linking claim-verification
    outcomes to company outcomes (that dataset does not exist -- see the
    limitations section in ml/research/), so fitting one would be inventing
    a relationship rather than measuring it. Keeping it an explicit,
    inspectable arithmetic term is the honest option, and both components
    are reported separately so a reader can see which did the work.
    """
    if not model_result.get("available"):
        return model_result
    prior = float(model_result["probability_exit_or_survive"])
    adjusted = max(0.0, min(1.0, prior - evidence_penalty))
    out = dict(model_result)
    out["model_only_score"] = model_result["venture_score"]
    out["evidence_penalty"] = round(evidence_penalty, 4)
    out["venture_score"] = int(round(adjusted * 100))
    out["probability_exit_or_survive"] = round(adjusted, 4)
    shift = adjusted - prior
    out["score_range"] = [
        max(0, min(100, int(round(model_result["score_range"][0] + shift * 100)))),
        max(0, min(100, int(round(model_result["score_range"][1] + shift * 100)))),
    ]
    return out


if __name__ == "__main__":
    import json

    print(json.dumps(score_company(
        description=(
            "We build an AI-powered developer tools platform that automates code review "
            "for enterprise engineering teams. Our SaaS product integrates with existing "
            "CI/CD pipelines and uses machine learning to detect regressions before merge."
        ),
        one_liner="AI code review for enterprise teams",
        industry="B2B",
        stage="Early",
        location="San Francisco, CA, USA",
    ), indent=2))
