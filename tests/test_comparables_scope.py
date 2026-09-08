"""The comparables feature must state its own population, and cover more than
one accelerator.

HISTORY, BECAUSE IT CHANGES WHAT THESE TESTS ASSERT

An earlier version of this file recorded that a broader-than-YC population "is
NOT obtainable today", on the grounds that Crunchbase's API returns 401 without
a paid licence, its free Open Data Map is no longer published, and the startup
datasets on public model hubs are unattributed scrapes with no verifiable
provenance. All three of those facts still hold.

The conclusion drawn from them did not. A market-wide corpus WAS obtainable, from
public reference data: Wikidata for company structure and outcomes, English
Wikipedia for description text, both free, both CC-licensed, and every row
carrying a Q-identifier a reader can open and check. It is small -- 470 companies
against YC's 5,133 -- and it under-represents startups that failed quietly. It is
also real, and it is not Y Combinator.

So the tests below no longer assert the YC-only caveat. They assert the two
things that replaced it: that both populations are described as structured data,
and that a non-YC company is actually shown when one exists rather than being
crowded out.
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


def _require_market_corpus():
    """Skip, with instructions, when the market corpus has not been built.

    `ml/data/*` is gitignored, with individual data files force-added. If
    `market_dataset.jsonl` is not committed alongside `outcome_dataset.jsonl`,
    a fresh clone has no second population and every assertion about it fails --
    which would read as a code regression rather than as a missing data file.
    """
    if not comparables.MARKET_PATH.exists():
        pytest.skip(
            f"{comparables.MARKET_PATH.name} is not present. Build it with: "
            f"python ml/scripts/build_market_company_dataset.py "
            f"--out ml/data/market_dataset.jsonl"
        )


def test_comparables_are_returned_at_all(result):
    if not result.get("available"):
        pytest.skip(f"comparables unavailable: {result.get('reason')}")
    assert result["comparables"]


def test_both_populations_are_described_as_structured_data_not_only_prose(result):
    """The UI renders the scope above the table from these fields. Leaving it in
    a prose caveat means it renders as an 11px grey footnote under a table a
    reader has already read as "this company's competitors"."""
    _require_market_corpus()
    if not result.get("available"):
        pytest.skip("comparables unavailable")
    population = result["population"]

    assert set(population) >= {"yc", "market"}
    for key in ("yc", "market"):
        entry = population[key]
        assert entry["n"] > 0, f"{key} corpus is empty"
        assert entry["label"]
        assert entry["source"]
        assert entry["url"].startswith("https://")
        assert entry["note"], f"{key} must say what it does and does not cover"
    # 5,133, not 1,560: the YC half is now a display corpus that includes
    # companies still operating (70% of the population), which the training
    # dataset it used to read excluded by construction.
    assert population["yc"]["n"] > 5000


def test_every_row_says_which_population_it_came_from(result):
    """Two populations in one table is only honest if each row is labelled. A
    YC alum and an encyclopedia-notable public company are different kinds of
    evidence and must not be presented as one list of peers."""
    if not result.get("available"):
        pytest.skip("comparables unavailable")
    for row in result["comparables"]:
        assert row["population"] in {"yc", "market"}
        assert row["population_label"]


def test_a_non_yc_company_is_actually_shown_when_one_exists(result):
    """The point of the whole change, and the reason results are stratified
    rather than pooled.

    Pooling was measured first: across five probe queries the merged top five
    came back 24 of 25 rows from Y Combinator, because the embedder is fitted on
    YC's own writing and scores its register above encyclopedia prose. That
    would have added a second population to the data and left the output as
    YC-only as before, while the caveat claimed otherwise.
    """
    _require_market_corpus()
    if not result.get("available"):
        pytest.skip("comparables unavailable")
    if result["population"]["market"]["matches_above_floor"] == 0:
        pytest.skip("no market-wide company clears the floor for this query")

    sources = {row["population"] for row in result["comparables"]}
    assert "market" in sources, (
        "a market-wide company cleared the similarity floor but was crowded out "
        "of the results by YC rows"
    )


def test_market_rows_carry_a_link_a_reader_can_check(result):
    """The market corpus's whole claim to trustworthiness is that every row is
    verifiable. A row without its source URL cannot be checked."""
    _require_market_corpus()
    if not result.get("available"):
        pytest.skip("comparables unavailable")
    market_rows = [r for r in result["comparables"] if r["population"] == "market"]
    if not market_rows:
        pytest.skip("no market rows in this result")
    for row in market_rows:
        assert row["source_url"].startswith("https://www.wikidata.org/wiki/Q")


def test_the_caveat_leads_with_the_population_and_names_both(result):
    """Not buried at the end. A reader has to know what was searched before they
    read a similarity number."""
    _require_market_corpus()
    if not result.get("available"):
        pytest.skip("comparables unavailable")
    caveat = result["caveat"]
    assert caveat.upper().startswith("TWO POPULATIONS")
    assert "Y Combinator" in caveat
    assert "did not go through an accelerator" in caveat


def test_the_caveat_forbids_comparing_the_two_similarity_columns(result):
    """The scores are not on one scale: the embedder was fitted on YC text, so
    it systematically scores YC rows higher for reasons of writing style. A
    reader who ranks the whole table by the number is being misled."""
    _require_market_corpus()
    if not result.get("available"):
        pytest.skip("comparables unavailable")
    assert "DO NOT COMPARE THE TWO SIMILARITY COLUMNS" in result["caveat"]


def test_the_caveat_still_says_what_is_missing(result):
    """The market corpus is drawn from an encyclopedia, so it over-represents
    companies whose failure was notable. Replacing one population caveat with
    silence would be a step backwards."""
    _require_market_corpus()
    if not result.get("available"):
        pytest.skip("comparables unavailable")
    caveat = result["caveat"]
    assert "notable enough for an encyclopedia entry" in caveat
    assert "Neither population is a market census" in caveat


def test_an_empty_description_degrades_without_claiming_no_comparables_exist():
    """Failure-mode test: an empty population or empty query must not render as
    "no comparable companies were found", which is a statement about the
    company rather than about the input."""
    out = comparables.find_comparables("")
    assert out["available"] is False
    assert out.get("reason")


def test_a_nonsense_description_returns_nothing_rather_than_filling_the_table():
    """The tab used to return exactly five rows for every query however distant,
    which presents "the nearest things in the corpus" as though it meant "these
    are comparable companies"."""
    out = comparables.find_comparables("zzzz qqqq xxxx vvvv")
    if not out.get("available"):
        pytest.skip("comparables unavailable")
    assert out["comparables"] == []
    assert out["no_close_matches"] is True
    assert "No close comparables found" in out["caveat"]
    assert out["best_similarity"] < out["threshold"]


