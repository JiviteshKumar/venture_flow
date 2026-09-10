"""The claim judge must never turn an unreadable reply into a verdict.

FOUND BY THE BENCHMARK, NOT BY A UNIT TEST

Two claims in ml/eval/claim_benchmark_subset_retrieval.jsonl came back at
confidence 0.5:

  s10  the reasoning field held raw JSON -- {"verdict": "REFUTES",
       "confidence": 0.96, ... -- cut at 300 characters. The model's actual
       confidence was discarded.
  r35  the reasoning was empty and the verdict NOT_ENOUGH_INFO, although the
       evidence contained the refuting fact verbatim ("Uber now has a market in
       70 countries"; Lyft "primarily operates in the United States and
       Canada").

The judge ran with max_tokens=500 on a reasoning model, so the thinking ate the
budget and the JSON arrived truncated or empty. A fallback then picked a verdict
by searching the raw text for "REFUTES" and then "SUPPORTS", and attached a
confidence of 0.5 the model never gave. Nothing marked the result, so a failure
to judge counted towards the company's score exactly like a real verdict.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ml" / "scripts"))

import agents.claim_verifier as cv  # noqa: E402

EVIDENCE = {
    "snippets": [{"title": "Uber - Wikipedia", "url": "https://en.wikipedia.org/wiki/Uber",
                  "snippet": "Uber operates in around 70 countries."}],
    "full_texts": [],
    "sources": ["https://en.wikipedia.org/wiki/Uber"],
}

GOOD = '{"verdict": "REFUTES", "confidence": 0.96, "reasoning": "Uber is in 70 countries.", "key_evidence": "70 countries"}'
TRUNCATED = '{"verdict": "REFUTES", "confidence": 0.96, "reasoning": "Uber is in 70 coun'


class ScriptedClient:
    """Stands in for the Groq client: replays (content, finish_reason) pairs and
    records every call's keyword arguments."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        content, finish = self.replies.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content),
                                     finish_reason=finish)],
            usage=SimpleNamespace(total_tokens=100),
        )


@pytest.fixture
def scripted(monkeypatch):
    monkeypatch.setattr(cv, "pace_for", lambda *a, **k: 0.0)
    monkeypatch.setattr(cv, "settle_usage", lambda *a, **k: 0)

    def install(*replies):
        client = ScriptedClient(replies)
        monkeypatch.setattr(cv, "get_client", lambda: client)
        return client

    return install


class TestTheBudgetFitsAReasoningModel:
    def test_the_first_attempt_has_room_to_think(self, scripted):
        client = scripted((GOOD, "stop"))
        cv.groq_judge("Lyft operates in more countries than Uber.", EVIDENCE)
        assert client.calls[0]["max_tokens"] >= 2000, (
            "500 tokens is what let the reasoning consume the whole budget"
        )

    def test_the_reply_is_constrained_to_a_json_object(self, scripted):
        client = scripted((GOOD, "stop"))
        cv.groq_judge("claim", EVIDENCE)
        assert client.calls[0]["response_format"] == {"type": "json_object"}


class TestATruncatedReplyIsRetriedNotGuessed:
    def test_the_s10_case_recovers_the_real_verdict_and_confidence(self, scripted):
        """Truncated first reply, complete second: the verdict must carry the
        model's own confidence, not a substituted 0.5."""
        client = scripted((TRUNCATED, "length"), (GOOD, "stop"))
        result = cv.groq_judge("claim", EVIDENCE)

        assert result["verdict"] == "REFUTES"
        assert result["confidence"] == pytest.approx(0.96)
        assert len(client.calls) == 2
        assert client.calls[1]["max_tokens"] > client.calls[0]["max_tokens"]

    def test_the_r35_case_an_empty_reply_is_retried(self, scripted):
        scripted(("", "length"), (GOOD, "stop"))
        assert cv.groq_judge("claim", EVIDENCE)["verdict"] == "REFUTES"


class TestTwoFailuresAreReportedNotScored:
    def test_it_is_marked_degraded_with_its_own_kind(self, scripted):
        scripted(("", "length"), (TRUNCATED, "length"))
        result = cv.groq_judge("claim", EVIDENCE)

        assert result["_degraded"] is True
        assert result["_degraded_kind"] == "unparseable"
        assert result["verdict"] == "NOT_ENOUGH_INFO"

    def test_no_confidence_is_invented(self, scripted):
        scripted(("", "length"), ("", "length"))
        assert cv.groq_judge("claim", EVIDENCE)["confidence"] == 0.0, (
            "a failure to judge was stamped with a confidence the model never gave"
        )

    def test_keywords_in_prose_are_not_mistaken_for_a_verdict(self, scripted):
        """The old fallback read "does not refute" as REFUTES."""
        prose = "This evidence does not REFUTE the claim, nor clearly SUPPORTS it"
        scripted((prose, "stop"), (prose, "stop"))
        result = cv.groq_judge("claim", EVIDENCE)
        assert result["verdict"] == "NOT_ENOUGH_INFO"
        assert result["_degraded"] is True

    def test_the_marker_survives_verify_claims_rebuild(self, scripted, monkeypatch):
        """verify_claim rebuilds its result field by field -- the exact place
        `_degraded` itself was once silently dropped."""
        scripted(("", "length"), ("", "length"))
        monkeypatch.setattr(cv, "collect_evidence", lambda *a, **k: {
            **EVIDENCE, "dropped": [], "retrieved_before_filter": 1,
            "providers": {"wikipedia": 1}, "general_web_unavailable": False,
        })
        result = cv.verify_claim("claim", company="Uber")
        assert result["_degraded"] is True
        assert result["_degraded_kind"] == "unparseable"


class TestParseJudgment:
    @pytest.mark.parametrize("raw", [
        GOOD,
        f"```json\n{GOOD}\n```",
        f"Here is my answer:\n{GOOD}\nThanks.",
    ])
    def test_a_real_judgment_in_any_wrapper_is_read(self, raw):
        assert cv.parse_judgment(raw)["verdict"] == "REFUTES"

    @pytest.mark.parametrize("raw", [
        "", "   ", TRUNCATED, "no json here", "[1, 2, 3]",
        '{"verdict": "MAYBE", "confidence": 0.9}',
        '{"confidence": 0.9}',
    ])
    def test_anything_that_is_not_a_judgment_is_none(self, raw):
        assert cv.parse_judgment(raw) is None

    def test_confidence_is_clamped_and_coerced(self):
        assert cv.parse_judgment('{"verdict":"SUPPORTS","confidence":7}')["confidence"] == 1.0
        assert cv.parse_judgment('{"verdict":"SUPPORTS","confidence":"high"}')["confidence"] == 0.0

    def test_a_lowercase_verdict_is_normalised(self):
        assert cv.parse_judgment('{"verdict":"supports","confidence":0.8}')["verdict"] == "SUPPORTS"


class TestTheBenchmarkKeepsRunning:
    """An unusable reply on one claim is a verifier error to COUNT; only a
    provider outage should stop the run."""

    def test_an_unparseable_claim_does_not_halt_the_benchmark(self):
        import eval_claim_verifier as ev
        assert ev._is_provider_failure({"_degraded": True, "_degraded_kind": "unparseable"}) is False

    def test_a_provider_outage_still_does(self):
        import eval_claim_verifier as ev
        assert ev._is_provider_failure({"_degraded": True, "_degraded_kind": "provider"}) is True
        assert ev._is_provider_failure({"_degraded": True}) is True
