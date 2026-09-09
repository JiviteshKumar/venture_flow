"""An empty search result is not the same thing as a broken search provider.

WHAT WENT WRONG

Two defects, both in the seam between "the web has nothing" and "we could not
reach the web", and both silent.

1. `ddgs` raises `DDGSException("No results found.")` for a query with no
   hits. That is an answer, but it arrives as an exception, so the provider
   chain recorded a provider FAILURE and put DuckDuckGo in a 120-second
   cooldown. One analysis issues about twenty-five searches and deck claims are
   elliptical enough that at least one is always unfindable -- so the first
   such query sidelined the general-web provider for the remainder of the
   analysis, and every later claim was judged on Wikipedia alone.

2. Once a provider answered with zero results, the chain stopped, on the
   reasoning that a provider which answers has answered. But DuckDuckGo returns
   an empty page when it soft-throttles as well as when the web is genuinely
   empty, and the two are byte-identical. On ml/eval/claim_benchmark.jsonl this
   cost two outright errors: "IBM acquired Red Hat in 2019 for approximately
   $34 billion" and "WeWork successfully completed its initial IPO in 2019"
   both retrieved zero sources and scored NOT_ENOUGH_INFO. Wikipedia, one line
   further down the chain, answers both.

The tests below pin both directions, because the cheap fix for either one
breaks the other: a chain that treats every empty answer as a failure would
retry four providers for every genuinely unfindable claim, and a chain that
treats every exception as an answer would report a total outage as "the web has
nothing on this company".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agents.web_search as ws  # noqa: E402


@pytest.fixture(autouse=True)
def clean_cooldowns():
    ws.reset_cooldowns()
    yield
    ws.reset_cooldowns()


def _providers(monkeypatch, **behaviour):
    """Install a fake provider chain. Each value is either a list of results or
    an exception instance to raise."""
    calls: list[str] = []

    def make(name, outcome):
        def fn(_query, _max_results):
            calls.append(name)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        return fn

    monkeypatch.setattr(ws, "PROVIDERS", [
        (name, make(name, outcome), lambda: True)
        for name, outcome in behaviour.items()
    ])
    return calls


HIT = [{"title": "t", "url": "https://example.com/a", "snippet": "s"}]


class TestEmptyIsConfirmedBeforeItIsBelieved:
    def test_an_empty_first_provider_does_not_end_the_chain(self, monkeypatch):
        """The IBM/Red Hat case: DuckDuckGo came back empty and the fact was
        one provider further down."""
        calls = _providers(monkeypatch, duckduckgo=[], wikipedia=HIT)
        out = ws.search("IBM acquired Red Hat")

        assert out["results"] == HIT
        assert out["provider"] == "wikipedia"
        assert calls == ["duckduckgo", "wikipedia"]

    def test_two_providers_agreeing_on_nothing_ends_the_chain(self, monkeypatch):
        """The other half. A genuinely unfindable company must not cost a
        lookup at every provider in the list."""
        calls = _providers(monkeypatch, duckduckgo=[], wikipedia=[],
                           brave=HIT, tavily=HIT)
        out = ws.search("Zarnathine Dynamics Series B")

        assert out["results"] == []
        assert out["empty_confirmed_by"] == ["duckduckgo", "wikipedia"]
        assert calls == ["duckduckgo", "wikipedia"], (
            "emptiness was confirmed twice; the remaining providers should not "
            "have been asked"
        )

    def test_a_successful_search_reports_no_confirmations(self, monkeypatch):
        _providers(monkeypatch, duckduckgo=HIT)
        assert ws.search("anything")["empty_confirmed_by"] == []


class TestNoResultsIsNotAProviderFailure:
    def test_an_unfindable_query_does_not_cool_down_duckduckgo(self, monkeypatch):
        """The expensive one. A cooldown here costs every LATER query in the
        same analysis, not just this one."""
        from ddgs.exceptions import DDGSException

        monkeypatch.setattr(ws, "PROVIDERS", [
            ("duckduckgo", ws._duckduckgo, lambda: True),
        ])

        class FakeDDGS:
            def __enter__(self): return self
            def __exit__(self, *_a): return False
            def text(self, _q, max_results=None):
                raise DDGSException("No results found.")

        import ddgs
        monkeypatch.setattr(ddgs, "DDGS", FakeDDGS)

        out = ws.search("a query with no hits")

        assert out["results"] == []
        assert "duckduckgo" not in ws._cooldowns, (
            "an empty result sidelined the general-web provider for 120s, "
            "starving every remaining query in the analysis"
        )
        assert out["errors"] == []
        assert out["attempts"][0]["outcome"] == "ok"

    @pytest.mark.parametrize("exc_name", ["RatelimitException", "TimeoutException"])
    def test_a_real_failure_is_still_a_failure(self, monkeypatch, exc_name):
        """The fix must not swallow the failures the cooldown exists for."""
        import ddgs.exceptions as ddgs_exc

        exc = getattr(ddgs_exc, exc_name)("throttled")
        monkeypatch.setattr(ws, "PROVIDERS", [
            ("duckduckgo", ws._duckduckgo, lambda: True),
        ])

        class FakeDDGS:
            def __enter__(self): return self
            def __exit__(self, *_a): return False
            def text(self, _q, max_results=None):
                raise exc

        import ddgs
        monkeypatch.setattr(ddgs, "DDGS", FakeDDGS)

        out = ws.search("anything")

        assert out["errors"], "a genuine rate limit was recorded as an answer"
        assert "duckduckgo" in ws._cooldowns


class TestAnOutageIsStillDistinguishable:
    """founder_research depends on this: it must never report our own
    connectivity failure as a fact about the company."""

    def test_every_provider_failing_raises(self, monkeypatch):
        _providers(monkeypatch,
                   duckduckgo=RuntimeError("refused"),
                   wikipedia=RuntimeError("refused"))
        with pytest.raises(ws.AllProvidersFailed):
            ws.search_or_raise("Uber founders")

    def test_a_confirmed_empty_web_does_not_raise(self, monkeypatch):
        """"Nobody has written about this company" is an answer, and callers
        must be able to act on it rather than treat it as an outage."""
        _providers(monkeypatch, duckduckgo=[], wikipedia=[])
        out = ws.search_or_raise("Zarnathine Dynamics founders")
        assert out["results"] == []
