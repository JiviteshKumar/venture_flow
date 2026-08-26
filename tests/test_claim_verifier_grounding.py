"""Guards for the two errors that real pitch decks exposed in claim verification.

Both were found by running seven genuine decks (Airbnb 2009, Uber 2008, Buffer
2011, Intercom 2011, Coinbase 2012, Mint 2007, Front 2016) end to end and
reading every decisive verdict, which is something no benchmark run had done.
`ml/eval/claim_benchmark.jsonl` reports REFUTES precision of 1.000; on real decks
it was 0.000. The benchmark could not see either failure because it contains only
claims about present-day facts and no claims sourced from the document under
test.

These tests are structural. They assert that the prompt actually carries the
rules and the date, rather than asserting what a model replies -- a model's
answer is not reproducible in CI, and the failure being guarded against is a
prompt regression: someone tidying the rules block and removing the part that
stops the tool calling growth a lie.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agents.claim_verifier as cv
from agents import evidence_filter as ef

EVIDENCE = {
    "snippets": [{"title": "t", "url": "https://example.com/a", "snippet": "s"}],
    "full_texts": [],
}


def _capture_prompt(monkeypatch):
    seen = {}

    def fake_create(**kwargs):
        seen["prompt"] = kwargs["messages"][-1]["content"]
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='{"verdict":"NOT_ENOUGH_INFO","confidence":0.5,'
                                            '"reasoning":"r","key_evidence":"e"}'))])

    monkeypatch.setattr(cv, "get_client", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))))
    return seen


def test_the_judge_is_told_a_present_day_figure_does_not_refute_a_past_one(monkeypatch):
    """The rule that fixes all four wrong REFUTES verdicts.

    Airbnb's "630,000 users on couchsurfing.com" (2008) was refuted at 0.97
    confidence using Wikipedia's present-day 12,000,000. Buffer's "800 Paying
    Users" (2011) was refuted because Buffer now has 70,000+. Coinbase's "$2M
    per day" (2012) was refuted against today's ~$751M per day. Each claim was
    TRUE when written, and the tool penalised precisely the companies whose
    numbers had grown most.
    """
    seen = _capture_prompt(monkeypatch)
    cv.groq_judge("800 Paying Users", EVIDENCE, as_of="2011")
    prompt = seen["prompt"]

    assert "2011" in prompt, "the deck's vintage must reach the judge"
    lowered = prompt.lower()
    assert "different period" in lowered
    assert "not_enough_info" in lowered
    assert "grew" in lowered or "growth" in lowered, (
        "the prompt must state that a larger present-day figure is evidence of "
        "growth rather than of falsehood"
    )


def test_an_unknown_deck_date_still_biases_away_from_refutes(monkeypatch):
    """Vintage is often unavailable. The guard must degrade toward caution, not
    switch off -- an absent date must not restore the old behaviour."""
    seen = _capture_prompt(monkeypatch)
    cv.groq_judge("800 Paying Users", EVIDENCE, as_of="")
    lowered = seen["prompt"].lower()
    assert "date of this claim is unknown" in lowered
    assert "describes the past, not today" in lowered


def test_the_judge_is_told_a_deck_cannot_corroborate_itself(monkeypatch):
    """Buffer's "$150,000 annual revenue run rate" was marked SUPPORTS at 0.96
    on the strength of pitchdeckinspo.com, failory.com and slideshare.net --
    three sites hosting Buffer's own deck. Intercom's claim was 'confirmed' by
    two Scribd copies of the Intercom deck."""
    seen = _capture_prompt(monkeypatch)
    cv.groq_judge("$150,000 annual revenue run rate", EVIDENCE, as_of="2011")
    lowered = seen["prompt"].lower()
    assert "cannot corroborate itself" in lowered


@pytest.mark.parametrize("url", [
    "https://www.slideshare.net/slideshow/buffer-deck",
    "https://www.failory.com/pitch-deck/buffer",
    "https://www.scribd.com/document/375877002/Intercom-first-Pitch-Deck-pdf",
    "https://www.pitchdeckinspo.com/deck/Buffer_x/slides",
    "https://media.genppt.com/pitch-decks/uber/uber-pitch-deck-2008.pdf",
])
def test_deck_mirrors_are_dropped_as_circular_evidence(url):
    assert ef.is_deck_mirror(url) is True


@pytest.mark.parametrize("url", [
    "https://buffer.com/pricing",
    "https://investors.airbnb.com/press-releases/default.aspx",
    "https://www.crunchbase.com/organization/coinbase",
    "https://en.wikipedia.org/wiki/CouchSurfing",
])
def test_genuine_independent_sources_are_not_dropped(url):
    """The filter must not become a general-purpose blocklist. A company's own
    investor-relations page is a legitimate source; a mirror of its pitch deck
    is not."""
    assert ef.is_deck_mirror(url) is False


def test_filter_records_why_a_circular_source_was_removed():
    kept, dropped = ef.filter_sources(
        [{"url": "https://www.slideshare.net/x", "title": "Buffer deck", "snippet": "800 users"},
         {"url": "https://buffer.com/pricing", "title": "Buffer pricing", "snippet": "plans"}],
        context="Buffer social media scheduling", company="Buffer",
    )
    assert [item["url"] for item in kept] == ["https://buffer.com/pricing"]
    assert "circular" in dropped[0]["_drop_reason"]


def test_company_scoped_queries_drop_the_noise_template():
    """"is it true that {claim}" contributed the word "true" to every query,
    which is what retrieved dictionary entries for "true" and two unrelated
    businesses with "true" in their names (truemfg.com, trueccu.com)."""
    scoped = cv.build_queries("Seed round target is $8M", company="ClaimFlow")
    unscoped = cv.build_queries("Seed round target is $8M")

    assert all("is it true that" not in q for q in scoped + unscoped)
    assert all("ClaimFlow" in q for q in scoped[:2]), (
        "a company-scoped query must actually contain the company name"
    )
    assert any("false wrong debunked" in q for q in unscoped), (
        "the refutation template is retained when no company is known, because "
        "it is what finds a public claim's rebuttal"
    )
