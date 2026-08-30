"""Section B (founder research) and Section C (the relabelled quality score).

Both are safety properties rather than features, and both are tested without a
live provider so they cannot quietly stop being checked when quota runs out.

The Section B property is anti-fabrication. Asking a model who founded a
company is the single most dangerous call in this pipeline, because it will
answer from memory whether or not the search returned anything, a wrong name
is indistinguishable from a right one at a glance, and everything downstream
inherits its authority -- a full background check gets written about a person
who may have nothing to do with the company. The guard is a literal string
check against retrieved source text, and these tests pin it.

The Section C property is that relabelling `data_quality` did not move the
number. `data_quality.score` is an input to `_evidence_components`, so a change
there would shift every VentureFlow Score in the product, which this pass was
explicitly not allowed to do.
"""
from __future__ import annotations

import pytest

import agents.founder_research as fr
import pdf_extractor
import ventureflow_agent as vf


# ── Section A: founder names outside a team slide ──────────────────────────
#
# Names in these cases are deliberately fictional. They exercise a regex, not a
# claim about any company, so nothing here asserts a fact that would need a
# source.

def test_a_name_and_role_on_one_line_is_a_founder():
    """"Melanie Perkins, Founder" -- the title-slide form.

    The extractor only understood a name line followed by a role line, which is
    what a team slide looks like. A deck with no team slide puts the founder on
    the title slide instead, name and title together on one line -- so the one
    case where this was the only path to a founder name was the case it could
    not read.
    """
    deck = "Acme Robotics\nMaking things move\nAda Lovelace, Founder\nSeed deck 2011\n"
    found = pdf_extractor.extract_founders(deck)
    assert [(f["name"], f["role"]) for f in found] == [("Ada Lovelace", "Founder")]


def test_the_two_line_team_slide_form_still_works():
    """The original shape must keep working; this is an addition, not a swap."""
    deck = "Team\nAda Lovelace\nCo-Founder & CTO\nBuilt analytical engines.\n"
    found = pdf_extractor.extract_founders(deck)
    assert found and found[0]["name"] == "Ada Lovelace"


def test_an_inline_comma_line_that_is_not_a_person_is_rejected():
    """The role half is validated, so ordinary prose does not become a founder.

    Without that check "San Francisco, California" and a use-of-funds bullet
    both match the name-comma-text shape.
    """
    deck = (
        "Initial Service Area\n"
        "San Francisco, California\n"
        "Trips to/from restaurants, bars and shows\n"
        "Union Square, a dense pickup zone\n"
    )
    assert pdf_extractor.extract_founders(deck) == []


# ── Section B: the anti-fabrication guard ──────────────────────────────────

def _evidence(*pairs):
    return [
        {"title": t, "url": f"https://example.test/{i}", "snippet": s}
        for i, (t, s) in enumerate(pairs)
    ]


def test_a_name_absent_from_the_evidence_is_rejected():
    """The failure mode this whole module exists to prevent.

    A model that answers "who founded Acme" from training data rather than from
    the supplied search results must not get that name into a report.
    """
    evidence = _evidence(("Acme raises Series A", "Acme announced a funding round today."))
    assert fr._grounded("Ada Lovelace", evidence) == []


def test_a_name_present_in_the_evidence_is_accepted_with_its_sources():
    evidence = _evidence(
        ("Acme profile", "Acme was co-founded by Ada Lovelace in 2011."),
        ("Unrelated", "Nothing relevant here."),
    )
    sources = fr._grounded("Ada Lovelace", evidence)
    assert sources == ["https://example.test/0"]


def test_a_name_merely_present_on_the_page_is_not_a_founder():
    """Presence is not the same fact as founding, and conflating them invents
    a relationship rather than a name.

    Aggregator company profiles list founders, executives, investors and board
    members in identical markup, so a presence-only check reads them all as
    founders. The result is a real person attached to a claim no source made --
    harder to catch than a hallucinated name and just as wrong.
    """
    evidence = _evidence(
        (
            "Acme - Company Profile, Team, Funding",
            "Acme was founded by Ada Lovelace. Leadership: Grace Hopper, VP "
            "Engineering. Investors include Charles Babbage. Board: Alonzo Church.",
        ),
    )
    assert fr._grounded("Ada Lovelace", evidence) == ["https://example.test/0"]
    for bystander in ("Grace Hopper", "Charles Babbage", "Alonzo Church"):
        assert fr._grounded(bystander, evidence) == [], (
            f"{bystander} appears on the page but is not described as a founder"
        )


