"""Failover across search providers.

The defect: every web lookup in the product went through one DuckDuckGo call.
DuckDuckGo rate-limits aggressively under sustained use, and when it does, claim
verification, founder research and adverse-news detection all lose their
evidence at the same moment -- mostly silently, because an empty result set is
indistinguishable from "the web has nothing on this company".

These tests use stub providers rather than the live network. What is being
tested is the chain's decision-making -- when it moves on, when it stops, what
it remembers, and what it tells the caller -- and that has to be exercised with
failures that can be produced on demand. There is one opt-in live test at the
bottom for the providers themselves.
"""

from __future__ import annotations

import os

import pytest

from agents import web_search


@pytest.fixture(autouse=True)
def clean_cooldowns():
    """Cooldowns are module-global and would leak between tests.

    Exactly the failure class conftest.py documents at length: state at module
    scope, mutated by one test, read by the next.
    """
    web_search.reset_cooldowns()
    yield
    web_search.reset_cooldowns()


def _result(name):
    return [{"title": f"{name} hit", "url": f"https://example.test/{name}",
             "snippet": f"from {name}"}]


def stub_providers(monkeypatch, *specs):
    """Install a provider chain from (name, behaviour) pairs.

    `behaviour` is either a list of results to return or an Exception to raise.
    """
    calls: list[str] = []
    providers = []
    for name, behaviour in specs:
        def make(name=name, behaviour=behaviour):
            def provider(query, max_results):
                calls.append(name)
                if isinstance(behaviour, Exception):
                    raise behaviour
                return behaviour
            return provider
        providers.append((name, make(), lambda: True))
    monkeypatch.setattr(web_search, "PROVIDERS", providers)
    return calls


class TestFailover:
    def test_the_first_working_provider_answers(self, monkeypatch):
        calls = stub_providers(
            monkeypatch,
            ("alpha", _result("alpha")),
            ("beta", _result("beta")),
        )
        outcome = web_search.search("anything")

        assert outcome["provider"] == "alpha"
        assert outcome["results"] == _result("alpha")
        assert calls == ["alpha"], "the second provider should not have been called"

    def test_a_failing_provider_falls_through_to_the_next(self, monkeypatch):
        calls = stub_providers(
            monkeypatch,
            ("alpha", RuntimeError("429 rate limited")),
            ("beta", _result("beta")),
        )
        outcome = web_search.search("anything")

        assert outcome["provider"] == "beta"
        assert outcome["results"] == _result("beta")
        assert calls == ["alpha", "beta"]
        assert any("429" in e for e in outcome["errors"])

    def test_an_empty_answer_is_an_answer_and_ends_the_chain(self, monkeypatch):
        """A provider returning nothing has genuinely answered.

        Falling through would turn "the web has nothing on this obscure
        seed-stage company" into one redundant lookup per configured provider,
        on every query, for the companies where that is the normal result.
        """
        calls = stub_providers(
            monkeypatch,
            ("alpha", []),
            ("beta", _result("beta")),
        )
        outcome = web_search.search("anything")

        assert outcome["provider"] == "alpha"
        assert outcome["results"] == []
        assert calls == ["alpha"]
        assert outcome["errors"] == []

    def test_all_providers_failing_is_reported_not_hidden(self, monkeypatch):
        stub_providers(
            monkeypatch,
            ("alpha", RuntimeError("boom")),
            ("beta", RuntimeError("bang")),
        )
        outcome = web_search.search("anything")

        assert outcome["provider"] == ""
        assert outcome["results"] == []
        assert len(outcome["errors"]) == 2

    def test_unconfigured_providers_are_skipped_without_being_called(self, monkeypatch):
        calls: list[str] = []

        def never(query, max_results):
            calls.append("keyed")
            return _result("keyed")

        monkeypatch.setattr(web_search, "PROVIDERS", [
            ("keyed", never, lambda: False),
            ("free", lambda q, n: _result("free"), lambda: True),
        ])
        outcome = web_search.search("anything")

        assert outcome["provider"] == "free"
        assert calls == []
        assert any(a["provider"] == "keyed" and a["outcome"] == "not configured"
                   for a in outcome["attempts"])


