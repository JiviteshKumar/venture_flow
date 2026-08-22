"""Drift check for the Outcome Model.

Compares the distribution of probabilities the model has actually produced
for real due-diligence calls (ml/logs/outcome_score_log.jsonl, written by
ml/inference.py's score_company()) against the distribution the same model
file produces on its own training population, recomputed fresh on every run
-- not a cached reference, so this always reflects whatever model is
currently on disk. A live distribution that's drifted far from the training
population is the signal that retraining is worth doing; it does not by
itself mean the model got worse, only that what's being fed into it looks
different from what it learned on.

Uses the Population Stability Index (PSI) -- a standard, dependency-free
drift metric: PSI < 0.1 = no significant drift, 0.1-0.25 = moderate (watch
it), > 0.25 = significant (retrain).

Usage:
    python ml/scripts/check_drift.py
Needs at least MIN_LIVE_SCORES logged calls to say anything meaningful.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.inference import score_company  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "ml" / "logs" / "outcome_score_log.jsonl"
TRAIN_DATA_PATH = ROOT / "ml" / "data" / "outcome_dataset.jsonl"
MIN_LIVE_SCORES = 20
BIN_EDGES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


def _bucketize(values: list[float]) -> list[float]:
    counts = [0] * (len(BIN_EDGES) - 1)
    for v in values:
        idx = min(int(v * (len(BIN_EDGES) - 1)), len(BIN_EDGES) - 2)
        counts[idx] += 1
    total = sum(counts) or 1
    return [c / total for c in counts]


def _psi(reference: list[float], live: list[float]) -> float:
    total = 0.0
    for r, l in zip(reference, live):
        r = max(r, 1e-4)
        l = max(l, 1e-4)
        total += (l - r) * math.log(l / r)
    return total


def _reference_distribution(sample_size: int = 300) -> list[float]:
    if not TRAIN_DATA_PATH.exists():
        raise FileNotFoundError(
            f"{TRAIN_DATA_PATH} not found -- run ml/scripts/prepare_outcome_dataset.py first."
        )
    probs = []
    with open(TRAIN_DATA_PATH) as f:
        for i, line in enumerate(f):
            if i >= sample_size:
                break
            row = json.loads(line)
            result = score_company(
                text=row.get("description", ""),
                industry=row.get("industry", "unknown"),
                stage=row.get("stage", "unknown"),
                team_size=row.get("team_size", 0) or 0,
                num_tags=row.get("num_tags", 0) or 0,
                nonprofit=bool(row.get("nonprofit", False)),
                age_years=row.get("age_years", 0.0) or 0.0,
            )
            if result.get("available"):
                probs.append(result["probability_survives_or_exits"])
    return probs


def _live_distribution() -> list[float]:
    if not LOG_PATH.exists():
        return []
    probs = []
    with open(LOG_PATH) as f:
        for line in f:
            try:
                probs.append(json.loads(line)["probability"])
            except (json.JSONDecodeError, KeyError):
                continue
    return probs


def main() -> None:
    live = _live_distribution()
    print(f"Logged live scoring calls: {len(live)}")
    if len(live) < MIN_LIVE_SCORES:
        print(
            f"Need at least {MIN_LIVE_SCORES} logged calls to compare distributions "
            f"meaningfully (have {len(live)}). Nothing to report yet -- this is "
            f"expected on a fresh install. Keep using the app; ml/inference.py "
            f"logs every call automatically."
        )
        return

    reference = _reference_distribution()
    if not reference:
        print("Could not compute a reference distribution (is the model trained?).")
        return

    ref_buckets = _bucketize(reference)
    live_buckets = _bucketize(live)
    psi = _psi(ref_buckets, live_buckets)

    if psi < 0.1:
        verdict = "No significant drift."
    elif psi < 0.25:
        verdict = "Moderate drift -- worth watching, not yet urgent."
    else:
        verdict = "Significant drift -- consider retraining (see ml/README.md's reproduction steps)."

    print(f"PSI: {psi:.3f} — {verdict}")
    print(f"Reference (training-population) bucket shares: {[round(b, 2) for b in ref_buckets]}")
    print(f"Live (production-traffic) bucket shares:       {[round(b, 2) for b in live_buckets]}")


if __name__ == "__main__":
    main()
