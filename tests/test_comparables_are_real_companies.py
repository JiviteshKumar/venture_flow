"""A comparable must be a company, not a filename or a test fixture.

WHAT THE USER SAW

A real end-to-end analysis of Uber's 2008 deck returned exactly one similar
company:

    comparables: ['02 uber']

`db.find_similar_companies` selects from any row in `companies` that has a
report or an investment attached, and `companies` is written by every analysis
this deployment has ever run. Two kinds of junk had accumulated there:

  * names taken from an upload filename, from before the name was cleaned at
    the API boundary -- "02 uber", "05 dropbox", "claritycare health pitch
    deck". "02 uber" then matched back to "Uber" by trigram similarity on its
    own filename, which is how a company became its own comparable.
  * fixture companies left behind by tests/test_auth.py -- 33 of the 81 rows
    in the table were `ScopeTest <hex>`, `ListScope <hex>` or `Legacy <hex>`.

Both are fixed at the source (the name is cleaned before it is stored; the
tests now delete what they create). This is the read-side guard, because the
rows already exist and a comparables list is read far more often than written.

THE EXPENSIVE DIRECTION

Most of the tests below are about names that must SURVIVE. A filter that
withholds a real company costs the reader a row of context; that is a real but
small cost, and it is the one this is tuned to avoid over-paying. "7-Eleven",
"500 Startups", "3M" and "23andMe" all look filename-shaped by any naive rule.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402


class TestJunkIsWithheld:
    @pytest.mark.parametrize("name", [
        "02 uber",          # the reported case
        "05 dropbox",
        "03 linkedin",
        "28 canva",
    ])
    def test_a_filename_derived_name_is_not_a_comparable(self, name):
        assert db._is_a_real_company_name(name) is False

    @pytest.mark.parametrize("name", [
        "claritycare health pitch deck",
        "ledgerloop ai pitch deck",
        "novaedge sample pitch deck",
        "ComplyForge AI Pitch Deck",
        "PawPulse Pitch Deck",
    ])
    def test_a_packaging_suffix_is_not_a_company(self, name):
        """No company is called "... Pitch Deck". These lost their extension
        somewhere and kept the rest of the filename."""
        assert db._is_a_real_company_name(name) is False

    @pytest.mark.parametrize("name", [
        "ScopeTest 793de54f", "ListScope fa105c5c", "Legacy 667fb66f",
    ])
    def test_a_test_fixture_is_not_a_comparable(self, name):
        assert db._is_a_real_company_name(name) is False

    @pytest.mark.parametrize("name", ["", "   ", None])
    def test_an_empty_name_is_not_a_company(self, name):
        assert db._is_a_real_company_name(name) is False


class TestRealCompaniesSurvive:
    @pytest.mark.parametrize("name", [
        "Uber", "Airbnb", "Stripe",
        "500 Startups",       # leading number
        "7-Eleven",           # leading digit AND a hyphen
        "3M", "23andMe", "1Password",
        "Carbon Ledger", "Deck Technologies", "Final Frontier",
    ])
    def test_a_real_name_is_offered(self, name):
        assert db._is_a_real_company_name(name) is True, (
            f"{name!r} is a real company and was withheld from comparables"
        )

    def test_it_does_not_reuse_the_looser_ui_predicate(self):
        """`company_name.looks_like_a_filename` answers a different question --
        "should the UI suggest checking this name" -- and returns True for
        "7-Eleven". Correct as a prompt, wrong as grounds for withholding."""
        from company_name import looks_like_a_filename

        assert looks_like_a_filename("7-Eleven") is True
        assert db._is_a_real_company_name("7-Eleven") is True


class TestTheFilterIsAppliedToResults:
    def test_find_similar_companies_drops_junk_rows(self, monkeypatch):
        """The filter has to run on the query's output, not merely exist."""
        rows = [
            {"id": 1, "name": "02 uber", "domain": None, "sector": None,
             "similarity": 0.9},
            {"id": 2, "name": "Lyft", "domain": None, "sector": None,
             "similarity": 0.6},
            {"id": 3, "name": "ScopeTest abc12345", "domain": None,
             "sector": None, "similarity": 0.5},
        ]

        class FakeCursor:
            def execute(self, *a, **k): pass
            def fetchall(self): return rows
            def __enter__(self): return self
            def __exit__(self, *a): return False

        class FakeConn:
            def cursor(self): return FakeCursor()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        monkeypatch.setattr(db, "connection", lambda: FakeConn())

        out = db.find_similar_companies("Uber", None, None)
        assert [row["name"] for row in out] == ["Lyft"]
