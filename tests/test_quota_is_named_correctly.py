"""A spent daily quota must be reported as a spent daily quota.

FOUND BY THE BENCHMARK RUN THAT HIT IT

The claim-verifier benchmark stopped on its 16th claim with the daily token
quota exhausted ("tokens per day (TPD): Limit 200000, Used 198946"). The reason
it recorded was:

    Claim verification did not run: the language model could not be reached.

Every call site classified the failure by looking for Groq's own wording --
"tokens per day" or "TPD". That matches the FIRST quota 429. It does not match
what every later call receives: once that 429 trips groq_client's breaker,
`pace_for` raises DailyQuotaExhausted, whose message says "daily token quota"
and contains neither phrase. So after the first call, the most common real
failure this product has was described as a connectivity problem -- the one
explanation that sends a reader to check the wrong thing.

Classification now lives in one place, `groq_client.describe_provider_failure`,
so the call sites cannot word it differently again.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import groq_client  # noqa: E402

TPD_429 = RuntimeError(
    "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
    "`openai/gpt-oss-120b` ... on tokens per day (TPD): Limit 200000, Used "
    "198946, Requested 3629.'}}"
)
TPM_429 = RuntimeError(
    "Error code: 429 - {'error': {'message': 'Rate limit reached ... on tokens "
    "per minute (TPM): Limit 8000, Used 6864, Requested 4290.', 'code': "
    "'rate_limit_exceeded'}}"
)


class TestTheClassifier:
    def test_the_breakers_own_exception_is_a_quota_failure(self):
        """The exact case that was misreported."""
        exc = groq_client.DailyQuotaExhausted(
            "Groq daily token quota (200,000/day) is exhausted. It resets in "
            "about 12 minute(s); retrying before then fails the same way."
        )
        assert groq_client.describe_provider_failure(exc) == (
            "the daily Groq token quota is exhausted"
        )

    def test_groqs_own_daily_429_is_a_quota_failure(self):
        assert "daily" in groq_client.describe_provider_failure(TPD_429)

    def test_a_per_minute_limit_is_not_called_the_daily_quota(self):
        """They need opposite responses: one clears in seconds, the other
        tomorrow. Calling a TPM 429 'quota exhausted' would tell a reader to
        give up on something that fixes itself."""
        described = groq_client.describe_provider_failure(TPM_429)
        assert "daily" not in described
        assert "per-minute" in described

    @pytest.mark.parametrize("exc", [
        ConnectionError("connection refused"),
        TimeoutError("read timed out"),
        RuntimeError("503 Service Unavailable"),
    ])
    def test_a_real_connectivity_failure_is_described_as_one(self, exc):
        assert groq_client.describe_provider_failure(exc) == (
            "the language model could not be reached"
        )


@pytest.fixture
def breaker_tripped(monkeypatch):
    """The state the benchmark was in: the first 429 has already tripped the
    breaker, so every later call is refused before it reaches Groq."""
    def refuse(*_a, **_k):
        raise groq_client.DailyQuotaExhausted(
            "Groq daily token quota (200,000/day) is exhausted.")
    return refuse


class TestTheCallSitesUseIt:
    def test_the_claim_judge_names_the_quota(self, monkeypatch, breaker_tripped):
        import agents.claim_verifier as cv

        monkeypatch.setattr(cv, "pace_for", breaker_tripped)
        result = cv.groq_judge("A claim.", {
            "snippets": [{"title": "t", "url": "https://x/1", "snippet": "s"}],
            "full_texts": [],
        })

        assert result["_degraded"] is True
        assert "quota is exhausted" in result["reasoning"], result["reasoning"]
        assert "could not be reached" not in result["reasoning"]

    def test_founder_research_names_the_quota(self, monkeypatch, breaker_tripped):
        import agents.founder_research as fr

        monkeypatch.setattr(fr, "pace_for", breaker_tripped)
        with pytest.raises(fr.ProposalUnavailable) as excinfo:
            fr._propose_names("Uber", "some evidence")
        assert "quota" in str(excinfo.value).lower()

    def test_no_call_site_classifies_by_groqs_wording_any_more(self):
        """The inline check is what went wrong; keep it from coming back."""
        root = Path(__file__).resolve().parents[1]
        offenders = []
        for path in root.glob("**/*.py"):
            if any(p in (".venv", "node_modules", "legacy", "tests") for p in path.parts):
                continue
            if '"tokens per day" in str(exc)' in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(root)))
        assert not offenders, (
            f"{offenders} classify quota failures inline; use "
            f"groq_client.describe_provider_failure"
        )


class TestAFailedJobSaysWhy:
    """The message a user sees when a whole analysis job fails."""

    def test_the_breakers_exception_gets_the_quota_message(self):
        import api

        message = api._describe_failure(groq_client.DailyQuotaExhausted(
            "Groq daily token quota (200,000/day) is exhausted."))
        assert "daily token quota is exhausted" in message
        assert "resets every 24 hours" in message
        assert not message.startswith("Analysis failed:"), (
            "fell through to the raw exception text instead of the actionable "
            "message"
        )

    def test_groqs_own_429_still_gets_it(self):
        import api

        class RateLimitError(Exception):
            pass

        exc = RateLimitError("rate_limit_exceeded ... tokens per day (TPD): Limit 200000")
        assert "daily token quota" in api._describe_failure(exc)

    def test_a_per_minute_limit_is_still_told_to_wait_a_minute(self):
        import api

        class RateLimitError(Exception):
            pass

        exc = RateLimitError("rate_limit_exceeded ... tokens per minute (TPM): Limit 8000")
        assert "Wait a minute" in api._describe_failure(exc)

