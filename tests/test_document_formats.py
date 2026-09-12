"""Input and output format tests.

Input: the same deck in four formats (tests/fixtures/, built by
build_fixtures.py) must yield the same facts. The fixtures are real multi-column
layouts -- a three-column problem slide, a three-column team slide with names,
roles and biographies in separate boxes, a three-tier pricing table -- because
those are the layouts that were actually being mangled, and a single-paragraph
stub would pass a broken extractor.

Output: PDF, Word and Markdown all render `report_document.build_report_blocks()`,
so the tests assert the same content survives all three rather than checking
each in isolation. A section that appears in one export and not another is the
specific failure mode having a shared content model is supposed to prevent.

No network, no LLM: extraction here is the deterministic reader plus the regex
founder pass, never `structured_extractor` (which calls Groq).
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from document_extractor import (
    SUPPORTED_FORMATS,
    UnsupportedDocument,
    extract_document,
    is_supported,
)
from pdf_extractor import extract_founders
from report_document import build_report_blocks, memo_blocks
from report_docx import build_report_docx
from report_markdown import build_report_markdown
from report_pdf import build_report_pdf

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DECK_FORMATS = ["sample_deck.pdf", "sample_deck.pptx", "sample_deck.docx", "sample_deck.md"]

EXPECTED_FOUNDERS = ["Priya Raghunathan", "Marcus Oyelaran", "Helena Vasquez"]


def read_fixture(name: str) -> dict:
    path = FIXTURES / name
    assert path.exists(), f"missing fixture {name}; run python tests/fixtures/build_fixtures.py"
    return extract_document(name, path.read_bytes())


# ── Input formats ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", DECK_FORMATS)
def test_every_format_extracts_substantial_text(name):
    document = read_fixture(name)
    assert len(document["text"]) > 400, f"{name} produced only {len(document['text'])} chars"
    assert document["format"] in SUPPORTED_FORMATS.values()
    assert document["page_count"] >= 1


@pytest.mark.parametrize("name", DECK_FORMATS)
def test_every_format_recovers_the_company_and_tagline(name):
    text = read_fixture(name)["text"]
    assert "Thornbury Freight" in text
    assert "Predictive load matching" in text


@pytest.mark.parametrize("name", DECK_FORMATS)
def test_every_format_recovers_all_three_founders(name):
    """The end-to-end point of the multi-column work: the Founder Analysis tab
    can only run if names survive extraction, and on a three-column team slide
    they only survive if reading order is reconstructed."""
    founders = extract_founders(read_fixture(name)["text"])
    assert [f["name"] for f in founders] == EXPECTED_FOUNDERS
    for founder in founders:
        assert founder["role"], f"{founder['name']} lost its role line"


@pytest.mark.parametrize("name", DECK_FORMATS)
def test_founder_biographies_are_not_interleaved(name):
    """Each biography must land on its own founder.

    This is the regression that matters. Before the column fix, a three-column
    team slide read row by row and produced three names, then three roles, then
    three biographies -- so pairing a founder with their own background was
    guesswork, and the founder verifier would have been handed one person's
    name with another's history.
    """
    founders = {f["name"]: f["background"] for f in extract_founders(read_fixture(name)["text"])}
    assert "400-truck carrier" in founders["Priya Raghunathan"]
    assert "Optimisation engineer" in founders["Marcus Oyelaran"]
    assert "TMS software" in founders["Helena Vasquez"]


@pytest.mark.parametrize("name", ["sample_deck.pdf", "sample_deck.pptx"])
def test_multi_column_pricing_tiers_stay_with_their_own_price(name):
    """Each tier, its price and its limit must appear together and in order.

    Read row-major, this slide interleaves into "$49 / $39 / Custom" followed by
    "Up to 5 / Up to 80 / Unlimited", which silently attaches the wrong price to
    the wrong tier -- a wrong number presented as a quoted fact.
    """
    text = read_fixture(name)["text"]
    for tier, price, limit in (
        ("Owner-Operator", "$49/truck/mo", "Up to 5 trucks"),
        ("Fleet", "$39/truck/mo", "Up to 80 trucks"),
        ("Enterprise", "Custom", "Unlimited trucks"),
    ):
        tier_at, price_at, limit_at = text.find(tier), text.find(price), text.find(limit)
        assert tier_at != -1 and price_at != -1 and limit_at != -1, f"{tier} block incomplete in {name}"
        assert tier_at < price_at < limit_at, f"{tier} read out of order in {name}"


@pytest.mark.parametrize("name", DECK_FORMATS)
def test_problem_statements_survive_as_whole_sentences(name):
    text = " ".join(read_fixture(name)["text"].split())
    assert "Regional carriers run 28% of their miles empty" in text
    assert "Brokers take four hours on average" in text
    assert "91% annual driver turnover" in text


def test_unsupported_extension_is_rejected_by_name_not_content():
    assert not is_supported("deck.key")
    with pytest.raises(UnsupportedDocument):
        extract_document("deck.key", b"anything")


def test_supported_check_is_case_insensitive():
    assert is_supported("DECK.PPTX")
    assert is_supported("Deck.Pdf")


def test_text_reader_survives_non_utf8_bytes():
    """Decks converted on Windows arrive as cp1252 often enough to matter, and
    a decode crash on upload is a worse outcome than a mangled dash."""
    # cp1252, not utf-8: the en dash here is a single byte 0x96, which is not
    # valid utf-8 and is exactly what a Word "save as plain text" produces.
    document = extract_document("notes.txt", "Fleet size 80 – 100 trucks".encode("cp1252"))
    assert "Fleet size 80" in document["text"]
    assert "100 trucks" in document["text"]


# ── Output formats ──────────────────────────────────────────────────────────

@pytest.fixture
def sample_report() -> dict:
    return {
        "company": "Thornbury Freight",
        "final_score": 61.5,
        "recommendation": "NEEDS MORE DILIGENCE",
        "risk_level": "MEDIUM",
        "key_concerns": ["Customer concentration in two shippers"],
        "red_flags": ["Runway under six months at current burn"],
        "positive_factors": ["GMV growing month over month"],
        "sections": {
            "ai_analysis": "Executive summary.\n\nSecond paragraph with an ampersand: R&D spend.",
            "claims": {
                "checked": 2, "supported": 1, "refuted": 0, "uncertain": 1,
                "details": [
                    {"claim": "Booked $1.4M in GMV across 62 carriers", "verdict": "NOT_ENOUGH_INFO", "confidence": 0.4},
                    {"claim": "Regional freight brokerage is an $88B market", "verdict": "SUPPORTS", "confidence": 0.9},
                ],
            },
            "founder_verification": [
                {"available": True, "name": "Priya Raghunathan", "assessment": "CONSISTENT",
                 "confidence": 0.7, "evidence_summary": "Public profile matches the stated operating background."},
            ],
            "market_comparables": {
                "available": True,
                "caveat": "Text-similarity match, not a validated comp set.",
                "comparables": [
                    {"name": "Flexport", "industry": "B2B", "stage": "Growth", "outcome": "Acquired/Public", "similarity": 0.61},
                ],
            },
            "ml_outcome_model": {
                "available": True, "probability_survives_or_exits": 0.42,
                "band": "mixed", "model_test_auc": 0.646, "caveat": "Weak proxy label.",
            },
        },
    }


def test_all_three_exports_are_built_from_the_same_blocks(sample_report):
    kinds = [b["kind"] for b in build_report_blocks(sample_report, "2026-08-23")]
    assert kinds[0] == "title"
    headings = [b["text"] for b in build_report_blocks(sample_report, "2026-08-23") if b["kind"] == "heading"]
    assert headings == [
        "Investment Memo", "Claim Verification", "Key Concerns", "Red Flags",
        "Positive Factors", "Founder Background Checks", "Comparable Companies",
        "Outcome Model Signal",
    ]


def test_pdf_export_is_a_real_pdf(sample_report):
    data = build_report_pdf(sample_report, "2026-08-23")
    assert data.startswith(b"%PDF-")
    assert len(data) > 3000


def test_pdf_export_survives_html_special_characters(sample_report):
    """reportlab parses Paragraph text as mini-HTML, so an unescaped '&' from
    an LLM memo or a company name raises instead of rendering."""
    sample_report["company"] = "Smith & Sons <Holdings>"
    assert build_report_pdf(sample_report, "2026-08-23").startswith(b"%PDF-")


def test_docx_export_is_a_real_docx_and_carries_the_content(sample_report):
    data = build_report_docx(sample_report, "2026-08-23")
    assert data[:2] == b"PK"
    with zipfile.ZipFile(__import__("io").BytesIO(data)) as archive:
        body = archive.read("word/document.xml").decode("utf-8")
    for expected in ("Thornbury Freight", "Investment Memo", "Priya Raghunathan", "Flexport"):
        assert expected in body, f"{expected!r} missing from the Word export"


def test_markdown_export_carries_the_same_sections(sample_report):
    markdown = build_report_markdown(sample_report, "2026-08-23")
    assert markdown.startswith("# VentureFlow Due Diligence Report")
    for expected in (
        "## Investment Memo", "## Founder Background Checks", "## Comparable Companies",
        "Priya Raghunathan", "Flexport", "Runway under six months",
    ):
        assert expected in markdown, f"{expected!r} missing from the Markdown export"
    # Blockquoted small print, so caveats stay visually distinct in a format
    # with no font sizes.
    assert "> Text-similarity match" in markdown


def test_markdown_tables_escape_embedded_pipes(sample_report):
    sample_report["sections"]["claims"]["details"][0]["claim"] = "Revenue | margin claim"
    markdown = build_report_markdown(sample_report, "2026-08-23")
    assert "Revenue \\| margin claim" in markdown


def test_exports_do_not_crash_on_an_empty_report():
    """A report where every optional section is missing still has to export --
    the same degrade-don't-crash contract every reader of `sections` follows."""
    bare = {"company": "Unknown", "sections": {}}
    assert build_report_pdf(bare, "2026-08-23").startswith(b"%PDF-")
    assert build_report_docx(bare, "2026-08-23")[:2] == b"PK"
    assert "VentureFlow Due Diligence Report" in build_report_markdown(bare, "2026-08-23")


