"""A provider outage must never be counted as a finding about the company.

THE FAILURE THIS REPRODUCES

With the Groq daily token quota exhausted (200,000 TPD, a limit that appears in
no response header and is only discoverable from the 429 body), every claim
check on Uber's 2008 deck failed:

    RateLimitError: 429 ... tokens per day (TPD): Limit 200000, Used 199553

Each failure returned the verdict NOT_ENOUGH_INFO, which is the same verdict a
claim gets when the web genuinely cannot settle it. Nothing downstream could
tell the two apart, so all five landed in `unresolved`, the evidence penalty
took 15 points off, and Uber's deck scored 35/100 against a model prior of 50.

A company was marked down because OUR provider was down.

The machinery to prevent this already existed on both sides -- `groq_judge`
raises a `_degraded` flag, and `ventureflow_agent` scans claim results for it --
but `verify_claim` rebuilt its result dict field by field and dropped the flag
in between, so the two halves never met.

These tests pin the whole chain: the flag is raised, it survives `verify_claim`,
and `extract_features` refuses to score on it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.evidence_fusion import extract_features  # noqa: E402


def _claim(verdict: str, degraded: bool = False) -> dict:
    out = {"claim": "Raised $200K", "verdict": verdict, "confidence": 0.0}
    if degraded:
        out["_degraded"] = True
        out["_degraded_reason"] = "claim verifier provider call failed"
    return out


class TestDegradedClaimsDoNotScore:
    def test_an_outage_produces_no_evidence_penalty(self):
        """The Uber case, exactly: five claims, all failed to a 429."""
        features = extract_features(
            [_claim("NOT_ENOUGH_INFO", degraded=True) for _ in range(5)],
            risk_result=None, specialist_results=None,
        )

        assert features.n_claims == 0, (
            "degraded claims were counted as checked claims"
        )
        assert features.unsupported_fraction == 0.0, (
            "a provider outage produced an unsupported-claims penalty; this is "
            "the bug that scored Uber 35/100"
        )
        assert features.supported_fraction == 0.0
        assert features.refuted_fraction == 0.0

    def test_a_genuine_unresolved_claim_still_counts(self):
        """The other half of the contract. A claim that WAS checked and could
        not be settled is a real finding and must still move the score --
        otherwise this fix would simply disable the penalty."""
        features = extract_features(
            [_claim("NOT_ENOUGH_INFO") for _ in range(5)],
            risk_result=None, specialist_results=None,
        )

        assert features.n_claims == 5
        assert features.unsupported_fraction == 1.0

    def test_a_mixed_batch_scores_only_what_was_checked(self):
        """Two verified, one refuted, two lost to the provider: the fractions
        are over the three that actually happened, not over five."""
        features = extract_features(
            [
                _claim("SUPPORTS"),
                _claim("SUPPORTS"),
                _claim("REFUTES"),
                _claim("NOT_ENOUGH_INFO", degraded=True),
                _claim("NOT_ENOUGH_INFO", degraded=True),
            ],
            risk_result=None, specialist_results=None,
        )

        assert features.n_claims == 3
        assert features.supported_fraction == pytest.approx(2 / 3)
        assert features.refuted_fraction == pytest.approx(1 / 3)
        assert features.unsupported_fraction == 0.0

    def test_a_refuted_claim_is_never_suppressed(self):
        """The dangerous direction. Whatever this fix does, it must not make a
        refuted claim disappear -- that is the one verdict an investor most
        needs to survive."""
        features = extract_features(
            [_claim("REFUTES"), _claim("NOT_ENOUGH_INFO", degraded=True)],
            risk_result=None, specialist_results=None,
        )

        assert features.n_claims == 1
        assert features.refuted_fraction == 1.0


class TestTheFlagSurvivesVerifyClaim:
    """The boundary the flag was actually dying at."""

    def test_verify_claim_propagates_a_provider_failure(self, monkeypatch):
        import agents.claim_verifier as cv

        monkeypatch.setattr(cv, "collect_evidence", lambda *a, **k: {
            "snippets": [{"title": "t", "url": "https://example.test", "snippet": "s"}],
            "full_texts": [], "sources": ["https://example.test"], "dropped": [],
        })
        monkeypatch.setattr(cv, "groq_judge", lambda *a, **k: {
            "verdict": "NOT_ENOUGH_INFO",
            "confidence": 0.0,
            "reasoning": "Claim verification is temporarily unavailable.",
            "key_evidence": "",
            "_degraded": True,
            "_degraded_reason": "claim verifier provider call failed",
        })

        result = cv.verify_claim("Raised $200K", company="Uber")

        assert result["_degraded"] is True, (
            "verify_claim rebuilt its result dict without the flag, so no "
            "caller could tell a 429 from an unverifiable claim"
        )
        assert result["_degraded_reason"]

    def test_a_normal_verdict_carries_no_flag(self, monkeypatch):
        import agents.claim_verifier as cv

        monkeypatch.setattr(cv, "collect_evidence", lambda *a, **k: {
            "snippets": [{"title": "t", "url": "https://example.test", "snippet": "s"}],
            "full_texts": [], "sources": ["https://example.test"], "dropped": [],
        })
        monkeypatch.setattr(cv, "groq_judge", lambda *a, **k: {
            "verdict": "SUPPORTS", "confidence": 0.95,
            "reasoning": "Sources confirm it.", "key_evidence": "e",
        })

        result = cv.verify_claim("Raised $200K", company="Uber")

        assert result["verdict"] == "SUPPORTS"
        assert "_degraded" not in result
