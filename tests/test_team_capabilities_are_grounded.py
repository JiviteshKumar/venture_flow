"""A capability score has to point at text the agent was actually given.

WHAT THIS GUARDS

The team specialist is asked for 4-6 capability areas, each scored 0-100 with
"a short verbatim evidence excerpt", and told to return an empty list when
there is no team evidence at all. That is a prompt instruction, and a prompt
instruction is not a guarantee. It failed visibly: a report rendered
"SEARCHED -- NO FOUNDERS FOUND" at the bottom of the page while a radar above
it scored Commercial Execution at 80 for a deck with no team slide. Nothing in
the deck said that, and nothing had to.

This is the same class of failure `agents/founder_research.py` guards against
for names, and it takes the same remedy: the model may only point at text it
was handed, and anything else is removed by a check it does not participate in.

WHY THE MATCH IS NOT EXACT

Models re-punctuate, fix casing and drop a stray line break when quoting.
Rejecting a real quote over a comma would push the radar toward showing
nothing, which is its own kind of wrong. Both sides are normalised to bare
lower-case words and a capability survives if any six-word run of its evidence
appears in the source. Six words of exact sequence is far past coincidence.
"""
from __future__ import annotations

from agents.investment_agents import ground_team_capabilities

DECK = """
MySQL AB. The world's most popular open source database.
Our commercial licensing and support business serves enterprises worldwide.
We have over 5 million active installations across web companies.
"""

FOUNDER_CHECKS = [
    {
        "name": "Michael Widenius",
        "evidence_summary": "Co-founded MySQL AB and wrote the original version of the database.",
    }
]


def _cap(area: str, evidence: str, score: int = 70) -> dict:
    return {"area": area, "score": score, "evidence": evidence}


def test_a_quote_that_is_in_the_deck_survives():
    team = {"capabilities": [
        _cap("Commercial Execution", "commercial licensing and support business serves enterprises"),
    ]}
    out = ground_team_capabilities(team, DECK, [])
    assert [c["area"] for c in out["capabilities"]] == ["Commercial Execution"]
    assert "capabilities_dropped" not in out


def test_requoting_does_not_lose_a_real_quote():
    """Casing, punctuation and line breaks are the model's, not the deck's."""
    team = {"capabilities": [
        _cap("Commercial Execution", "Commercial licensing and support business, serves enterprises."),
    ]}
    out = ground_team_capabilities(team, DECK, [])
    assert len(out["capabilities"]) == 1


def test_an_invented_quote_is_dropped():
    team = {"capabilities": [
        _cap("Technical Depth", "The founding team previously scaled two infrastructure companies"),
    ]}
    out = ground_team_capabilities(team, DECK, [])
    assert out["capabilities"] == []
    assert out["capabilities_dropped"] == ["Technical Depth"]
    assert "Technical Depth" in out["capabilities_dropped_reason"]


def test_an_empty_quote_is_dropped():
    """A score with nothing behind it is the exact thing being guarded."""
    team = {"capabilities": [_cap("Team Completeness", "")]}
    out = ground_team_capabilities(team, DECK, [])
    assert out["capabilities"] == []


def test_a_two_word_quote_is_too_short_to_prove_anything():
    """"strong team" appears in almost any deck by chance."""
    team = {"capabilities": [_cap("Team Completeness", "open source")]}
    out = ground_team_capabilities(team, DECK, [])
    assert out["capabilities"] == []


def test_founder_check_evidence_counts_as_a_source():
    """The background checks are the only team evidence the founders did not write."""
    team = {"capabilities": [
        _cap("Technical Depth", "wrote the original version of the database"),
    ]}
    out = ground_team_capabilities(team, DECK, FOUNDER_CHECKS)
    assert len(out["capabilities"]) == 1


def test_the_grounded_and_the_invented_are_separated_in_one_pass():
    team = {"capabilities": [
        _cap("Commercial Execution", "commercial licensing and support business serves enterprises", 80),
        _cap("Technical Depth", "deep expertise in distributed consensus protocols", 30),
        _cap("Domain Experience", "", 30),
    ]}
    out = ground_team_capabilities(team, DECK, [])
    assert [c["area"] for c in out["capabilities"]] == ["Commercial Execution"]
    assert out["capabilities_dropped"] == ["Technical Depth", "Domain Experience"]


def test_a_section_with_no_capabilities_is_untouched():
    """An agent that correctly returned nothing must not gain a dropped-list."""
    team = {"capabilities": [], "overall_assessment": "Insufficient team information"}
    out = ground_team_capabilities(team, DECK, [])
    assert out["capabilities"] == []
    assert "capabilities_dropped" not in out


def test_malformed_specialist_output_loses_its_capabilities_rather_than_raising():
    team = {"capabilities": ["not a dict", {"score": 50}, None]}
    out = ground_team_capabilities(team, DECK, [])
    assert out["capabilities"] == []
