"""The comparables feature must state its own population.

Part of this session's honesty pass. A broader-than-YC population was
investigated and is NOT obtainable today: Crunchbase's API returns 401 without a
paid licence, its free Open Data Map is no longer published, and the startup
datasets on public model hubs are unattributed third-party scrapes with no
verifiable provenance.

What IS verifiable: yc-oss publishes 6,194 YC companies, of which 1,903 have a
determinable outcome (Acquired/Public/Inactive) and 4,291 are still Active and
therefore have no outcome to compare against. The corpus uses 1,560 -- 82% of
the addressable pool. So there is no meaningful expansion available inside YC
either, and the honest response is to scope the feature correctly rather than
overclaim it.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import comparables

DESCRIPTION = "An AI-powered developer tools platform for enterprise engineering teams"


@pytest.fixture(scope="module")
def result():
    return comparables.find_comparables(DESCRIPTION)


def test_comparables_are_returned_at_all(result):
    if not result.get("available"):
        pytest.skip(f"comparables unavailable: {result.get('reason')}")
    assert result["comparables"]


def test_the_population_is_stated_as_structured_data_not_only_prose(result):
    """The UI renders the scope above the table from these fields. Leaving it in
    a prose caveat means it renders as an 11px grey footnote under a table a
    reader has already interpreted as "this company's competitors"."""
    if not result.get("available"):
        pytest.skip("comparables unavailable")
    population = result["population"]
    assert population["n"] == 1560
    assert population["labelled_available"] == 1903
    assert 0 < population["coverage_of_labelled"] <= 1
    assert "Y Combinator" in population["name"]


def test_the_caveat_leads_with_the_population_limit(result):
    """Not buried at the end. The previous caveat closed with "Also YC-only,
    same population caveat as the Outcome Model" -- true, and last."""
    if not result.get("available"):
        pytest.skip("comparables unavailable")
    caveat = result["caveat"]
    assert caveat.upper().startswith("YC-ONLY POPULATION")
    assert "not the nearest companies in the market" in caveat


def test_the_population_says_what_is_NOT_included(result):
    """A reader asking "why these five companies" needs to know what could never
    have appeared."""
    if not result.get("available"):
        pytest.skip("comparables unavailable")
    not_included = result["population"]["not_included"]
    assert "Non-YC" in not_included


def test_why_not_broader_is_recorded_as_a_budget_item_not_a_todo(result):
    """The blocker is a paid licence, not missing engineering, and saying so
    stops a future session re-investigating it from scratch."""
    if not result.get("available"):
        pytest.skip("comparables unavailable")
    assert "401" in result["population"]["why_not_broader"]


def test_an_empty_description_degrades_without_claiming_no_comparables_exist():
    """Failure-mode test: an empty population or empty query must not render as
    "no comparable companies were found", which is a statement about the
    company rather than about the input."""
    out = comparables.find_comparables("")
    assert out["available"] is False
    assert out.get("reason")


def test_a_nonsense_description_still_returns_matches_which_is_the_point_of_the_caveat():
    """This is the behaviour the caveat exists to disclose: the search always
    returns its nearest available matches however distant they are, so five rows
    appearing is not evidence that five relevant comparables exist."""
    out = comparables.find_comparables("zzzz qqqq xxxx vvvv")
    if not out.get("available"):
        pytest.skip("comparables unavailable")
    assert out["comparables"], "nearest-match search returns rows regardless"
    assert "however distant" in out["caveat"]
