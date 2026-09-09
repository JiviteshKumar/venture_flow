"""The benchmark harness must refuse to score an outage as a prediction.

WHAT HAPPENED

`ml/scripts/eval_claim_verifier.py` has a guard whose whole purpose is to stop
a run rather than record a provider failure as a model verdict. It worked by
comparing the verifier's `reasoning` string for exact equality with a constant
in the eval script:

    _PROVIDER_FAILURE_REASON = "Claim verification is temporarily unavailable."

Then `verify_claim` was improved to say which failure had occurred -- "Claim
verification did not run: the daily Groq token quota is exhausted." -- and the
guard stopped matching. Nothing failed, nothing warned. A 19-claim run made
against an exhausted quota recorded all nineteen as NOT_ENOUGH_INFO at
confidence 0.0 and wrote a results file reporting 0.0 accuracy on the
public-fact subset.

That number describes the token budget, not the verifier, and it was written
into a file whose entire purpose is to be quoted later.

The guard now reads the structured `_degraded` flag that `verify_claim`
already sets. These tests pin the behaviour to the flag rather than to any
sentence, so improving the message again cannot re-break the guard.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ml" / "scripts"))

import eval_claim_verifier as ev  # noqa: E402


class TestADegradedResultIsNeverAPrediction:
    def test_the_structured_flag_is_what_counts(self):
        assert ev._is_provider_failure({
            "verdict": "NOT_ENOUGH_INFO",
            "confidence": 0.0,
            "reasoning": "any wording at all, now or in future",
            "_degraded": True,
        }) is True

    def test_the_current_quota_message_is_recognised(self):
        """The exact shape that slipped through and produced the 0.0 file."""
        assert ev._is_provider_failure({
            "verdict": "NOT_ENOUGH_INFO",
            "confidence": 0.0,
            "reasoning": (
                "Claim verification did not run: the daily Groq token quota is "
                "exhausted. This is a fact about this deployment, not about the "
                "claim."
            ),
        }) is True

    def test_the_historical_message_is_still_recognised(self):
        """Partial logs from earlier runs must not be re-scored as verdicts."""
        assert ev._is_provider_failure({
            "reasoning": "Claim verification is temporarily unavailable.",
        }) is True


class TestARealVerdictIsNotMistakenForAnOutage:
    """The costly direction. A guard that over-triggers stops every run and
    makes the benchmark unrunnable."""

    @pytest.mark.parametrize("verdict,reasoning", [
        ("NOT_ENOUGH_INFO",
         "No external evidence could be retrieved for this claim."),
        ("NOT_ENOUGH_INFO",
         "The sources describe Lyft's IPO but never mention Uber's, so the "
         "comparison cannot be resolved."),
        ("SUPPORTS",
         "Multiple reliable sources state that Stripe was co-founded in 2010."),
        ("REFUTES",
         "WeWork withdrew its IPO filing in September 2019."),
    ])
    def test_a_genuine_judgement_passes(self, verdict, reasoning):
        assert ev._is_provider_failure({
            "verdict": verdict, "confidence": 0.9, "reasoning": reasoning,
        }) is False

    def test_a_genuinely_empty_web_is_a_finding_not_an_outage(self):
        """"Nothing has been written about this company" is the correct answer
        for the nonexistent-company subset, and the benchmark depends on being
        able to score it."""
        assert ev._is_provider_failure({
            "verdict": "NOT_ENOUGH_INFO",
            "confidence": 0.0,
            "reasoning": "No external evidence could be retrieved for this claim.",
            "total_sources": 0,
        }) is False

    def test_missing_fields_do_not_crash(self):
        assert ev._is_provider_failure({}) is False


class TestTheCommittedResultsAreNotPoisoned:
    def test_no_published_row_is_a_recorded_outage(self):
        """A results file exists to be quoted. If an outage ever lands in one,
        every figure computed from it is wrong by an unknown amount."""
        import json

        path = ROOT / "ml" / "eval" / "claim_benchmark_results.json"
        if not path.exists():
            pytest.skip("no committed results file")

        rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
        poisoned = [r["id"] for r in rows if ev._is_provider_failure(r)]
        assert not poisoned, (
            f"{len(poisoned)} rows in {path.name} record a provider outage as a "
            f"model prediction: {poisoned[:10]}"
        )
