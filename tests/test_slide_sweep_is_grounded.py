"""A recovered claim has to be on the slide it was attributed to.

WHAT THIS GUARDS

The first extraction reads the whole deck, is told to cover all of it, and
then ranks by how checkable each claim is and returns the best. That is right
for a claims table and it is why whole slides go unrepresented: on Buffer's
deck the first pass returned ten good claims and left the integrations slide
and the competitive-landscape slide untouched, both of which name real things.

The sweep asks again about only those slides, which changes the question from
"what are the best claims in this deck" to "what does THIS slide assert". It
raised that deck from 75% to 91.7% coverage, recovering "6 integrations so
far" and "Dashboards: Hootsuite, CoTweet, TweetDeck, Seesmic" verbatim.

A second pass is also a second opportunity to invent, and coverage bought with
invented claims is worse than no coverage at all -- it moves a number the
reader uses to decide whether to trust the rest of the report. So every
recovered claim is checked word for word against the slide it came from, and
these tests hold the model to that check by feeding it answers a model might
plausibly give.

The provider call is stubbed: what is under test is the guard around it, not
the provider.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import structured_extractor
from structured_extractor import sweep_unrepresented_slides

SLIDES = [
    "A sharing standard - 6 integrations so far - in talks with Reeder and Feedly",
    "Competitive Competition Landscape - Dashboards: Hootsuite, CoTweet, TweetDeck, Seesmic",
]
NUMBERS = [10, 11]


def _stub_provider(monkeypatch, payload: dict):
    """Make the model return exactly `payload`, and charge nothing for it."""
    def fake_create(**_kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )

    monkeypatch.setattr(
        structured_extractor, "get_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))),
    )
    monkeypatch.setattr(structured_extractor, "pace_for", lambda *a, **k: None)
    monkeypatch.setattr(structured_extractor, "settle_usage", lambda *a, **k: None)


def test_a_claim_copied_from_the_slide_is_kept(monkeypatch):
    _stub_provider(monkeypatch, {"claims": [
        {"slide": 10, "claim": "6 integrations so far - in talks with Reeder and Feedly"},
    ]})
    assert sweep_unrepresented_slides(SLIDES, NUMBERS, []) == [
        "6 integrations so far - in talks with Reeder and Feedly"
    ]


def test_a_summary_of_the_slide_is_dropped(monkeypatch):
    """The failure mode this exists for: fluent, plausible, not on the slide."""
    _stub_provider(monkeypatch, {"claims": [
        {"slide": 11, "claim": "The company competes with several established social media dashboards"},
    ]})
    assert sweep_unrepresented_slides(SLIDES, NUMBERS, []) == []


def test_a_claim_attributed_to_the_wrong_slide_is_dropped(monkeypatch):
    """Grounding is per slide, not against the deck as a whole."""
    _stub_provider(monkeypatch, {"claims": [
        {"slide": 11, "claim": "6 integrations so far - in talks with Reeder and Feedly"},
    ]})
    assert sweep_unrepresented_slides(SLIDES, NUMBERS, []) == []


def test_a_claim_the_first_pass_already_found_is_not_repeated(monkeypatch):
    _stub_provider(monkeypatch, {"claims": [
        {"slide": 10, "claim": "6 integrations so far - in talks with Reeder and Feedly"},
    ]})
    existing = ["6 integrations so far - in talks with Reeder and Feedly"]
    assert sweep_unrepresented_slides(SLIDES, NUMBERS, existing) == []


def test_a_slide_with_nothing_checkable_contributes_nothing(monkeypatch):
    """Omitting a slide is the instructed behaviour, not a failure."""
    _stub_provider(monkeypatch, {"claims": []})
    assert sweep_unrepresented_slides(["founders@bufferapp.com"], [13], []) == []


def test_a_provider_failure_costs_nothing(monkeypatch):
    """The sweep is an improvement, never a dependency: it must not break an upload."""
    def boom(**_kwargs):
        raise RuntimeError("provider is down")

    monkeypatch.setattr(
        structured_extractor, "get_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=boom))),
    )
    monkeypatch.setattr(structured_extractor, "pace_for", lambda *a, **k: None)
    assert sweep_unrepresented_slides(SLIDES, NUMBERS, []) == []


def test_malformed_output_is_survived(monkeypatch):
    _stub_provider(monkeypatch, {"claims": ["not a dict", {"slide": "ten"}, {"claim": ""}]})
    assert sweep_unrepresented_slides(SLIDES, NUMBERS, []) == []


def test_empty_slides_are_not_sent_at_all(monkeypatch):
    called = False

    def fake_create(**_kwargs):
        nonlocal called
        called = True
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])

    monkeypatch.setattr(
        structured_extractor, "get_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))),
    )
    assert sweep_unrepresented_slides(["", "   "], [1, 2], []) == []
    assert called is False, "a call was spent on slides with no text"


@pytest.mark.parametrize("cap", [1, 2])
def test_the_sweep_is_bounded(monkeypatch, cap):
    """One call, and never the whole deck: this runs on every upload."""
    seen: list[str] = []

    def fake_create(**kwargs):
        seen.append(kwargs["messages"][-1]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])

    monkeypatch.setattr(
        structured_extractor, "get_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))),
    )
    monkeypatch.setattr(structured_extractor, "pace_for", lambda *a, **k: None)
    monkeypatch.setattr(structured_extractor, "settle_usage", lambda *a, **k: None)

    sweep_unrepresented_slides(SLIDES * 6, NUMBERS * 6, [], max_slides=cap)
    assert len(seen) == 1
    assert seen[0].count("--- Slide ") == cap
