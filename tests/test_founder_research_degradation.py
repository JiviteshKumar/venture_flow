"""Founder research must not report our outage as a fact about the company.

WHAT HAPPENED

Asked for Uber's founders with the Groq daily quota exhausted, the product
said:

    Searched 14 public source(s) for the founders of 02 uber. No founder name
    could be established from them.

Two separate defects in one sentence.

The company name was "02 uber", taken from the filename `02 uber.pdf` -- see
tests/test_company_name.py. And the retrieved sources INCLUDED Garrett Camp's
own Wikipedia page; what failed was our call to the language model that reads
the evidence. Both of that model's failure paths returned `[]`, which is
exactly what "read the evidence and found nobody" returns, so the caller could
not tell them apart and reported the outage as an absence of evidence.

The module already distinguished three states -- not attempted, search failed,
searched-and-found-nothing. This adds the fourth it was missing: searched
successfully, evidence retrieved, and the step that reads it did not run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agents.founder_research as fr  # noqa: E402


@pytest.fixture
def enabled(monkeypatch):
    """The suite disables founder research globally (see conftest). These tests
    are about its behaviour, so they turn it back on for their own duration."""
    monkeypatch.setattr(fr, "RESEARCH_ENABLED", True)


@pytest.fixture
def evidence(monkeypatch):
    """Real-shaped evidence that DOES name the founders, so a "found nothing"
    result can only come from the reading step rather than from the search."""
    monkeypatch.setattr(fr, "search_web", lambda *a, **k: [
        {"title": "Garrett Camp - Wikipedia",
         "url": "https://en.wikipedia.org/wiki/Garrett_Camp",
         "snippet": "Garrett Camp co-founded Uber with Travis Kalanick in 2009."},
        {"title": "Travis Kalanick - Wikipedia",
         "url": "https://en.wikipedia.org/wiki/Travis_Kalanick",
         "snippet": "Travis Kalanick is a co-founder of Uber."},
    ])
    monkeypatch.setattr(fr, "fetch_page_text", lambda *a, **k: (
        "Uber was founded in 2009 by Garrett Camp and Travis Kalanick."
    ))


class TestProviderFailureIsNotAFindingAboutTheCompany:
    def test_a_quota_failure_is_reported_as_a_deployment_problem(
        self, enabled, evidence, monkeypatch
    ):
        def exhausted(*_a, **_k):
            raise fr.ProposalUnavailable("the daily Groq token quota is exhausted")

        monkeypatch.setattr(fr, "_propose_names", exhausted)
        out = fr.discover_founders("Uber", stage="Seed")

        assert out["found"] is False
        assert out["degraded"] is True, (
            "a provider outage was indistinguishable from an absent founder"
        )
        reason = out["reason"].lower()
        assert "could not be completed" in reason
        assert "not about the company" in reason
        # The sentence that was actually wrong must not reappear.
        assert "no founder name could be established" not in reason

    def test_the_retrieved_sources_are_still_reported(
        self, enabled, evidence, monkeypatch
    ):
        """The search worked. Saying how many sources were retrieved but unread
        is what makes the failure legible and the re-run obviously worth it."""
        monkeypatch.setattr(fr, "_propose_names", lambda *a, **k: (_ for _ in ()).throw(
            fr.ProposalUnavailable("the language model could not be reached")
        ))
        out = fr.discover_founders("Uber", stage="Seed")

        assert out["sources_consulted"], "sources were dropped on the failure path"
        assert out["searched"] is True

    def test_genuinely_finding_nobody_is_not_marked_degraded(
        self, enabled, evidence, monkeypatch
    ):
        """The other half of the contract. A model that ran and found nothing is
        a real (if weak) finding, and must not be dressed up as an outage."""
        monkeypatch.setattr(fr, "_propose_names", lambda *a, **k: [])
        out = fr.discover_founders("Uber", stage="Seed")

        assert out["found"] is False
        assert not out.get("degraded")
        assert "no founder name could be established" in out["reason"].lower()

    def test_a_successful_run_still_returns_founders(
        self, enabled, evidence, monkeypatch
    ):
        """The fix must not break the working path. Both names appear verbatim
        in the stubbed evidence, so the grounding check should accept them."""
        monkeypatch.setattr(
            fr, "_propose_names",
            lambda *a, **k: ["Garrett Camp", "Travis Kalanick"],
        )
        out = fr.discover_founders("Uber", stage="Seed")

        assert out["found"] is True, out.get("reason")
        names = {f["name"] for f in out["founders"]}
        assert "Garrett Camp" in names
        assert not out.get("degraded")


class TestTheProposalStepSignalsFailure:
    """`_propose_names` returned [] on both failure paths, which is the same
    value it returns when the evidence genuinely names nobody."""

    def test_an_unparseable_reply_raises(self, monkeypatch):
        class Boom:
            def __getattr__(self, _name):
                raise AssertionError("should not reach the client")

        monkeypatch.setattr(fr, "pace_for", lambda *a, **k: 0.0)
        monkeypatch.setattr(fr, "get_client", lambda: (_ for _ in ()).throw(
            RuntimeError("connection refused")
        ))
        with pytest.raises(fr.ProposalUnavailable):
            fr._propose_names("Uber", "some evidence")

    def test_a_quota_error_is_named_in_the_message(self, monkeypatch):
        monkeypatch.setattr(fr, "pace_for", lambda *a, **k: 0.0)
        monkeypatch.setattr(fr, "get_client", lambda: (_ for _ in ()).throw(
            RuntimeError("429 rate_limit_exceeded tokens per day (TPD): Limit 200000")
        ))
        with pytest.raises(fr.ProposalUnavailable) as excinfo:
            fr._propose_names("Uber", "some evidence")
        assert "quota" in str(excinfo.value).lower()