# ── The memo is Markdown, and it has to stop reaching the page as Markdown ──

MEMO = "\n".join([
    "**1. EXECUTIVE SUMMARY**",
    "Match Box is a dating app.",
    "It matches users who both opt in.",
    "",
    "---",
    "",
    "**2. CLAIM VERIFICATION**",
    "",
    "| Claim | Status | Confidence |",
    "|-------|--------|------------|",
    "| Proximity matching | **Verified** | 96 % |",
    "| Mutual opt-in | Unverified | 90 % |",
    "",
    "- **Model-only baseline:** 62 / 100",
    "- **Evidence adjustment:** -2 points",
])


class TestTheMemoBecomesStructure:
    """An exported memo used to carry its own Markup: `**1. EXECUTIVE
    SUMMARY**` with the asterisks, and a claim table as a wall of `| ... |`
    lines."""

    def test_a_bold_only_line_is_a_heading(self):
        kinds = [b["kind"] for b in memo_blocks(MEMO)]
        assert kinds[0] == "subheading"
        assert memo_blocks(MEMO)[0]["text"] == "1. EXECUTIVE SUMMARY"

    def test_a_pipe_table_becomes_a_table(self):
        table = next(b for b in memo_blocks(MEMO) if b["kind"] == "table")
        assert table["header"] == ["Claim", "Status", "Confidence"]
        assert len(table["rows"]) == 2, "the |---| separator row is not content"
        assert table["rows"][0][0] == "Proximity matching"

    def test_dashes_become_bullets_and_the_rule_disappears(self):
        bullets = next(b for b in memo_blocks(MEMO) if b["kind"] == "bullets")
        assert len(bullets["items"]) == 2
        assert not any(b.get("text", "").strip() == "---" for b in memo_blocks(MEMO))

    def test_consecutive_prose_lines_stay_one_paragraph(self):
        paragraphs = [b["text"] for b in memo_blocks(MEMO) if b["kind"] == "text"]
        assert paragraphs[0].startswith("Match Box is a dating app.")
        assert "both opt in" in paragraphs[0]

    def test_plain_prose_survives_untouched(self):
        """A memo with no Markdown at all must not be mangled by the parser."""
        blocks = memo_blocks("One sentence.\n\nAnother paragraph.")
        assert [b["kind"] for b in blocks] == ["text", "text"]

    def test_the_pdf_carries_no_stray_asterisks(self, sample_report):
        sample_report["sections"]["ai_analysis"] = MEMO
        text = _pdf_text(build_report_pdf(sample_report, "2026-08-23"))
        assert "**" not in text
        assert "1. EXECUTIVE SUMMARY" in text
        assert "|---" not in text


class TestCharactersHelveticaCannotDraw:
    """The model writes non-breaking hyphens and narrow spaces. Helvetica's
    WinAnsi encoding has neither, and reportlab draws a filled black box for
    each -- "hyper-local" arrived as "hyper[]local"."""

    def test_they_are_mapped_to_something_the_font_has(self):
        from report_pdf import _normalise_glyphs

        assert _normalise_glyphs("hyper‑local") == "hyper-local"
        assert _normalise_glyphs("96 %") == "96 %"
        assert _normalise_glyphs("opted‐in") == "opted-in"

    def test_the_exported_pdf_contains_no_box_characters(self, sample_report):
        sample_report["sections"]["ai_analysis"] = "A hyper‑local app at 96 % confidence."
        text = _pdf_text(build_report_pdf(sample_report, "2026-08-23"))
        assert "hyper-local" in text
        assert "‑" not in text


def _pdf_text(data: bytes) -> str:
    """Read the rendered page text back, which is the only way to assert on
    what a reader actually sees."""
    import io

    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(io.BytesIO(data))
    return "\n".join(page.get_textpage().get_text_range() for page in document)