def test_a_hyphenated_name_matches_its_unhyphenated_form():
    """Punctuation must not be able to discard a real founder.

    Measured on Alan: every source writes "Jean-Charles Samuelian-Werve", the
    model returned it unhyphenated, the literal check missed, and a genuine
    co-founder was reported as ungrounded. The guard exists to reject names the
    sources do not support -- not names whose hyphens changed in transit.
    """
    evidence = _evidence(
        ("Alan profile", "Alan was co-founded by Jean-Charles Samuelian-Werve in 2016."),
    )
    assert fr._grounded("Jean Charles Samuelian Werve", evidence) == [
        "https://example.test/0"
    ]
    assert fr._grounded("Jean-Charles Samuelian-Werve", evidence) == [
        "https://example.test/0"
    ]


def test_normalising_punctuation_does_not_ground_an_unrelated_person():
    """The tolerance is for punctuation only, not for different names."""
    evidence = _evidence(
        ("Alan profile", "Alan was co-founded by Jean-Charles Samuelian-Werve in 2016."),
    )
    assert fr._grounded("Charles Samuelian", evidence) == []


def test_founder_language_must_be_near_the_name_not_merely_on_the_page():
    """A "founder" mentioned in an unrelated paragraph must not carry over."""
    filler = "x" * 600
    evidence = _evidence(
        ("Acme news", f"Acme was founded in 2011. {filler} Grace Hopper joined recently."),
    )
    assert fr._grounded("Grace Hopper", evidence) == []


def test_grounding_also_searches_fetched_page_bodies():
    """Snippets frequently omit the founder's name even on the right page.

    Search snippets are selected to match the query, not to answer it, so the
    company's own leadership page can rank first and still not mention a name
    in its snippet. The body text has to count as evidence or the guard rejects
    correct names.
    """
    evidence = [
        {
            "title": "Leadership",
            "url": "https://example.test/leadership",
            "snippet": "Meet the team behind Acme.",
            "page_text": "Ada Lovelace, co-founder and CEO, started Acme in 2011.",
        }
    ]
    assert fr._grounded("Ada Lovelace", evidence) == ["https://example.test/leadership"]


def test_company_names_and_publishers_are_not_accepted_as_people():
    """Search titles are full of things shaped like names but are not people."""
    evidence = _evidence(("Oscar Health - Wikipedia", "Oscar Health is an insurer."))
    assert fr._grounded("Oscar Health", evidence) == []
    assert fr._grounded("Crunchbase Company", evidence) == []


def test_single_word_and_overlong_strings_are_not_people():
    evidence = _evidence(("x", "Madonna Ada Lovelace Smith Jones Brown Green"))
    assert fr._grounded("Madonna", evidence) == []
    assert fr._grounded("Ada Lovelace Smith Jones Brown Green", evidence) == []


@pytest.fixture
def research_enabled(monkeypatch):
    """Opt back in to founder research for the tests that are about it.

    conftest disables it suite-wide so no test acquires a live web dependency
    by accident. These tests stub `search_web` themselves, so they exercise the
    logic without touching the network.
    """
    monkeypatch.setattr(fr, "RESEARCH_ENABLED", True)


def test_disabled_research_is_reported_as_not_attempted():
    """Disabled must never be presented as "searched and found nothing".

    Those are different facts and only one of them is evidence about the
    company. This is the same distinction the whole coverage metric exists to
    preserve, applied to the founder path.
    """
    with_disabled = fr.discover_founders("Acme Robotics")
    assert with_disabled["found"] is False
    assert with_disabled["searched"] is False
    assert "disabled" in with_disabled["reason"].lower()
    assert "not evidence" in with_disabled["reason"].lower()


def test_no_search_results_reports_not_found_honestly(research_enabled, monkeypatch):
    """"We searched and found nothing" must be a real, reasoned output.

    Not an exception, not an empty section, and above all not a guess.
    """
    monkeypatch.setattr(fr, "search_web", lambda *a, **k: [])
    result = fr.discover_founders("Acme Robotics", deck_date="2011")
    assert result["found"] is False
    assert result["searched"] is True
    assert "no results" in result["reason"].lower()


def test_ungrounded_proposals_are_dropped_and_reported(research_enabled, monkeypatch):
    """A model naming someone absent from the evidence yields found=False.

    And the rejection is recorded rather than swallowed: a model doing this is
    a signal about the run that a maintainer should be able to see.
    """
    evidence = _evidence(("Acme news", "Acme raised a round. No founder is named here."))
    monkeypatch.setattr(fr, "search_web", lambda *a, **k: evidence)
    monkeypatch.setattr(fr, "fetch_page_text", lambda *a, **k: "")
    monkeypatch.setattr(fr, "_propose_names", lambda *a, **k: ["Ada Lovelace"])

    result = fr.discover_founders("Acme Robotics")
    assert result["found"] is False
    assert result["rejected_ungrounded"] == ["Ada Lovelace"]
    assert "ungrounded" in result["reason"].lower()


