"""Tests for the deterministic financial reader.

Every case below is either a real excerpt from ml/eval/risk_benchmark.jsonl or a
minimal reproduction of a bug this module actually shipped during development.
The arithmetic ones matter most: a diligence tool that reports the wrong runway
is worse than one that reports no runway, because a wrong number is acted on.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import deck_financials as df

CONCENTRATION = (
    "Traction. We closed $2.4M in ARR this year, up from $310K. Our anchor "
    "customer, a national logistics operator, represents $1.9M of that figure "
    "and their master services agreement comes up for renewal in four months."
)
RUNWAY = (
    "Financials. Monthly burn is currently $410K against $38K in monthly "
    "recognised revenue. Cash on hand at the end of last month was $1.1M. "
    "We are raising a $6M Series A to extend runway."
)
DEPARTURE = (
    "Team. Our founding CTO left the company in March to return to academia. "
    "He wrote the original matching algorithm during his postdoc and the "
    "assignment agreement covering that work is still being negotiated."
)
CLEAN_MARKET_SLIDE = (
    "Market. Third-party analysts size the warehouse execution software market "
    "at $4.1B today, growing to $9.8B by 2030. We define our serviceable market "
    "as mid-market third-party logistics operators."
)


@pytest.mark.parametrize("text,expected", [
    ("$2.4M", 2_400_000),
    ("$310K", 310_000),
    ("$1,200,000", 1_200_000),
    ("USD 4.1B", 4_100_000_000),
    ("£250k", 250_000),
    ("1.9 million", 1_900_000),
])
def test_money_parsing_handles_the_forms_decks_use(text, expected):
    assert df.parse_money(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["62 customers", "by 2030", "nine accounts", ""])
def test_bare_integers_are_not_money(text):
    """A market slide is full of years and counts. Reading "2030" as $2,030
    would put a phantom figure into every derived ratio."""
    assert df.parse_money(text) is None


def test_a_scaled_number_inside_a_currency_amount_is_not_a_separate_figure():
    """Regression: the bare-scaled pattern matched the "4M" INSIDE "$2.4M",
    creating a phantom $4,000,000 three characters from the real $2,400,000.
    Being nearer to the "ARR" anchor, the phantom won and was reported as the
    company's revenue -- a 67% overstatement that propagated into every ratio."""
    positions = df._money_positions("We closed $2.4M in ARR this year, up from $310K.")
    assert [value for _, value in positions] == [2_400_000.0, 310_000.0]


def test_arr_is_read_from_the_amount_before_its_label():
    """"$2.4M in ARR" puts the figure before the anchor; a forward-only scan
    reads $310K from "up from $310K" instead."""
    state = df.derive_state(CONCENTRATION)
    assert state.arr == pytest.approx(2_400_000)
    assert state.growth_multiple == pytest.approx(7.74, abs=0.01)


def test_cash_is_not_read_from_the_previous_sentence():
    """Regression, and the most dangerous single bug this module had: a
    backward window read `cash_on_hand` as $38K from the preceding clause
    instead of $1.1M, reporting 0.1 months of runway rather than 2.7 -- wrong by
    a factor of thirty in the most decisive figure on the page."""
    state = df.derive_state(RUNWAY)
    assert state.cash_on_hand == pytest.approx(1_100_000)
    assert state.monthly_burn == pytest.approx(410_000)
    assert state.runway_months == pytest.approx(2.7, abs=0.05)
    assert state.runway_source.startswith("computed")


def test_monthly_revenue_is_not_recorded_as_annual_revenue():
    """"revenue" is a substring of "monthly recognised revenue". Letting the
    annual field take a monthly value threw the burn multiple out by 12x --
    129x reported where the truth was 10.8x."""
    state = df.derive_state(RUNWAY)
    assert state.mrr == pytest.approx(38_000)
    assert state.annual_revenue == pytest.approx(456_000)
    assert state.burn_multiple == pytest.approx(10.79, abs=0.05)


def test_customer_concentration_is_a_share_not_the_total():
    """A window wide enough to reach "We closed $2.4M in ARR" read the TOTAL as
    the share and reported 100% concentration -- an impossible number standing
    in for a serious but real 79%."""
    state = df.derive_state(CONCENTRATION)
    assert state.largest_customer_share == pytest.approx(0.792, abs=0.01)


def test_the_three_deck_red_flags_the_keyword_detector_misses_are_all_caught():
    """The reason this module exists. `agents.risk_detector.RISK_SIGNALS` is SEC
    vocabulary and matches none of these, because a founder states the risk as
    arithmetic rather than as a term of art."""
    concentration = {s["signal"] for s in df.deck_risk_signals(CONCENTRATION)}
    runway = {s["signal"] for s in df.deck_risk_signals(RUNWAY)}
    departure = {s["signal"] for s in df.deck_risk_signals(DEPARTURE)}

    assert any("largest customer" in s for s in concentration)
    assert any("runway" in s for s in runway)
    assert any("departure" in s for s in departure)
    assert any("intellectual-property" in s for s in departure)


def test_a_clean_market_slide_produces_no_signals():
    """The headline metric for a risk detector is its false-positive rate on
    boilerplate, not its recall. A detector that flags everything is useless on
    documents that are mostly hedged prose."""
    assert df.deck_risk_signals(CLEAN_MARKET_SLIDE) == []
    state = df.derive_state(CLEAN_MARKET_SLIDE)
    # A market-size slide must not be read as company revenue.
    assert state.arr is None
    assert state.revenue is None


def test_nothing_is_inferred_from_an_empty_deck():
    state = df.derive_state("")
    assert state.runway_months is None
    assert state.annual_revenue is None
    assert df.deck_risk_signals("") == []


def test_a_stated_runway_is_preferred_over_a_computed_one_and_says_so():
    state = df.derive_state("We have 14 months of runway. Monthly burn is $100K.")
    assert state.runway_months == pytest.approx(14)
    assert state.runway_source == "stated in deck"


def test_analyse_returns_metrics_state_and_signals_together():
    out = df.analyse(RUNWAY)
    assert set(out) == {"metrics", "state", "signals"}
    assert out["state"]["runway_months"] == pytest.approx(2.7, abs=0.05)
    # Every figure carries the sentence it came from, so a wrong number can be
    # traced to its source rather than argued about.
    assert out["state"]["evidence"]["monthly_burn"]
