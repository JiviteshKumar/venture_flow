"""The company name is the subject of every web lookup this product makes.

A file called `02 uber.pdf` became the company name "02 uber", and founder
research then searched for the founders of "02 uber" -- consulting, among
fourteen sources, the Wikipedia articles for Delta Air Lines and Maximilien
Robespierre before reporting that no founder could be established. Claim
verification, the comparables search and the report title were all scoped to
the same non-existent company.

The tests below are split by which way the cleaner can be wrong. Both matter,
and the second matters more: a cleaner that mangles a real name is worse than
no cleaner, because the user has no way to know it happened.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import company_name  # noqa: E402


class TestFilenamesBecomeCompanies:
    @pytest.mark.parametrize("raw,expected", [
        # The reported case, and its neighbour from the same upload batch.
        ("02 uber.pdf", "Uber"),
        ("05 dropbox.pdf", "Dropbox"),
        # Ordinals in the other shapes files actually arrive in.
        ("1. airbnb.pdf", "Airbnb"),
        ("3-intercom.pptx", "Intercom"),
        ("007_coinbase.pdf", "Coinbase"),
        # Packaging words at either end.
        ("uber-pitch-deck.pdf", "Uber"),
        ("Airbnb Pitch Deck 2009.pdf", "Airbnb"),
        ("final-buffer-deck-v2.pdf", "Buffer"),
        ("investor deck mint.pdf", "Mint"),
        ("canva presentation final.pptx", "Canva"),
        # Separators.
        ("front_series_a.pdf", "Front"),
        ("carbon-cycle.pdf", "Carbon Cycle"),
    ])
    def test_a_filename_becomes_something_searchable(self, raw, expected):
        assert company_name.clean(raw) == expected


class TestRealNamesSurvive:
    """The expensive direction. Every one of these is a company whose real name
    contains something the cleaner is tempted to remove."""

    @pytest.mark.parametrize("raw", [
        "500 Startups",     # leading number, plain space, no leading zero
        "1Password",        # leading digit, no separator at all
        "23andMe",
        "3M",
        "7-Eleven",         # a hyphen that is part of the name
        "Series",           # a company that IS a packaging word
        "Deck",
        "Version One",      # packaging word as a real first word
        "Final Frontier",
    ])
    def test_a_real_name_is_not_mangled(self, raw):
        assert company_name.clean(raw) == raw

    def test_existing_capitalisation_is_never_second_guessed(self):
        """Any scheme clever enough to re-case these is clever enough to ruin
        them."""
        for name in ("iRobot", "eBay", "OpenAI", "YCombinator", "deepMind"):
            assert company_name.clean(name) == name

    def test_a_multi_word_name_keeps_its_interior_words(self):
        assert company_name.clean("Deck Technologies") == "Deck Technologies"
        assert company_name.clean("Series Ventures") == "Series Ventures"


class TestItNeverReturnsNothing:
    """A recognisable wrong name beats an empty one: the user sees this in an
    editable field and can correct it. An empty field tells them nothing."""

    @pytest.mark.parametrize("raw", ["deck.pdf", "pitch deck.pdf", "final.pdf", "2008.pdf"])
    def test_an_all_packaging_filename_keeps_something(self, raw):
        assert company_name.clean(raw).strip() != ""

    def test_empty_input_is_empty_output(self):
        assert company_name.clean("") == ""
        assert company_name.clean("   ") == ""

    def test_it_never_raises(self):
        for weird in ("...", "___", "42", "%%%", "a" * 500, "🙂.pdf"):
            company_name.clean(weird)


class TestFilenameDetection:
    def test_it_recognises_a_filename(self):
        assert company_name.looks_like_a_filename("02 uber.pdf") is True
        assert company_name.looks_like_a_filename("deck.pptx") is True
        assert company_name.looks_like_a_filename("1. airbnb") is True

    def test_it_does_not_flag_a_real_name(self):
        for name in ("Uber", "500 Startups", "Carbon Cycle", "3M"):
            assert company_name.looks_like_a_filename(name) is False


class TestTheApiAppliesIt:
    """Cleaning only in the upload form would not be enough: the name is
    editable before submission and /analyze is reachable directly, so a
    filename can arrive at the pipeline by either route."""

    def test_analyze_cleans_the_company_name_before_using_it(self, monkeypatch):
        from fastapi.testclient import TestClient

        import api

        captured: dict = {}

        def capture(payload):
            captured.update(payload)
            return "job-1"

        monkeypatch.setattr(api, "create_analysis_job", capture)
        monkeypatch.setattr(api, "count_active_jobs", lambda: 0)
        # Keep the scope gate out of the way; it is tested elsewhere.
        monkeypatch.setattr(api.tech_scope, "classify", lambda *a, **k: {
            "in_scope": True, "confidence": 0.9, "sector": "tech",
            "reason": "ok", "method": "signals",
            "software_signals": [], "non_tech_signals": [], "scope_statement": "",
        })

        client = TestClient(api.app)
        response = client.post("/analyze", json={
            "company_name": "02 uber.pdf",
            "company_description": "A mobile app for booking cars, with an API.",
        })

        assert response.status_code == 202, response.text
        assert captured["company_name"] == "Uber", (
            "the filename reached the pipeline as the company name; every web "
            "lookup would be scoped to a company that does not exist"
        )

    def test_a_real_company_name_passes_through_untouched(self, monkeypatch):
        from fastapi.testclient import TestClient

        import api

        captured: dict = {}
        monkeypatch.setattr(api, "create_analysis_job",
                            lambda payload: (captured.update(payload), "job-1")[1])
        monkeypatch.setattr(api, "count_active_jobs", lambda: 0)
        monkeypatch.setattr(api.tech_scope, "classify", lambda *a, **k: {
            "in_scope": True, "confidence": 0.9, "sector": "tech",
            "reason": "ok", "method": "signals",
            "software_signals": [], "non_tech_signals": [], "scope_statement": "",
        })

        client = TestClient(api.app)
        client.post("/analyze", json={
            "company_name": "500 Startups",
            "company_description": "An accelerator running a software platform.",
        })

        assert captured["company_name"] == "500 Startups"