def test_a_total_search_failure_is_not_reported_as_found_nothing(research_enabled, monkeypatch):
    """The conflation this whole project exists to remove, in the founder path.

    With the network down or the provider rate-limiting, every query throws.
    Before this, the report said "searched public sources, no founder names
    could be established" -- a statement about the COMPANY, made on the
    strength of a statement about our connectivity. A reader would reasonably
    conclude the founders are not publicly documented.
    """
    def boom(*a, **k):
        raise ConnectionError("provider unreachable")

    monkeypatch.setattr(fr, "search_web", boom)
    result = fr.discover_founders("Acme Robotics", deck_date="2011")

    assert result["found"] is False
    assert result["searched"] is False, "a failed search must not report as searched"
    assert result["search_failed"] is True
    assert result["queries_failed"] > 0
    assert "could not be completed" in result["reason"].lower()
    assert "do not read this as evidence" in result["reason"].lower()


def test_a_partial_search_failure_still_reports_what_ran(research_enabled, monkeypatch):
    """Some queries failing is not the same as all of them failing."""
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] % 2:
            raise TimeoutError("slow")
        return []

    monkeypatch.setattr(fr, "search_web", flaky)
    result = fr.discover_founders("Acme Robotics", deck_date="2011")
    assert result["searched"] is True, "searches did run; say so"
    assert result["search_failed"] is False
    assert result["queries_failed"] > 0
    assert "failed" in result["reason"].lower()


def test_conflicting_founder_sets_are_all_surfaced_with_their_sources(
    research_enabled, monkeypatch
):
    """Two sources disagreeing must not be resolved by silently picking one.

    Aggregators genuinely disagree about early-stage founding teams. The report
    has to show the disagreement and whose page each name came from, so a
    partner can weigh the sources; choosing one for them hides the very thing
    that should prompt a human check.
    """
    evidence = [
        {
            "title": "Source A",
            "url": "https://a.test/acme",
            "snippet": "Acme was founded by Ada Lovelace and Grace Hopper.",
        },
        {
            "title": "Source B",
            "url": "https://b.test/acme",
            "snippet": "Acme was founded by Ada Lovelace and Alonzo Church.",
        },
    ]
    monkeypatch.setattr(fr, "search_web", lambda *a, **k: evidence)
    monkeypatch.setattr(fr, "fetch_page_text", lambda *a, **k: "")
    monkeypatch.setattr(
        fr, "_propose_names",
        lambda *a, **k: ["Ada Lovelace", "Grace Hopper", "Alonzo Church"],
    )

    result = fr.discover_founders("Acme Robotics")
    by_name = {f["name"]: f["discovery_sources"] for f in result["founders"]}

    # All three surface -- none is dropped to make the sources agree.
    assert set(by_name) == {"Ada Lovelace", "Grace Hopper", "Alonzo Church"}
    # And each carries only the source that actually attributes it, so the
    # disagreement is legible rather than averaged away.
    assert by_name["Grace Hopper"] == ["https://a.test/acme"]
    assert by_name["Alonzo Church"] == ["https://b.test/acme"]
    assert sorted(by_name["Ada Lovelace"]) == ["https://a.test/acme", "https://b.test/acme"]


def test_one_person_listed_under_two_spellings_is_merged_once(research_enabled, monkeypatch):
    """Punctuation variants of one name are one founder, not two.

    Tracxn's Alan profile writes both "Jean-Charles Samuelian-Werve" and "Jean
    Charles Samuelian Werve" in a single sentence. Reporting two founders from
    that is plainly wrong, and merging on exact normalised identity involves no
    judgement -- the strings are equal once punctuation is flattened.
    """
    evidence = _evidence(
        (
            "Acme profile",
            "Acme was founded by Jean-Charles Samuelian-Werve and "
            "Jean Charles Samuelian Werve and Grace Hopper.",
        ),
    )
    monkeypatch.setattr(fr, "search_web", lambda *a, **k: evidence)
    monkeypatch.setattr(fr, "fetch_page_text", lambda *a, **k: "")
    monkeypatch.setattr(
        fr, "_propose_names",
        lambda *a, **k: [
            "Jean-Charles Samuelian-Werve", "Jean Charles Samuelian Werve", "Grace Hopper",
        ],
    )

    result = fr.discover_founders("Acme Robotics")
    names = [f["name"] for f in result["founders"]]
    assert len(names) == 2, f"the same person was reported twice: {names}"
    merged = next(f for f in result["founders"] if "Samuelian" in f["name"])
    assert sorted(merged["name_variants"]) == [
        "Jean Charles Samuelian Werve", "Jean-Charles Samuelian-Werve",
    ], "both spellings must stay visible on the merged entry"


