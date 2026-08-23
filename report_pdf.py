"""PDF rendering of a due-diligence report.

This file used to own both the report's content and its reportlab drawing. The
content moved to `report_document.build_report_blocks()` when Word and Markdown
export were added, so that all three formats describe the same analysis instead
of drifting apart section by section. What is left here is only the reportlab
half: blocks in, PDF bytes out.
"""
from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from report_document import build_report_blocks

RECOMMENDATION_COLORS = {
    "INVEST": colors.HexColor("#0EA66A"),
    "PASS": colors.HexColor("#D93025"),
    "NEEDS MORE DILIGENCE": colors.HexColor("#C47A0A"),
}


def _styles():
    base = getSampleStyleSheet()
    base.add(ParagraphStyle("VFTitle", parent=base["Title"], fontSize=20, spaceAfter=4))
    base.add(ParagraphStyle("VFMeta", parent=base["Normal"], fontSize=9, textColor=colors.HexColor("#4A5568")))
    base.add(ParagraphStyle("VFSection", parent=base["Heading2"], fontSize=13, spaceBefore=16, spaceAfter=6, textColor=colors.HexColor("#0B1120")))
    base.add(ParagraphStyle("VFBody", parent=base["Normal"], fontSize=10, leading=14))
    base.add(ParagraphStyle("VFCaveat", parent=base["Normal"], fontSize=8, leading=11, textColor=colors.HexColor("#94A3B8")))
    base.add(ParagraphStyle("VFCell", parent=base["Normal"], fontSize=8.5, leading=11))
    base.add(ParagraphStyle("VFCellHead", parent=base["Normal"], fontSize=8.5, leading=11, fontName="Helvetica-Bold"))
    base.add(ParagraphStyle("VFCentered", parent=base["Normal"], alignment=TA_CENTER))
    return base


def _escape(text: str) -> str:
    """reportlab's Paragraph parses its input as mini-HTML, so a stray '&' or
    '<' in LLM-authored text raises rather than rendering. The '·' separator
    this codebase uses in meta lines is fine; the ampersand in a company name
    is not."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _bullet_list(items: list[str], styles) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(_escape(item), styles["VFBody"])) for item in items or ["None identified."]],
        bulletType="bullet", leftIndent=14,
    )


def _table(block: dict[str, Any], styles) -> Table:
    header = [Paragraph(_escape(cell), styles["VFCellHead"]) for cell in block["header"]]
    body = [[Paragraph(_escape(cell), styles["VFCell"]) for cell in row] for row in block["rows"]]
    width = 6.5 * inch / max(1, len(block["header"]))
    table = Table([header, *body], colWidths=[width] * len(block["header"]))
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F7F8FA")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def build_report_pdf(report: dict[str, Any], generated_on: str) -> bytes:
    """PDF bytes for a report dict shaped like the API's DiligenceResponse
    (or the equivalent raw_output)."""
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
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
        elif kind == "text":
            story.append(Paragraph(_escape(block["text"]).replace("\n", "<br/>"), styles["VFBody"]))
        elif kind == "bullets":
            story.append(_bullet_list(block["items"], styles))
        elif kind == "table":
            story.append(_table(block, styles))
        elif kind == "caveat":
            story.append(Spacer(1, 6))
            story.append(Paragraph(_escape(block["text"]), styles["VFCaveat"]))

    doc.build(story)
    return buffer.getvalue()
