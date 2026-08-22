"""Proper PDF report export -- replaces the frontend's plain-text download
(Analysis.tsx's `exportReport`) with a real PDF built server-side from the
persisted report, so what a VC puts in an IC deck isn't a .txt file.
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
    base.add(ParagraphStyle("VFCentered", parent=base["Normal"], alignment=TA_CENTER))
    return base


def _bullet_list(items: list[str], styles) -> ListFlowable:
    if not items:
        items = ["None identified."]
    return ListFlowable(
        [ListItem(Paragraph(item, styles["VFBody"])) for item in items],
        bulletType="bullet", leftIndent=14,
    )


def build_report_pdf(report: dict[str, Any], generated_on: str) -> bytes:
    """Builds a PDF from a report dict shaped like the API's DiligenceResponse
    (or the equivalent raw_output). Never assumes optional sections are
    present -- every section is read with .get() and rendered only if it has
    data, matching the same "degrade, don't crash" pattern used everywhere
    else `sections` is read in this codebase."""
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )
    sections = report.get("sections", {}) or {}
    story = []

    story.append(Paragraph("VentureFlow Due Diligence Report", styles["VFTitle"]))
    story.append(Paragraph(f"{report.get('company', 'Unknown Company')} &middot; Generated {generated_on}", styles["VFMeta"]))
    story.append(Spacer(1, 12))

    score = report.get("final_score", 0)
    recommendation = report.get("recommendation", "NEEDS MORE DILIGENCE")
    risk_level = report.get("risk_level", "UNKNOWN")
    rec_color = RECOMMENDATION_COLORS.get(recommendation, colors.HexColor("#4A5568"))

    summary_table = Table(
        [["Overall Score", "Recommendation", "Risk Level"],
         [f"{score}/100", recommendation, risk_level]],
        colWidths=[2.1 * inch] * 3,
    )
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F7F8FA")),
        ("TEXTCOLOR", (1, 1), (1, 1), rec_color),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, 1), 13),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_table)

    story.append(Paragraph("Investment Memo", styles["VFSection"]))
    story.append(Paragraph((sections.get("ai_analysis") or "No AI memo was generated.").replace("\n", "<br/>"), styles["VFBody"]))

    claims = sections.get("claims", {})
    if claims:
        story.append(Paragraph("Claim Verification", styles["VFSection"]))
        story.append(Paragraph(
            f"{claims.get('checked', 0)} claim(s) checked &middot; "
            f"{claims.get('supported', 0)} supported &middot; "
            f"{claims.get('refuted', 0)} refuted &middot; "
            f"{claims.get('uncertain', 0)} uncertain",
            styles["VFBody"],
        ))

    story.append(Paragraph("Key Concerns", styles["VFSection"]))
    story.append(_bullet_list(report.get("key_concerns", []), styles))

    story.append(Paragraph("Red Flags", styles["VFSection"]))
    story.append(_bullet_list(report.get("red_flags", []), styles))

    story.append(Paragraph("Positive Factors", styles["VFSection"]))
    story.append(_bullet_list(report.get("positive_factors", []), styles))

    comparables = sections.get("market_comparables", {})
    if comparables.get("available"):
        story.append(Paragraph("Comparable Companies", styles["VFSection"]))
        rows = [["Company", "Industry", "Stage", "Outcome", "Similarity"]]
        for comp in comparables.get("comparables", [])[:5]:
            rows.append([
                comp.get("name", ""), comp.get("industry", ""), comp.get("stage", ""),
                comp.get("outcome", ""), f"{comp.get('similarity', 0):.2f}",
            ])
        comp_table = Table(rows, colWidths=[1.5 * inch, 1.1 * inch, 1 * inch, 1.2 * inch, 0.9 * inch])
        comp_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F7F8FA")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ]))
        story.append(comp_table)
        story.append(Paragraph(comparables.get("caveat", ""), styles["VFCaveat"]))

    outcome_model = sections.get("ml_outcome_model", {})
    if outcome_model.get("available"):
        story.append(Paragraph("Outcome Model Signal", styles["VFSection"]))
        story.append(Paragraph(
            f"Probability of survival/exit: {outcome_model.get('probability_survives_or_exits', 0):.0%} "
            f"({outcome_model.get('band', 'n/a')}) &middot; model test ROC-AUC {outcome_model.get('model_test_auc', 'n/a')}",
            styles["VFBody"],
        ))
        story.append(Paragraph(outcome_model.get("caveat", ""), styles["VFCaveat"]))

    technical_score = sections.get("technical_score", {})
    if technical_score.get("available"):
        story.append(Paragraph("Technical/GitHub Score", styles["VFSection"]))
        story.append(Paragraph(f"{technical_score.get('score', 0)}/100 for {technical_score.get('repo', '')}", styles["VFBody"]))

    story.append(Spacer(1, 16))
    story.append(Paragraph(
        "Generated by VentureFlow AI. This report combines evidence-grounded LLM "
        "analysis with additional trained/rule-based signals where available; it is "
        "not a substitute for independent due diligence.",
        styles["VFCaveat"],
    ))

    doc.build(story)
    return buffer.getvalue()
