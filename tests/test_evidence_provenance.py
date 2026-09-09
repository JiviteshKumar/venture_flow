"""Evidence from the fallback index must not look like evidence from the web.

MEASURED

`ml/scripts/eval_retrieval_quality.py` measured company-scoped retrieval at
94.3% on-topic across 14 real deck claims with DuckDuckGo healthy. A later run
with DuckDuckGo rate-limited -- Wikipedia answering every query -- measured
32.4% across 17 claims. Separate runs on different claim sets, so this is
indicative rather than a controlled comparison; the gap is too large for that
caveat to change the conclusion.

Reaching that second state takes exactly one throttled query: the provider goes
into a 120-second cooldown, which covers the remainder of an analysis. So the
difference between a good evidence base and a thin one is not a rare disaster,
it is an ordinary Tuesday -- and until now the two produced identical-looking
reports, because nothing recorded which index had answered.

Wikipedia is the right fallback. Substituting it silently is the problem: a
claim about a startup's click-through rate checked only against encyclopaedia
articles is a weaker check, and a reader is entitled to know that is what
happened rather than reading "NOT_ENOUGH_INFO" as a finding about the company.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agents.claim_verifier as cv  # noqa: E402


def _outcome(provider, n=3, attempts=None):
    results = [
        {"title": f"t{i}", "url": f"https://{provider}.example/{i}",
         "snippet": "Acme grew revenue."}
        for i in range(n)
    ]
    return {
        "results": results,
        "provider": provider,
        "attempts": attempts if attempts is not None
        else [{"provider": provider, "outcome": "ok", "n": n}],
        "errors": [],
    }


@pytest.fixture
def no_page_fetches(monkeypatch):
    """Keep the test off the network; page text is not what is under test."""
    monkeypatch.setattr(cv, "fetch_page_text", lambda *a, **k: "")


class TestTheAnsweringProviderIsRecorded:
    def test_a_healthy_search_names_its_provider(self, monkeypatch, no_page_fetches):
        monkeypatch.setattr(cv, "search_web_with_provenance",
                            lambda q, max_results=5: _outcome("duckduckgo"))
        evidence = cv.collect_evidence("Revenue grew 4x", company="Acme")

        assert "duckduckgo" in evidence["providers"]
        assert evidence["general_web_unavailable"] is False

    def test_a_throttled_general_index_is_flagged(self, monkeypatch, no_page_fetches):
        """The condition that turns 94% on-topic into 32%."""
        monkeypatch.setattr(cv, "search_web_with_provenance",
                            lambda q, max_results=5: _outcome(
                                "wikipedia",
                                attempts=[
                                    {"provider": "duckduckgo", "outcome": "failed",
                                     "error": "RatelimitException"},
                                    {"provider": "wikipedia", "outcome": "ok", "n": 3},
                                ]))
        evidence = cv.collect_evidence("Revenue grew 4x", company="Acme")

        assert evidence["general_web_unavailable"] is True
        assert set(evidence["providers"]) == {"wikipedia"}

    def test_a_cooldown_counts_as_unavailable(self, monkeypatch, no_page_fetches):
        """A provider skipped because it is cooling down did not answer, and
        the reason it is cooling down is that it already failed once."""
        monkeypatch.setattr(cv, "search_web_with_provenance",
                            lambda q, max_results=5: _outcome(
                                "wikipedia",
                                attempts=[
                                    {"provider": "duckduckgo",
                                     "outcome": "cooling down for another 90s "
                                                "after an earlier failure"},
                                    {"provider": "wikipedia", "outcome": "ok", "n": 3},
                                ]))
        evidence = cv.collect_evidence("Revenue grew 4x", company="Acme")
        assert evidence["general_web_unavailable"] is True


class TestTheReportCanSeeIt:
    def test_verify_claim_surfaces_degraded_evidence(self, monkeypatch):
        monkeypatch.setattr(cv, "collect_evidence", lambda *a, **k: {
            "snippets": [{"title": "t", "url": "https://x/1", "snippet": "s"}],
            "full_texts": [], "sources": ["https://x/1"], "dropped": [],
            "retrieved_before_filter": 1,
            "providers": {"wikipedia": 5},
            "general_web_unavailable": True,
        })
        monkeypatch.setattr(cv, "groq_judge", lambda *a, **k: {
            "verdict": "NOT_ENOUGH_INFO", "confidence": 0.4,
            "reasoning": "the sources do not address the figure",
            "key_evidence": "",
        })

        result = cv.verify_claim("Clicks increased 200%", company="Buffer")

        assert result["evidence_providers"] == {"wikipedia": 5}
        assert result["evidence_degraded"] is True
        reason = result["evidence_degraded_reason"]
        assert "94%" in reason and "32%" in reason, (
            "the reason should carry the measured cost, not just assert one"
        )
        assert "weaker check, not a stronger finding" in reason

    def test_a_healthy_run_is_not_marked_degraded(self, monkeypatch):
        monkeypatch.setattr(cv, "collect_evidence", lambda *a, **k: {
            "snippets": [{"title": "t", "url": "https://x/1", "snippet": "s"}],
            "full_texts": [], "sources": ["https://x/1"], "dropped": [],
            "retrieved_before_filter": 1,
            "providers": {"duckduckgo": 5},
            "general_web_unavailable": False,
        })
        monkeypatch.setattr(cv, "groq_judge", lambda *a, **k: {
            "verdict": "SUPPORTS", "confidence": 0.9,
            "reasoning": "confirmed", "key_evidence": "",
        })

        result = cv.verify_claim("Clicks increased 200%", company="Buffer")

        assert "evidence_degraded" not in result
        assert result["evidence_providers"] == {"duckduckgo": 5}

    def test_degraded_evidence_is_not_the_same_flag_as_a_dead_model(self, monkeypatch):
        """`evidence_degraded` (thin sources) and `_degraded` (the judge never
        ran) are different failures with different remedies, and conflating
        them would make one of them unfixable."""
        monkeypatch.setattr(cv, "collect_evidence", lambda *a, **k: {
            "snippets": [], "full_texts": [], "sources": [], "dropped": [],
            "retrieved_before_filter": 0,
            "providers": {"wikipedia": 1},
            "general_web_unavailable": True,
        })
        monkeypatch.setattr(cv, "groq_judge", lambda *a, **k: {
            "verdict": "NOT_ENOUGH_INFO", "confidence": 0.3,
            "reasoning": "nothing relevant", "key_evidence": "",
        })

        result = cv.verify_claim("Clicks increased 200%", company="Buffer")

        assert result.get("evidence_degraded") is True
        assert not result.get("_degraded"), (
            "the search was thin, but nothing about the language model failed; "
            "marking it `_degraded` would drop the claim from the score, which "
            "is the remedy for a dead model and the wrong one here"
        )
        assert "not evidence of absence" in result["evidence_degraded_reason"]