class TestCooldown:
    def test_a_failed_provider_is_not_retried_immediately(self, monkeypatch):
        """Without this, a rate-limited provider is retried on every query in an
        analysis, and each retry costs its own timeout -- turning a degraded
        search into a slow one as well."""
        calls = stub_providers(
            monkeypatch,
            ("alpha", RuntimeError("429")),
            ("beta", _result("beta")),
        )
        web_search.search("first")
        web_search.search("second")

        assert calls == ["alpha", "beta", "beta"], (
            "alpha should have been skipped on the second query"
        )

    def test_the_cooldown_is_visible_in_the_attempt_log(self, monkeypatch):
        stub_providers(
            monkeypatch,
            ("alpha", RuntimeError("429")),
            ("beta", _result("beta")),
        )
        web_search.search("first")
        outcome = web_search.search("second")

        alpha = next(a for a in outcome["attempts"] if a["provider"] == "alpha")
        assert "cooling down" in alpha["outcome"]

    def test_cooldown_expires(self, monkeypatch):
        calls = stub_providers(
            monkeypatch,
            ("alpha", RuntimeError("429")),
            ("beta", _result("beta")),
        )
        monkeypatch.setattr(web_search, "COOLDOWN_S", 0.0)
        web_search.search("first")
        web_search.search("second")

        assert calls.count("alpha") == 2


class TestSearchOrRaise:
    """Founder research must be able to tell "we searched and found nothing"
    from "the search never ran". Reporting the second as the first states a
    fact about the company that was never established."""

    def test_nothing_found_does_not_raise(self, monkeypatch):
        stub_providers(monkeypatch, ("alpha", []))
        outcome = web_search.search_or_raise("anything")

        assert outcome["results"] == []
        assert outcome["provider"] == "alpha"

    def test_everything_failing_raises(self, monkeypatch):
        stub_providers(
            monkeypatch,
            ("alpha", RuntimeError("boom")),
            ("beta", RuntimeError("bang")),
        )
        with pytest.raises(web_search.AllProvidersFailed):
            web_search.search_or_raise("anything")

    def test_one_provider_surviving_is_enough(self, monkeypatch):
        """The behaviour change this whole module exists for: DuckDuckGo being
        throttled is no longer a search failure."""
        stub_providers(
            monkeypatch,
            ("duckduckgo", RuntimeError("429 rate limited")),
            ("wikipedia", _result("wikipedia")),
        )
        outcome = web_search.search_or_raise("anything")

        assert outcome["provider"] == "wikipedia"
        assert outcome["results"]


class TestCallerContract:
    """`agents.claim_verifier.search_web` is called from five modules. Its
    signature and both of its behaviours have to survive the rewrite."""

    def test_search_web_still_returns_a_bare_list(self, monkeypatch):
        stub_providers(monkeypatch, ("alpha", _result("alpha")))
        from agents.claim_verifier import search_web

        results = search_web("anything")
        assert isinstance(results, list)
        assert results[0]["url"] == "https://example.test/alpha"

    def test_search_web_still_swallows_errors_by_default(self, monkeypatch):
        stub_providers(monkeypatch, ("alpha", RuntimeError("boom")))
        from agents.claim_verifier import search_web

        assert search_web("anything") == []

    def test_search_web_still_raises_when_asked(self, monkeypatch):
        stub_providers(monkeypatch, ("alpha", RuntimeError("boom")))
        from agents.claim_verifier import search_web

        with pytest.raises(Exception):
            search_web("anything", raise_on_error=True)


class TestProviderShapes:
    """Each adapter must return the {title, url, snippet} shape the rest of the
    product consumes, whatever its upstream JSON looks like."""

    def test_wikipedia_strips_the_search_match_markup(self, monkeypatch):
        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"query": {"search": [
                    {"title": "Melanie Perkins",
                     "snippet": '<span class="searchmatch">Melanie</span> '
                                'Perkins is an Australian entrepreneur'},
                ]}}

        monkeypatch.setattr(web_search.requests, "get",
                            lambda *a, **k: FakeResponse())
        results = web_search._wikipedia("Canva founders", 5)

        assert results[0]["title"] == "Melanie Perkins"
        assert results[0]["url"] == "https://en.wikipedia.org/wiki/Melanie_Perkins"
        # Left in, the markup reaches the LLM prompt and the evidence filter as
        # literal angle brackets.
        assert "<span" not in results[0]["snippet"]
        assert results[0]["snippet"].startswith("Melanie Perkins is an Australian")


def test_the_default_chain_works_without_any_api_key(monkeypatch):
    """The property that makes this useful on a fresh clone: two of the four
    providers need no configuration at all."""
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    assert web_search.available_providers() == ["duckduckgo", "wikipedia"]


@pytest.mark.skipif(
    os.getenv("VENTUREFLOW_LIVE_SEARCH_TEST", "").lower() not in {"1", "true", "yes"},
    reason="live network test; set VENTUREFLOW_LIVE_SEARCH_TEST=1 to run",
)
def test_wikipedia_really_answers_a_founder_question():
    """Opt-in, because it reaches the open web. This is the one thing the stubs
    above cannot establish: that the fallback provider is actually any good at
    the question this product asks it."""
    results = web_search._wikipedia("Canva founders Melanie Perkins", 5)

    assert results, "Wikipedia returned nothing"
    titles = " ".join(r["title"] for r in results)
    assert "Melanie Perkins" in titles or "Canva" in titles
