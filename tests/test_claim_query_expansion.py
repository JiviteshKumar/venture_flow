"""A claim that compares two companies must retrieve evidence about both.

Four of the six errors on ml/eval/claim_benchmark.jsonl were one shape:

    "Lyft went public in March 2019, before Uber's initial public offering."
        gold SUPPORTS, predicted NOT_ENOUGH_INFO. Every retrieved source was
        about Lyft. The judge's own reasoning: "none of the provided sources
        give the date of Uber's initial public offering".

    "Lyft operates in more countries than Uber."
        gold REFUTES, predicted NOT_ENOUGH_INFO, for the same reason.

The judge was right both times. Every query template anchors on the claim as a
whole, so retrieval returns pages about whichever entity the claim leads with,
and the second entity is never searched for. Adding one query per additional
entity is the same move that fixed company-scoped retrieval, applied to the
entity mentioned second.

The risk this introduces is over-matching: deck claims are fragments that begin
with a capitalised verb ("Partnered with Stripe", "Launched in 2023"), and a
search for the company "Partnered" both wastes a slot and displaces a real
entity. Most of the tests below are about that direction.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.claim_verifier import build_queries, named_entities  # noqa: E402


class TestTheSecondEntityIsFound:
    @pytest.mark.parametrize("claim,expected", [
        ("Lyft went public in March 2019, before Uber's initial public offering.",
         "Uber"),
        ("Lyft operates in more countries than Uber.", "Uber"),
        ("IBM acquired Red Hat in 2019 for approximately $34 billion.", "Red Hat"),
        ("Stripe processes more payment volume than Adyen.", "Adyen"),
    ])
    def test_the_trailing_entity_is_extracted(self, claim, expected):
        assert expected in named_entities(claim)

    def test_a_query_is_anchored_on_it(self):
        claim = "Lyft operates in more countries than Uber."
        queries = build_queries(claim)
        assert any(q.startswith('"Uber"') for q in queries), (
            f"no query retrieves evidence about Uber: {queries}"
        )


class TestElliptcalDeckClaimsAreLeftAlone:
    """These are what the verifier actually sees most of the time, and none of
    them contains a second company. Every extraction here is a false positive
    that costs a search slot."""

    @pytest.mark.parametrize("claim", [
        "Partnered with Stripe and Plaid for payments.",
        "Launched in 2023 after two years of development.",
        "Grew ARR 4x last year.",
        "Seed round target is $8M.",
        "We grew ARR 4x last year in Q3.",
        "Reached 10,000 monthly active users.",
    ])
    def test_a_leading_verb_is_not_a_company(self, claim):
        first_word = claim.split()[0].rstrip(".,")
        assert first_word not in named_entities(claim), (
            f"'{first_word}' was treated as a company; a search for it "
            f"displaces a real entity"
        )

    def test_real_partners_are_still_found(self):
        """The other half: the leading verb must be dropped without dropping
        the companies behind it."""
        found = named_entities("Partnered with Stripe and Plaid for payments.")
        assert "Stripe" in found and "Plaid" in found

    @pytest.mark.parametrize("claim,not_an_entity", [
        ("Notion raised a Series C funding round in 2020.", "C"),
        ("Closed the round in March 2024.", "March"),
        ("Revenue reached $4.2M in Q3.", "Q3"),
    ])
    def test_calendar_and_round_words_are_not_companies(self, claim, not_an_entity):
        assert not_an_entity not in named_entities(claim)


class TestTheQuerySetStaysBounded:
    def test_at_most_two_extra_queries(self):
        claim = ("Integrates with Salesforce, HubSpot, Zendesk, Workday and "
                 "NetSuite.")
        base = 5  # the company-scoped templates
        assert len(build_queries(claim, company="Acme")) <= base + 2

    def test_the_existing_templates_are_unchanged(self):
        """Retrieval quality on the other 128 benchmark claims rests on these."""
        queries = build_queries("ARR grew 4x", company="Acme")
        assert queries[:5] == [
            '"Acme" ARR grew 4x',
            "Acme ARR grew 4x",
            '"ARR grew 4x"',
            '"Acme" funding revenue customers announcement',
            "Acme startup company news",
        ]

    def test_the_company_is_never_re_queried_as_a_secondary_entity(self):
        """Two of the five templates already anchor on the company. The
        expansion must not add a sixth that does the same thing again."""
        claim = "Revenue at Uber grew after Uber restructured."
        queries = build_queries(claim, company="Uber")
        assert len(queries) == 5, (
            f"the company was re-queried as if it were a third party: {queries[5:]}"
        )

    def test_a_third_party_in_a_scoped_claim_still_gets_a_query(self):
        """The complement of the test above -- the skip must be scoped to the
        company itself, not to every entity in a company-scoped claim."""
        queries = build_queries("Revenue at Uber grew after Lyft exited.",
                                company="Uber")
        assert any(q.startswith('"Lyft"') for q in queries), queries

    def test_no_crash_on_degenerate_input(self):
        for weird in ("", "   ", ".", "A", "$$$", "a" * 2000):
            named_entities(weird)
            build_queries(weird)
            build_queries(weird, company="Acme")
