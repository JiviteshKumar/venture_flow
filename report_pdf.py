"""PDF rendering of a due-diligence report.

Content comes from `report_document.build_report_blocks()`, the same function
`report_docx.py` and `report_markdown.py` render, so the three exports cannot
disagree about what the analysis found. This file is only the reportlab half.

Two things here are not decoration, and both were visible in an exported memo:

  * The model writes Markdown. Until `report_document.memo_blocks` parsed it,
    a claim-verification table reached the page as `| ... | ... |` lines and
    every heading carried its asterisks.

  * Helvetica is a Type 1 font with WinAnsi encoding, and the model's prose is
    full of characters outside it -- a non-breaking hyphen in "hyper-local", a
    narrow no-break space in "96 %". reportlab draws a filled black box for
    each one, so an otherwise sound memo read as though it had been corrupted.
    `_normalise_glyphs` maps them to the nearest character the font has.
"""
from __future__ import annotations

import io
import re
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (ListFlowable, ListItem, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

from report_document import build_report_blocks

INK = colors.HexColor("#0B1120")
MUTED = colors.HexColor("#5D6B7F")
FAINT = colors.HexColor("#94A3B8")
ACCENT = colors.HexColor("#1D4ED8")
RULE = colors.HexColor("#E2E8F0")
ZEBRA = colors.HexColor("#FAFBFF")
HEAD_BG = colors.HexColor("#F1F5F9")

RECOMMENDATION_COLORS = {
    "INVEST": colors.HexColor("#0EA66A"),
    "PASS": colors.HexColor("#D93025"),
    "NEEDS MORE DILIGENCE": colors.HexColor("#C47A0A"),
}

CONTENT_WIDTH = 7.0 * inch

# Characters the model emits that Helvetica cannot draw. Mapped rather than
# dropped: a hyphen that renders is worth more than a typographically perfect
# one that does not.
_GLYPH_FIXES = {
    "‐": "-", "‑": "-", "‒": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ",
    "​": "", "⁄": "/", "⁃": "-",
}

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def _styles():
    base = getSampleStyleSheet()
    base.add(ParagraphStyle("VFTitle", parent=base["Title"], fontSize=21, leading=25,
                            alignment=0, textColor=INK, spaceAfter=2))
    base.add(ParagraphStyle("VFMeta", parent=base["Normal"], fontSize=8.8, leading=12,
                            textColor=MUTED))
    base.add(ParagraphStyle("VFSection", parent=base["Heading2"], fontSize=12.5, leading=16,
                            spaceBefore=17, spaceAfter=5, textColor=ACCENT))
    # Explicitly non-italic: Heading3 inherits an italic face, which set the
    # memo's own section titles in italic bold and read as emphasis rather than
    # structure.
    base.add(ParagraphStyle("VFSub", parent=base["Heading3"], fontSize=10.5, leading=14,
                            fontName="Helvetica-Bold", spaceBefore=12, spaceAfter=4,
                            textColor=INK))
    base.add(ParagraphStyle("VFBody", parent=base["Normal"], fontSize=9.6, leading=14.2,
                            textColor=INK, spaceAfter=6))
    base.add(ParagraphStyle("VFCaveat", parent=base["Normal"], fontSize=8, leading=11.5,
                            textColor=FAINT))
    base.add(ParagraphStyle("VFCell", parent=base["Normal"], fontSize=8.4, leading=11.6,
                            textColor=INK))
    base.add(ParagraphStyle("VFCellHead", parent=base["Normal"], fontSize=8, leading=11,
                            fontName="Helvetica-Bold", textColor=MUTED))
    base.add(ParagraphStyle("VFScore", parent=base["Normal"], fontSize=19, leading=23,
                            fontName="Helvetica-Bold", textColor=INK))
    base.add(ParagraphStyle("VFVerdict", parent=base["Normal"], fontSize=11, leading=15,
                            fontName="Helvetica-Bold", textColor=INK))
    base.add(ParagraphStyle("VFCentered", parent=base["Normal"], alignment=TA_CENTER))
    return base


def _normalise_glyphs(text: str) -> str:
    for bad, good in _GLYPH_FIXES.items():
        text = text.replace(bad, good)
    return text


def _escape(text: str) -> str:
    """reportlab's Paragraph parses its input as mini-HTML, so a stray '&' or
    '<' in LLM-authored text raises rather than rendering."""
    return (
        _normalise_glyphs(str(text))
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _inline(text: str) -> str:
    """Escaped text with Markdown emphasis turned into reportlab's markup.

    Applied after escaping, so `**` in the source becomes bold while a literal
    `<b>` typed by the model stays visible text.
    """
    return _BOLD.sub(r"<b>\1</b>", _escape(text))


def _bullet_list(items: list[str], styles) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(_inline(item), styles["VFBody"]), leftIndent=14)
         for item in items or ["None identified."]],
        bulletType="bullet", bulletFontSize=8, bulletOffsetY=-1,
        leftIndent=16, spaceBefore=2, spaceAfter=6,
    )