def test_two_founders_sharing_a_forename_are_never_merged():
    """The reason this is exact-match only rather than a similarity threshold.

    Alan's genuine founders are Charles Gorintin and Jean-Charles
    Samuelian-Werve. Any fuzzy matcher tuned to catch a spelling variant is
    also tuned to collapse these two real people, and silently dropping a
    founder is worse than showing a duplicate.
    """
    founders = [
        {"name": "Charles Gorintin"},
        {"name": "Jean-Charles Samuelian-Werve"},
    ]
    assert fr._possible_same_person(founders) == []


def test_a_truncated_name_variant_is_flagged_but_not_merged():
    """Weaker-than-exact similarity is surfaced for a human, never acted on."""
    founders = [
        {"name": "Charles Samuelian"},
        {"name": "Jean Charles Samuelian Werve"},
    ]
    flags = fr._possible_same_person(founders)
    assert len(flags) == 1
    assert set(flags[0]["names"]) == {"Charles Samuelian", "Jean Charles Samuelian Werve"}
    assert "NOT been merged" in flags[0]["reason"]


def test_a_shared_surname_alone_is_not_flagged():
    """Co-founders are often siblings or spouses; flagging every pair that
    shares a surname would make the flag worthless."""
    founders = [{"name": "Ada Hopper"}, {"name": "Grace Hopper"}]
    assert fr._possible_same_person(founders) == []


def test_a_one_word_company_name_gets_deck_context_in_its_queries():
    """"Alan founders" is not a searchable question; the deck says which Alan.

    Measured: without context the search returned Alan Turing and Alan Saunders
    and established nothing about the company whose deck was uploaded.
    """
    queries = fr._build_queries(
        "Alan", "", "2016", context="Alan Health insurance for the digital age France"
    )
    assert any("health" in q.lower() and "insurance" in q.lower() for q in queries)
    # The company's own name must not be its own disambiguator.
    assert not any(q.lower().startswith("alan alan") for q in queries)


# ── Section C: the label moved, the number did not ─────────────────────────

_ARGS = (["a claim about revenue", "another claim"], "A" * 400, "B" * 400, 1_000_000.0)


def test_the_quality_score_is_unchanged_by_the_coverage_rework():
    """The number that feeds `_evidence_components` must be untouched.

    Pinned because this pass was allowed to rename the label and add context
    beside it, and was explicitly not allowed to move the VentureFlow Score.
    """
    baseline = vf.assess_data_quality(*_ARGS)
    with_low_coverage = vf.assess_data_quality(
        *_ARGS,
        coverage={
            "available": True,
            "coverage_pct": 12.0,
            "verdict": "LOW",
            "represented_slides": 2,
            "content_slides": 17,
        },
    )
    assert with_low_coverage["score"] == baseline["score"]
    assert with_low_coverage["quality"] == baseline["quality"]
    assert with_low_coverage["can_proceed"] == baseline["can_proceed"]


def test_the_label_no_longer_claims_to_be_about_data_quality():
    """The old name let a reader take an input check for a parsing check.

    That is not hypothetical: a report read `HIGH data quality (100/100)`
    directly above a claims table holding a fraction of the deck.
    """
    quality = vf.assess_data_quality(*_ARGS)
    assert quality["label"] == "Input Completeness"
    assert "not a measure of how much of the deck" in quality["measures"].lower()


def test_low_coverage_adds_a_warning_next_to_the_completeness_score():
    """A high completeness score must never stand unqualified beside lost content."""
    quality = vf.assess_data_quality(
        *_ARGS,
        coverage={
            "available": True,
            "coverage_pct": 12.0,
            "verdict": "LOW",
            "represented_slides": 2,
            "content_slides": 17,
        },
    )
    assert quality["extraction_coverage_pct"] == 12.0
    assert quality["extraction_verdict"] == "LOW"
    assert any("coverage" in w.lower() for w in quality["warnings"])
    assert any("not because the deck is thin" in w.lower() for w in quality["warnings"])


def test_high_coverage_adds_context_without_a_warning():
    quality = vf.assess_data_quality(
        *_ARGS,
        coverage={
            "available": True,
            "coverage_pct": 91.0,
            "verdict": "HIGH",
            "represented_slides": 20,
            "content_slides": 22,
        },
    )
    assert quality["extraction_coverage_pct"] == 91.0
    assert not any("coverage" in w.lower() for w in quality["warnings"])
