"""Guard against a heading-vocabulary regression in extraction.

The defect this exists to catch, in full: extraction was gated on a fixed
vocabulary -- a closed 24-word verb list in `is_good_claim`, plus a team-slide
shape in `extract_founders` -- and silently returned nothing for content that
did not match. It produced no error, no low-confidence flag, and no empty-result
warning. The 2008 UberCab deck came back with two "claims", both restatements of
the same $200K raise, and a report reading `HIGH data quality (100/100)`. It took
a manual audit against the original PDF to notice, which is not a control.

These tests run on real decks from `ml/eval/decks`, via the committed fixture
built by `fixtures/build_adversarial_headings.py`. Every heading and body line
is verbatim from a deck fetched from a recorded source URL and checked against
a recorded SHA-256; nothing was authored to make a test pass.

They deliberately exercise the NON-LLM path. The schema extractor is the
primary route and is better at this, but it needs a live provider, and a
regression guard that goes quiet whenever the API key is missing or the daily
quota is spent is not a guard. The regex fallback is also what actually runs
during an outage, so it is the layer where a silent vocabulary dependency does
the most damage.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import extraction_coverage
import pdf_extractor

FIXTURE = Path(__file__).parent / "fixtures" / "adversarial_headings.json"

# The closed verb list that used to be mandatory. Kept here ONLY so a test can
# assert that content lacking every one of these words still extracts. If
# anyone reintroduces this gate, `test_bullets_without_closed_list_verbs...`
# fails immediately.
RETIRED_VERB_GATE = (
    "is", "are", "was", "were", "has", "have", "had", "will", "does", "do",
    "can", "provides", "offers", "delivers", "achieves", "uses", "reduces",
    "increases", "generates", "processes", "serves", "operates", "raised",
    "cleared", "approved",
)


def _load() -> list[dict]:
    if not FIXTURE.exists():  # pragma: no cover
        pytest.skip(f"{FIXTURE.name} missing; run fixtures/build_adversarial_headings.py")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["decks"]


DECKS = _load()
DECK_IDS = [d["company"] for d in DECKS]


def _deck_text(deck: dict) -> str:
    return "\n".join(
        "\n".join([slide["heading"], *slide["body_lines"]]) for slide in deck["slides"]
    )


def _slide_texts(deck: dict) -> list[str]:
    return [
        "\n".join([slide["heading"], *slide["body_lines"]]) for slide in deck["slides"]
    ]


@pytest.mark.parametrize("deck", DECKS, ids=DECK_IDS)
def test_corpus_decks_really_are_adversarial(deck):
    """The fixture is only a guard if these decks avoid the standard headings.

    Asserted rather than assumed: if a future corpus refresh swapped in decks
    labelled Problem/Solution/Team, every other test here would still pass
    while guarding nothing.
    """
    assert deck["nonstandard_heading_count"] >= max(1, deck["slide_count"] - 2), (
        f"{deck['company']} no longer has predominantly nonstandard headings "
        f"({deck['nonstandard_heading_count']}/{deck['slide_count']}); it can no "
        f"longer catch a heading-vocabulary regression."
    )
    assert deck["source_url"] and deck["sha256"], "fixture entry lost its provenance"


@pytest.mark.parametrize("deck", DECKS, ids=DECK_IDS)
def test_every_fixture_deck_declares_its_provenance(deck):
    """A deck kept for parser testing must never pass as ground truth.

    One corpus file is a business-school case study about a company rather than
    that company's own raise deck. It is still a real PDF with real
    unconventional headings, so it remains useful for testing the PARSER -- but
    anything that reads these fixtures has to be able to tell the difference,
    and an unlabelled fixture cannot be told apart from a verified one.
    """
    assert "provenance_confirmed" in deck, (
        f"{deck['company']} has no provenance flag; regenerate the fixture with "
        f"tests/fixtures/build_adversarial_headings.py"
    )
    if not deck["provenance_confirmed"]:
        assert deck.get("provenance_note"), (
            f"{deck['company']} is marked unconfirmed but says nothing about why. "
            f"An unexplained flag gets ignored."
        )


@pytest.mark.parametrize("deck", DECKS, ids=DECK_IDS)
def test_nonstandard_headings_still_yield_claims(deck):
    """A deck that never says "Problem" must still produce claims.

    Coinbase's 2012 deck is the clean case: twelve slides, not one of them
    headed with a word from the conventional set.
    """
    claims = pdf_extractor.extract_claims_from_text(_deck_text(deck))
    assert claims, (
        f"{deck['company']} ({deck['source_url']}) extracted ZERO claims. Its "
        f"headings are {deck['nonstandard_heading_count']}/{deck['slide_count']} "
        f"nonstandard, which is exactly the condition that used to return an "
        f"empty result in silence."
    )


@pytest.mark.parametrize("deck", DECKS, ids=DECK_IDS)
def test_extraction_does_not_depend_on_the_heading_text(deck):
    """Renaming every heading must not change what is extracted.

    This is the core invariant. Extraction is supposed to classify by content,
    so substituting each slide's heading for an unrelated one -- while leaving
    every body line untouched -- should leave the body-derived claims alone. An
    extractor keyed to heading strings fails this; one keyed to content does
    not care.
    """
    original = set(pdf_extractor.extract_claims_from_text(_deck_text(deck)))

    renamed_text = "\n".join(
        "\n".join([f"Slide {i}", *slide["body_lines"]])
        for i, slide in enumerate(deck["slides"], start=1)
    )
    renamed = set(pdf_extractor.extract_claims_from_text(renamed_text))

    # Claims derived from body content must survive the rename. Claims derived
    # from a heading legitimately will not, so this compares the body-derived
    # majority rather than demanding set equality.
    body_lines = {
        line.strip()
        for slide in deck["slides"]
        for line in slide["body_lines"]
    }
    body_derived = {
        c for c in original
        if any(c[:30] in line or line[:30] in c for line in body_lines)
    }
    if not body_derived:
        pytest.skip(f"{deck['company']}: no body-derived claims to compare")

    survived = body_derived & renamed
    assert len(survived) >= len(body_derived) * 0.8, (
        f"{deck['company']}: renaming slide headings changed extraction. "
        f"{len(body_derived) - len(survived)} of {len(body_derived)} body-derived "
        f"claims disappeared, so extraction is reading headings, not content. "
        f"Lost: {sorted(body_derived - survived)[:3]}"
    )


@pytest.mark.parametrize("deck", DECKS, ids=DECK_IDS)
def test_bullets_without_closed_list_verbs_are_still_claims(deck):
    """Real deck bullets carrying a fact but no closed-list verb must extract.

    This is the precise line the old gate cut. On the real UberCab deck it
    dropped "U.S. taxi & limousine industry sized at roughly $4.2B annually",
    "Revenue model: percentage cut of every fare", and every other noun-phrase
    bullet -- which is most of how decks are written.
    """
    candidates = []
    for slide in deck["slides"]:
        for line in slide["body_lines"]:
            cleaned = pdf_extractor.clean_sentence(line)
            words = {w.lower().strip(".,;:") for w in cleaned.split()}
            has_number = any(ch.isdigit() for ch in cleaned)
            if (
                len(cleaned) >= 35
                and len(cleaned.split()) >= 6
                and has_number
                and not words & set(RETIRED_VERB_GATE)
            ):
                candidates.append(cleaned)

    if not candidates:
        pytest.skip(f"{deck['company']}: no verb-free factual bullets in this deck")

    accepted = [c for c in candidates if pdf_extractor.is_good_claim(c)]
    assert accepted, (
        f"{deck['company']} ({deck['source_url']}): none of "
        f"{len(candidates)} factual bullets without a closed-list verb were "
        f"accepted as claims. The retired verb gate appears to be back. "
        f"Example rejected: {candidates[0]!r}"
    )


@pytest.mark.parametrize("deck", DECKS, ids=DECK_IDS)
def test_coverage_warns_when_content_was_dropped(deck):
    """Coverage must shout when a deck full of content extracts to nothing.

    The whole point of the metric: "we found nothing" and "there was nothing to
    find" must stop producing identical output. Given real slides and an empty
    extraction, coverage has to report LOW rather than staying silent.
    """
    result = extraction_coverage.compute(_deck_text(deck), {}, _slide_texts(deck))
    assert result["available"]
    assert result["verdict"] in {"LOW", "EMPTY"}, (
        f"{deck['company']}: extraction produced nothing from "
        f"{deck['slide_count']} real slides and coverage reported "
        f"{result['verdict']} ({result['coverage_pct']}%). A reader would not be "
        f"warned that the tool, not the deck, was the problem."
    )
    assert result["coverage_pct"] < 50.0
    assert "parsing gap" in result["interpretation"].lower()


@pytest.mark.parametrize("deck", DECKS, ids=DECK_IDS)
def test_coverage_rises_when_content_is_captured(deck):
    """The metric must be able to go up, or it is just a constant alarm.

    Feeding every body line back as a captured claim is the synthetic ceiling:
    if coverage does not read HIGH there, the metric cannot distinguish a good
    extraction from a bad one and its warnings mean nothing.
    """
    perfect = {
        "claims": [
            line for slide in deck["slides"] for line in slide["body_lines"]
        ] + [slide["heading"] for slide in deck["slides"]],
    }
    result = extraction_coverage.compute(_deck_text(deck), perfect, _slide_texts(deck))
    assert result["coverage_pct"] >= 80.0, (
        f"{deck['company']}: coverage read {result['coverage_pct']}% when every "
        f"line WAS captured, so a low score cannot be trusted to mean anything."
    )
    assert result["verdict"] == "HIGH"