def _summary_card(block: dict[str, Any], styles) -> Table:
    """The headline three, set as a card rather than a grid.

    It is the first thing on the page and the only part most readers look at;
    giving the score the same 8pt cell as a comparables row buried it.
    """
    score, recommendation, risk = (list(block["rows"][0]) + ["", "", ""])[:3]
    verdict_color = RECOMMENDATION_COLORS.get(str(recommendation).upper(), INK)

    labels = [Paragraph(_escape(name.upper()), styles["VFCellHead"]) for name in block["header"]]
    values = [
        Paragraph(_escape(score), styles["VFScore"]),
        Paragraph(f'<font color="#{verdict_color.hexval()[2:]}">{_escape(recommendation)}</font>',
                  styles["VFVerdict"]),
        Paragraph(_escape(risk), styles["VFVerdict"]),
    ]
    table = Table([labels, values], colWidths=[CONTENT_WIDTH / 3] * 3)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HEAD_BG),
        ("LINEABOVE", (0, 0), (-1, 0), 2, ACCENT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 11),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    return table


def _table(block: dict[str, Any], styles) -> Table:
    header = [Paragraph(_inline(cell), styles["VFCellHead"]) for cell in block["header"]]
    body = [[Paragraph(_inline(cell), styles["VFCell"]) for cell in row] for row in block["rows"]]
    width = CONTENT_WIDTH / max(1, len(block["header"]))
    table = Table([header, *body], colWidths=[width] * len(block["header"]), repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -2), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]
    for index in range(1, len(body) + 1):
        if index % 2 == 0:
            style.append(("BACKGROUND", (0, index), (-1, index), ZEBRA))
    table.setStyle(TableStyle(style))
    return table


def _page_furniture(company: str):
    """A footer on every page: which company, and where you are in the memo.

    A printed report loses its filename, and an IC memo gets read as loose
    pages, so the page has to say what it belongs to.
    """
    label = _normalise_glyphs(str(company or "VentureFlow"))

    def draw(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(0.75 * inch, 0.62 * inch, 8.0 * inch, 0.62 * inch)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(FAINT)
        canvas.drawString(0.75 * inch, 0.46 * inch, f"VentureFlow diligence - {label}")
        canvas.drawRightString(8.0 * inch, 0.46 * inch, str(canvas.getPageNumber()))
        canvas.restoreState()

    return draw


def build_report_pdf(report: dict[str, Any], generated_on: str) -> bytes:
    """PDF bytes for a report dict shaped like the API's DiligenceResponse
    (or the equivalent raw_output)."""
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=0.7 * inch, bottomMargin=0.85 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        title=f"VentureFlow diligence - {report.get('company', 'report')}",
        author="VentureFlow",
    )

    story = []
    for block in build_report_blocks(report, generated_on):
        kind = block["kind"]
        if kind == "title":
            story.append(Paragraph(_escape(block["text"]), styles["VFTitle"]))
        elif kind == "meta":
            story.append(Paragraph(_escape(block["text"]), styles["VFMeta"]))
            story.append(Spacer(1, 12))
        elif kind == "heading":
            story.append(Paragraph(_escape(block["text"]), styles["VFSection"]))
        elif kind == "subheading":
            story.append(Paragraph(_inline(block["text"]), styles["VFSub"]))
        elif kind == "text":
            story.append(Paragraph(_inline(block["text"]).replace("\n", "<br/>"), styles["VFBody"]))
        elif kind == "bullets":
            story.append(_bullet_list(block["items"], styles))
        elif kind == "table":
            story.append(Spacer(1, 2))
            story.append(_summary_card(block, styles) if block.get("role") == "summary"
                         else _table(block, styles))
            story.append(Spacer(1, 8))
        elif kind == "caveat":
            story.append(Spacer(1, 4))
            story.append(Paragraph(_escape(block["text"]), styles["VFCaveat"]))
            story.append(Spacer(1, 4))

    furniture = _page_furniture(report.get("company", ""))
    doc.build(story, onFirstPage=furniture, onLaterPages=furniture)
    return buffer.getvalue()