def test_a_real_description_still_returns_comparables():
    """The floor must not suppress genuine matches."""
    out = comparables.find_comparables(
        "An AI developer tools platform that automates code review for "
        "enterprise engineering teams."
    )
    if not out.get("available"):
        pytest.skip("comparables unavailable")
    assert out["comparables"], "the floor suppressed a genuine match"
    assert out.get("no_close_matches") is False


def test_the_caveat_states_that_similarity_is_lexical_not_semantic():
    """Measured counter-example, disclosed because the number invites the
    opposite reading."""
    out = comparables.find_comparables(
        "An AI developer tools platform for enterprise engineering teams."
    )
    if not out.get("available"):
        pytest.skip("comparables unavailable")
    assert "LEXICAL, NOT SEMANTIC" in out["caveat"]
    assert "commercial laundry" in out["caveat"]


def test_a_query_with_no_market_analogue_still_returns_a_full_set():
    """Reserving places for the market population must not shrink the result
    when that population has nothing to offer. A user asking about a bitcoin
    wallet should not get three rows because Wikidata is thin on them."""
    out = comparables.find_comparables(
        "A hosted bitcoin wallet for instant international payments with no "
        "transaction fees."
    )
    if not out.get("available") or out.get("no_close_matches"):
        pytest.skip("comparables unavailable or no matches")
    assert len(out["comparables"]) >= 5
