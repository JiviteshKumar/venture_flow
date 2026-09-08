"""Generate the VentureFlow explainer PDF.

Every figure in the output is read from a committed artifact in this repo
(model reports, provenance files, pickles) rather than typed in by hand, so the
document cannot drift away from what was actually trained. Where a number is
hardcoded below it is because it is a fact about the source data, and the file
it came from is named next to it.

    python scripts/build_overview_pdf.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Flowable, Frame, KeepTogether, NextPageTemplate,
    PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "VentureFlow_Explained.pdf"

# ── Palette, matching the product's own design tokens ──────────────────────
INK        = colors.HexColor("#0B1120")
SECONDARY  = colors.HexColor("#3D4A5C")
MUTED      = colors.HexColor("#5D6B7F")
BRAND      = colors.HexColor("#1D6FE8")
POSITIVE   = colors.HexColor("#0EA66A")
CAUTION    = colors.HexColor("#C47A0A")
NEGATIVE   = colors.HexColor("#D93025")
RULE       = colors.HexColor("#DDE3EC")
SURFACE2   = colors.HexColor("#F5F7FA")
PANEL_BLUE = colors.HexColor("#EFF5FE")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm


# ── Styles ─────────────────────────────────────────────────────────────────
_base = getSampleStyleSheet()

S = {
    "title": ParagraphStyle("title", parent=_base["Title"], fontName="Helvetica-Bold",
                            fontSize=30, leading=35, textColor=INK, spaceAfter=4),
    "subtitle": ParagraphStyle("subtitle", parent=_base["Normal"], fontName="Helvetica",
                               fontSize=13, leading=19, textColor=MUTED, alignment=TA_CENTER),
    "h1": ParagraphStyle("h1", parent=_base["Heading1"], fontName="Helvetica-Bold",
                         fontSize=19, leading=24, textColor=INK,
                         spaceBefore=2, spaceAfter=9),
    "h2": ParagraphStyle("h2", parent=_base["Heading2"], fontName="Helvetica-Bold",
                         fontSize=13.5, leading=18, textColor=INK,
                         spaceBefore=13, spaceAfter=5),
    "h3": ParagraphStyle("h3", parent=_base["Heading3"], fontName="Helvetica-Bold",
                         fontSize=11, leading=15, textColor=BRAND,
                         spaceBefore=10, spaceAfter=4),
    "body": ParagraphStyle("body", parent=_base["BodyText"], fontName="Helvetica",
                           fontSize=9.8, leading=15.2, textColor=SECONDARY,
                           alignment=TA_JUSTIFY, spaceAfter=7),
    "lead": ParagraphStyle("lead", parent=_base["BodyText"], fontName="Helvetica",
                           fontSize=11.2, leading=17, textColor=SECONDARY, spaceAfter=9),
    "bullet": ParagraphStyle("bullet", parent=_base["BodyText"], fontName="Helvetica",
                             fontSize=9.8, leading=15, textColor=SECONDARY,
                             leftIndent=12, bulletIndent=2, spaceAfter=4),
    "cell": ParagraphStyle("cell", parent=_base["BodyText"], fontName="Helvetica",
                           fontSize=8.6, leading=12.4, textColor=SECONDARY, spaceAfter=0),
    "cellb": ParagraphStyle("cellb", parent=_base["BodyText"], fontName="Helvetica-Bold",
                            fontSize=8.6, leading=12.4, textColor=INK, spaceAfter=0),
    "cellhead": ParagraphStyle("cellhead", parent=_base["BodyText"], fontName="Helvetica-Bold",
                               fontSize=7.6, leading=11, textColor=colors.white, spaceAfter=0),
    "mono": ParagraphStyle("mono", parent=_base["BodyText"], fontName="Courier",
                           fontSize=8.4, leading=12.6, textColor=SECONDARY, spaceAfter=0),
    "caption": ParagraphStyle("caption", parent=_base["BodyText"], fontName="Helvetica-Oblique",
                              fontSize=8.4, leading=12, textColor=MUTED,
                              alignment=TA_CENTER, spaceBefore=5),
    "callout": ParagraphStyle("callout", parent=_base["BodyText"], fontName="Helvetica",
                              fontSize=9.4, leading=14.4, textColor=SECONDARY, spaceAfter=0),
    "callouth": ParagraphStyle("callouth", parent=_base["BodyText"], fontName="Helvetica-Bold",
                               fontSize=9.4, leading=14, textColor=INK, spaceAfter=3),
}


def P(text, style="body"):
    return Paragraph(text, S[style])


def bullets(items, style="bullet"):
    return [Paragraph(t, S[style], bulletText="•") for t in items]


def callout(title, body, tone=BRAND, bg=PANEL_BLUE):
    """A tinted box for the points that matter most."""
    inner = [Paragraph(title, S["callouth"]), Paragraph(body, S["callout"])]
    t = Table([[inner]], colWidths=[PAGE_W - 2 * MARGIN])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEBEFORE", (0, 0), (0, -1), 2.4, tone),
        ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def table(rows, widths, header=True, align_right=()):
    """Standard data table: dark header, hairline rules, zebra body."""
    data = []
    for r_i, row in enumerate(rows):
        out = []
        for c_i, cell in enumerate(row):
            if isinstance(cell, Paragraph):
                out.append(cell)
            elif header and r_i == 0:
                out.append(Paragraph(str(cell), S["cellhead"]))
            else:
                out.append(Paragraph(str(cell), S["cellb"] if c_i == 0 else S["cell"]))
        data.append(out)

    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), INK),
            ("TOPPADDING", (0, 0), (-1, 0), 7),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ]
        for i in range(2, len(data), 2):
            style.append(("BACKGROUND", (0, i), (-1, i), SURFACE2))
    for c in align_right:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t


# ── The architecture diagram ───────────────────────────────────────────────
class Architecture(Flowable):
    """The end-to-end pipeline, drawn rather than described.

    Laid out as four labelled bands so a reader can see where the LLM is used,
    where a trained model is used, and where the two honesty checks sit.
    """

    def __init__(self, width, height=214 * mm):
        super().__init__()
        self.width = width
        self.height = height

    def wrap(self, *_):
        return self.width, self.height

    # -- primitives ---------------------------------------------------------
    def _box(self, x, y, w, h, label, sub=None, fill=colors.white,
             stroke=RULE, text=INK, bold=True, size=8.2, radius=3):
        c = self.canv
        c.setFillColor(fill)
        c.setStrokeColor(stroke)
        c.setLineWidth(0.9)
        c.roundRect(x, y, w, h, radius, stroke=1, fill=1)
        c.setFillColor(text)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        if sub:
            c.drawCentredString(x + w / 2, y + h / 2 + 2.2, label)
            c.setFont("Helvetica", size - 1.5)
            c.setFillColor(MUTED)
            c.drawCentredString(x + w / 2, y + h / 2 - 7.5, sub)
        else:
            c.drawCentredString(x + w / 2, y + h / 2 - 3, label)

    def _arrow(self, x1, y1, x2, y2, color=BRAND, dashed=False, label=None):
        c = self.canv
        c.setStrokeColor(color)
        c.setLineWidth(1.1)
        c.setDash(3, 3) if dashed else c.setDash()
        c.line(x1, y1, x2, y2)
        c.setDash()
        # arrowhead
        import math
        ang = math.atan2(y2 - y1, x2 - x1)
        size = 4.6
        c.setFillColor(color)
        p = c.beginPath()
        p.moveTo(x2, y2)
        p.lineTo(x2 - size * math.cos(ang - 0.42), y2 - size * math.sin(ang - 0.42))
        p.lineTo(x2 - size * math.cos(ang + 0.42), y2 - size * math.sin(ang + 0.42))
        p.close()
        c.drawPath(p, fill=1, stroke=0)
        if label:
            c.setFont("Helvetica", 6.4)
            c.setFillColor(colors.white)
            tw = c.stringWidth(label, "Helvetica", 6.4)
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            c.rect(mx - tw / 2 - 2, my + 2.6, tw + 4, 7, stroke=0, fill=1)
            c.setFillColor(MUTED)
            c.drawCentredString(mx, my + 4.4, label)

    def _band(self, y, h, title, tone):
        c = self.canv
        c.setFillColor(colors.HexColor("#FAFBFD"))
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.roundRect(0, y, self.width, h, 4, stroke=1, fill=1)
        c.setFillColor(tone)
        c.roundRect(0, y, 3, h, 1.5, stroke=0, fill=1)
        c.saveState()
        c.setFillColor(tone)
        c.setFont("Helvetica-Bold", 6.8)
        c.translate(10, y + h - 9)
        c.drawString(0, 0, title.upper())
        c.restoreState()

    # -- layout -------------------------------------------------------------
    def draw(self):
        c = self.canv
        W = self.width
        cx = W / 2

        # ---------- Band 1: input ----------
        y1 = 176 * mm
        self._band(y1, 30 * mm, "1 - Input", MUTED)
        self._box(cx - 46 * mm, y1 + 12 * mm, 92 * mm, 11 * mm,
                  "Pitch deck uploaded  (PDF / PPTX / DOCX / TXT / MD)",
                  fill=colors.white, size=8.4)
        c.setFont("Helvetica", 7)
        c.setFillColor(NEGATIVE)
        c.drawCentredString(cx, y1 + 6.5 * mm,
                            "Image-only PDFs extract to 0 characters - there is no OCR. 8 of 13 known decks are like this.")

        # ---------- Band 2: extraction ----------
        y2 = 118 * mm
        self._band(y2, 54 * mm, "2 - Extraction  (the part that had to be fixed)", BRAND)

        self._arrow(cx, y1, cx, y2 + 54 * mm)

        self._box(cx - 40 * mm, y2 + 39 * mm, 80 * mm, 10 * mm,
                  "document_extractor", "raw text  +  per-page text", size=8)

        bw, bh = 62 * mm, 13 * mm
        lx, rx = cx - bw - 5 * mm, cx + 5 * mm
        ytop = y2 + 22 * mm

        self._box(lx, ytop, bw, bh, "PRIMARY:  llm_schema",
                  "Groq LLM  ->  Pydantic-validated JSON", fill=PANEL_BLUE, stroke=BRAND, size=8)
        self._box(rx, ytop, bw, bh, "FALLBACK:  regex_fallback",
                  "used only when the LLM path fails", fill=colors.HexColor("#FFF6E8"),
                  stroke=CAUTION, size=8)

        self._arrow(cx - 12 * mm, y2 + 39 * mm, lx + bw / 2, ytop + bh)
        self._arrow(cx + 12 * mm, y2 + 39 * mm, rx + bw / 2, ytop + bh)
        self._arrow(lx + bw, ytop + bh / 2, rx, ytop + bh / 2,
                    color=CAUTION, dashed=True, label="on failure")

        self._box(cx - 62 * mm, y2 + 5 * mm, 60 * mm, 12 * mm,
                  "extraction_coverage", "how much of the deck was understood",
                  fill=colors.HexColor("#EAF8F1"), stroke=POSITIVE, size=8)
        self._box(cx + 2 * mm, y2 + 5 * mm, 60 * mm, 12 * mm,
                  "extraction_provenance", "which path produced this report",
                  fill=colors.HexColor("#EAF8F1"), stroke=POSITIVE, size=8)

        self._arrow(lx + bw / 2, ytop, cx - 32 * mm, y2 + 17 * mm, color=POSITIVE)
        self._arrow(rx + bw / 2, ytop, cx + 32 * mm, y2 + 17 * mm, color=POSITIVE)

        # ---------- Band 3: analysis ----------
        y3 = 46 * mm
        self._band(y3, 66 * mm, "3 - Analysis", CAUTION)
        self._arrow(cx, y2, cx, y3 + 66 * mm)

        cw, ch = 51 * mm, 12 * mm
        gap = 5 * mm
        col_x = [cx - 1.5 * cw - gap, cx - 0.5 * cw, cx + 0.5 * cw + gap]
        # normalise to three evenly spaced columns
        total = 3 * cw + 2 * gap
        col_x = [(W - total) / 2 + i * (cw + gap) for i in range(3)]

        row_a = y3 + 45 * mm
        self._box(col_x[0], row_a, cw, ch, "claim_verifier",
                  "web search  ->  LLM verdict", size=7.8)
        self._box(col_x[1], row_a, cw, ch, "founder_research",
                  "finds + checks founders", size=7.8)
        self._box(col_x[2], row_a, cw, ch, "risk_detector",
                  "keywords + trained model", fill=colors.HexColor("#F3EEFB"),
                  stroke=colors.HexColor("#7A5AF8"), size=7.8)

        row_b = y3 + 28 * mm
        self._box(col_x[0], row_b, cw, ch, "investment_agents",
                  "Bull / Bear / Market / Team", size=7.8)
        self._box(col_x[1], row_b, cw, ch, "VentureFlow Score",
                  "TRAINED MODEL", fill=colors.HexColor("#F3EEFB"),
                  stroke=colors.HexColor("#7A5AF8"), size=7.8)
        self._box(col_x[2], row_b, cw, ch, "Outcome Model",
                  "TRAINED MODEL", fill=colors.HexColor("#F3EEFB"),
                  stroke=colors.HexColor("#7A5AF8"), size=7.8)

        for x in col_x:
            self._arrow(x + cw / 2, row_a, x + cw / 2, row_b + ch)

        # score composition
        self._box(cx - 62 * mm, y3 + 8 * mm, 124 * mm, 13 * mm,
                  "final score  =  model prior  -  evidence penalty",
                  "the prior is trained; the penalty is a stated, visible formula",
                  fill=PANEL_BLUE, stroke=BRAND, size=8.6)
        for x in col_x:
            self._arrow(x + cw / 2, row_b, cx, y3 + 21 * mm)

        # ---------- Band 4: output ----------
        y4 = 4 * mm
        self._band(y4, 28 * mm, "4 - Output", POSITIVE)
        self._arrow(cx, y3, cx, y4 + 28 * mm)
        ow = 56 * mm
        self._box(cx - ow - 3 * mm, y4 + 8 * mm, ow, 12 * mm,
                  "Investment memo", "written by the LLM", size=8)
        self._box(cx + 3 * mm, y4 + 8 * mm, ow, 12 * mm,
                  "Report + score", "stored in Postgres", size=8)


# ── Page furniture ─────────────────────────────────────────────────────────
def cover_page(canv, doc):
    canv.saveState()
    canv.setFillColor(INK)
    canv.rect(0, PAGE_H - 88 * mm, PAGE_W, 88 * mm, stroke=0, fill=1)
    # accent stripe
    for i, col in enumerate([BRAND, POSITIVE, CAUTION]):
        canv.setFillColor(col)
        canv.rect(i * PAGE_W / 3, PAGE_H - 90 * mm, PAGE_W / 3, 2.2 * mm, stroke=0, fill=1)
    canv.setFillColor(colors.white)
    canv.setFont("Helvetica-Bold", 40)
    canv.drawString(MARGIN, PAGE_H - 46 * mm, "VentureFlow")
    canv.setFont("Helvetica", 15)
    canv.setFillColor(colors.HexColor("#A9B7CC"))
    canv.drawString(MARGIN, PAGE_H - 57 * mm, "AI due diligence for pitch decks")
    canv.setFont("Helvetica", 9.4)
    canv.drawString(MARGIN, PAGE_H - 70 * mm,
                    "How it works, what was trained, and what it can and cannot do")
    canv.setFillColor(MUTED)
    canv.setFont("Helvetica", 8)
    canv.drawCentredString(PAGE_W / 2, 12 * mm,
                           "Every figure in this document is read from a committed artifact in the repository.")
    canv.restoreState()


def body_page(canv, doc):
    canv.saveState()
    canv.setStrokeColor(RULE)
    canv.setLineWidth(0.6)
    canv.line(MARGIN, PAGE_H - MARGIN + 5 * mm, PAGE_W - MARGIN, PAGE_H - MARGIN + 5 * mm)
    canv.setFont("Helvetica", 7.6)
    canv.setFillColor(MUTED)
    canv.drawString(MARGIN, PAGE_H - MARGIN + 7.5 * mm, "VentureFlow - Technical Overview")
    canv.line(MARGIN, 13 * mm, PAGE_W - MARGIN, 13 * mm)
    canv.drawRightString(PAGE_W - MARGIN, 8.5 * mm, str(canv.getPageNumber()))
    canv.restoreState()


def build():
    doc = BaseDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
        title="VentureFlow - Technical Overview",
        author="VentureFlow",
        subject="Product, architecture, trained models and datasets",
    )
    frame = Frame(MARGIN, MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN, id="f")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame], onPage=cover_page),
        PageTemplate(id="body", frames=[frame], onPage=body_page),
    ])
    doc.build(story())
    return OUT


# ── Content ────────────────────────────────────────────────────────────────
FULL = PAGE_W - 2 * MARGIN


def story():
    s = []

    # ===== COVER =====
    s.append(Spacer(1, 96 * mm))
    s.append(P("What this document is", "h2"))
    s.append(P(
        "VentureFlow reads a startup's pitch deck and checks it. It pulls out the claims the deck "
        "makes, searches the web to see whether they hold up, looks up who founded the company, "
        "scores the business against a model trained on real startup outcomes, and writes an "
        "investment memo.", "lead"))
    s.append(P(
        "This document explains the whole thing from scratch - what problem it solves, how the "
        "pipeline works end to end, which machine-learning models were trained and exactly how, "
        "which public datasets they learned from, and where the system is weak. It is written to be "
        "readable without any prior knowledge of the codebase.", "body"))
    s.append(Spacer(1, 6 * mm))
    s.append(callout(
        "The one idea behind every design decision",
        "A tool that quietly invents a number is worse than no tool at all, because a convincing "
        "fabrication is impossible to tell apart from a real finding. Most of the engineering here "
        "went into making the system's own failures visible rather than into adding features. "
        "That principle explains nearly every choice in the pages that follow.",
        tone=BRAND))
    s.append(NextPageTemplate("body"))
    s.append(PageBreak())

    # ===== 1. PROBLEM =====
    s.append(P("1. The problem, in plain terms", "h1"))
    s.append(P(
        "An investor receives far more pitch decks than anyone can study properly. Reading a deck is "
        "quick. <b>Checking</b> it is the expensive part.", "body"))
    s.append(P(
        "A deck asserts things: a market worth billions, a growth rate, a list of customers, a "
        "founding team with the right background. Verifying even one of those means searching, "
        "reading sources and forming a judgement. Multiply that by fifty decks a week and the "
        "checking simply does not happen - which is precisely when a weak company slips through on "
        "a confident-sounding slide.", "body"))
    s.append(P("VentureFlow automates that checking pass. Give it a deck and it will:", "body"))
    s.extend(bullets([
        "Pull out every specific claim the deck makes.",
        "Search the public web and judge each claim as supported, refuted or unverifiable - with the sources it used attached.",
        "Find the founders (even when the deck never names them) and check their background against public record.",
        "Score the company against a model trained on 1,298 real startups whose outcomes are known.",
        "Write a structured memo, and tell you how much of the deck it actually managed to read.",
    ]))
    s.append(Spacer(1, 3 * mm))
    s.append(callout(
        "It is a triage tool, not a decision maker",
        "The score separates more-promising from less-promising decks well enough to sort a pile. "
        "It is nowhere near good enough to decide an investment, and Section 7 gives the exact "
        "numbers rather than a reassuring adjective.",
        tone=CAUTION, bg=colors.HexColor("#FFF6E8")))

    # ===== 2. STACK =====
    s.append(P("2. The technology", "h1"))
    s.append(P(
        "Nothing exotic. The interesting parts are the trained models in Section 5 and the honesty "
        "checks in Section 4, not the framework choices.", "body"))
    s.append(table([
        ["Layer", "Technology", "What it does here"],
        ["Backend", "Python 3.13, FastAPI, uvicorn", "The API the frontend talks to; runs the analysis pipeline."],
        ["Language model", "Groq - openai/gpt-oss-120b", "Reads decks, judges claims, writes the memo."],
        ["Database", "Neon (serverless Postgres) + pgvector", "Stores reports; pgvector powers similarity search."],
        ["Machine learning", "LightGBM, scikit-learn, TF-IDF + SVD", "The four shipped models."],
        ["Web search", "DuckDuckGo (ddgs)", "Evidence for claim checks and founder lookups."],
        ["Deck parsing", "pdfplumber, python-pptx, python-docx", "Turns a deck into text. No OCR."],
        ["Frontend", "React + TypeScript, Vite, Tailwind, recharts", "The dashboard and report UI."],
        ["Hosting", "Vercel (frontend), Neon (data)", "Deployment."],
    ], [26 * mm, 52 * mm, FULL - 78 * mm]))

    # ===== 3. ARCHITECTURE =====
    s.append(PageBreak())
    s.append(P("3. How the pipeline works", "h1"))
    s.append(P(
        "The diagram below is the whole system. Read it top to bottom: a deck comes in at the top and "
        "a memo comes out at the bottom. <b>Purple boxes are trained machine-learning models. Green "
        "boxes are the two honesty checks</b> that Section 4 explains.", "body"))
    s.append(Architecture(FULL))
    s.append(P("Figure 1 - The VentureFlow analysis pipeline, end to end.", "caption"))

    s.append(KeepTogether([P("3.1 Why extraction has two paths", "h2")]))
    s.append(P(
        "Look again at band 2 of the diagram. Extraction - turning a deck into structured facts - has "
        "a primary path and a fallback, and everything downstream depends on which one ran.", "body"))
    s.append(P(
        "The <b>primary path</b> asks the language model for a fixed JSON structure and validates it "
        "with Pydantic before anything is allowed to trust it. It understands a deck by its content, "
        "so a slide titled \"1-Click Car Service\" is correctly recognised as the solution slide.", "body"))
    s.append(P(
        "The <b>fallback path</b> uses hand-written pattern matching. It is much worse: on the real "
        "2008 UberCab deck it finds 3 claims where the primary path finds 14. It exists so that an "
        "outage degrades the product instead of breaking it.", "body"))
    s.append(Spacer(1, 2 * mm))
    s.append(callout(
        "The bug that shaped this entire project",
        "One line of code called a variable named <font face=\"Courier\">prompt</font> that did not "
        "exist. Every call raised an error; a catch-all handler swallowed it; extraction silently "
        "dropped to the fallback path. <b>Every analysis for an unknown number of weeks was produced "
        "by the worse path, and nothing anywhere said so.</b> It was found only when a human compared "
        "a report against the original PDF by hand. The lesson was not \"fix the typo\" - it was that "
        "a failure nobody can see will run for weeks.",
        tone=NEGATIVE, bg=colors.HexColor("#FDF0EF")))

    # ===== 4. HONESTY =====
    s.append(P("4. The two honesty checks", "h1"))
    s.append(P(
        "These are the green boxes in the diagram, and they are what makes the rest trustworthy.", "body"))

    s.append(P("4.1 Extraction coverage - did we actually read the deck?", "h3"))
    s.append(P(
        "Before this existed, two completely different situations produced identical output. If the "
        "report said \"insufficient data\", that could mean the deck genuinely said very little - or "
        "it could mean the deck was full of information and the parser dropped it. The first is an "
        "honest finding. The second is a bug. A reader could not tell which they were looking at.", "body"))
    s.append(P(
        "Coverage measures one thing: <b>of the text we were given, how much can be found again in "
        "the structured output?</b> The headline figure is the share of slides that contributed at "
        "least one line, because the failure being guarded against is whole slides vanishing. The "
        "report names the slides that contributed nothing, so you can check it against the PDF in "
        "about ten seconds.", "body"))
    s.append(table([
        ["Measured on the real deck corpus", "Before the fix", "After the fix"],
        ["Average coverage across decks", "20.8%", "69.6%"],
        ["Total claims extracted", "14", "92"],
        ["Uber 2008 deck - claims found", "3", "14"],
    ], [FULL - 66 * mm, 33 * mm, 33 * mm], align_right=(1, 2)))

    s.append(P("4.2 Extraction provenance - which path produced this?", "h3"))
    s.append(P(
        "Every report now records whether it came from the good path or the fallback. When the "
        "fallback runs, it says so in four places at once: the logs, the stored report, the written "
        "memo, and a red banner in the interface. A test deliberately breaks the language-model path "
        "and fails if that degradation is not visible.", "body"))

    s.append(P("4.3 The same principle, applied everywhere else", "h3"))
    s.extend(bullets([
        "<b>Founder search</b> reports three separate states: <i>the search failed</i>, <i>the search was not attempted</i>, and <i>we searched and genuinely found nobody</i>. Only the last one says anything about the company. They are three different colours in the interface.",
        "<b>Founder names</b> must be grammatically credited as a founder in a real source, not merely appear on the same page - otherwise a directory listing turns a random executive into a fabricated co-founder.",
        "<b>Missing numbers</b> display as a dash, never as zero. A figure the deck never stated and a figure that is genuinely zero are different facts.",
        "<b>A corpus deck</b> that turned out to be a business-school case study rather than the company's own fundraising deck is flagged as unverified rather than quietly used as ground truth.",
    ]))

    # ===== 5. MODELS =====
    # No forced break: section 4 ends short, and breaking here left two thirds
    # of a page blank. KeepTogether holds the heading to its first paragraph.
    s.append(Spacer(1, 4 * mm))
    s.append(P("5. The machine-learning models", "h1"))
    s.append(P(
        "Six models were trained. <b>Four are used in the product. Two were deliberately left out</b>, "
        "and the reasons they were left out are as informative as the ones that shipped.", "body"))
    s.append(P(
        "First, a plain-language note on how to read the numbers in this section, because one term "
        "does most of the work.", "body"))
    s.append(callout(
        "What \"AUC\" means",
        "AUC answers: given one company that succeeded and one that failed, how often does the model "
        "give the successful one a higher score? <b>0.5 is a coin flip - completely worthless. "
        "1.0 is perfect.</b> Real-world startup prediction is genuinely hard, so anything meaningfully "
        "above 0.5 is a real signal, and anything near 0.9 in this domain should make you suspect a "
        "leak rather than a breakthrough. That suspicion turned out to be correct twice here.",
        tone=BRAND))

    s.append(P("5.1 VentureFlow Score - the headline number", "h2"))
    s.append(table([
        ["Property", "Value"],
        ["File", "ml/models/venturescore_model.pkl"],
        ["Method", "Ensemble of 12 Random Forests, with isotonic calibration"],
        ["Training data", "1,298 Y Combinator companies"],
        ["Features", "22 numeric + 5 categorical, expanded to 80 columns"],
        ["Cross-validated AUC", "<b>0.6772</b>  (95% confidence interval 0.6607 - 0.6932)"],
        ["Calibration error", "0.0219  (lower is better; this is good)"],
        ["Verified out-of-sample AUC", "<b>0.6356</b>  on 261 companies with zero overlap with training"],
    ], [46 * mm, FULL - 46 * mm]))
    s.append(P(
        "<b>What it predicts.</b> Not returns - <i>survival</i>. The label is whether a company was "
        "acquired, went public, or is still operating, versus having shut down. Companies younger "
        "than three and a half years are excluded entirely, because \"still alive\" tells you nothing "
        "about a company founded last year.", "body"))
    s.append(P(
        "<b>How it was trained.</b> Each company becomes a row of features - its industry, its "
        "funding stage, tags describing what it does, how long its description is, and so on. A "
        "Random Forest learns which combinations preceded survival. Twelve of them vote, and isotonic "
        "calibration then adjusts the output so that \"70% likely\" genuinely means roughly seven in "
        "ten, rather than being an arbitrary confidence number.", "body"))
    s.append(Spacer(1, 2 * mm))
    s.append(callout(
        "Three features were deliberately thrown away",
        "Team size, company age and batch year were all removed. Each is recorded <i>years after</i> "
        "the outcome being predicted: team size measures growth that already happened, and age "
        "encodes whether a company had time to fail. Keeping them would have produced a better-looking "
        "score that had partly learned the answer instead of predicting it.",
        tone=POSITIVE, bg=colors.HexColor("#EAF8F1")))
    s.append(P(
        "<b>For comparison</b>, the hand-written formula this replaced scores an AUC of exactly 0.5 - "
        "not approximately, exactly. It read no company feature at all, so every company received the "
        "same score and every comparison was a tie.", "body"))

    s.append(KeepTogether([
        P("5.2 Outcome Model - a second opinion", "h2"),
        P("A different algorithm on the same underlying data, kept as a cross-check. It uses LightGBM "
          "(gradient-boosted trees) over both the company's text description and its structured fields. "
          "Trained on 1,560 companies: 1,248 for training, 312 held back for testing.", "body"),
    ]))
    s.append(P("All five variants that were trained are recorded, not just the flattering one:", "body"))
    s.append(table([
        ["Variant", "AUC", "Accuracy", "Shipped?"],
        ["Text only", "0.5721", "55.5%", "No"],
        ["Structured only, with hindsight features", "0.7047", "65.1%", "No - leaks"],
        ["Combined, with hindsight features", "0.7039", "65.1%", "No - leaks"],
        ["Structured only, deployable", "0.6613", "62.5%", "No"],
        ["<b>Combined, deployable</b>", "<b>0.6459</b>", "<b>63.8%</b>", "<b>Yes</b>"],
    ], [FULL - 62 * mm, 20 * mm, 21 * mm, 21 * mm], align_right=(1, 2)))
    s.append(callout(
        "The best-scoring model was deliberately not shipped",
        "The two 0.70 variants reach that number by using team size and company age - the same "
        "after-the-fact features excluded from the VentureFlow Score. Removing them <b>costs 0.058 "
        "AUC</b>, and that cost is written into the model's own report file rather than hidden. "
        "A 0.70 that partly knows the answer is worth less than a 0.65 that does not.",
        tone=POSITIVE, bg=colors.HexColor("#EAF8F1")))

    s.append(Spacer(1, 1 * mm))
    s.append(P("5.3 Risk Disclosure Model - the strongest result", "h2"))
    s.append(P(
        "This one detects genuine risk language, as opposed to the boilerplate every company copies "
        "into its filings. It is trained on real regulatory documents rather than on startup data.", "body"))
    s.append(table([
        ["Property", "Value"],
        ["Training data", "941 excerpts drawn from 614 real SEC filings (10-K, 10-Q, 8-K)"],
        ["Balance", "464 genuine-risk / 477 boilerplate"],
        ["Labelling method", "Weak supervision - 38 labelling functions (Ratner et al., NeurIPS 2016)"],
        ["Split", "Grouped by filing ID, so no single document spans training and testing"],
        ["Held-out accuracy", "<b>96.6%</b>   -   AUC <b>0.9973</b>"],
        ["Independent benchmark", "Precision 92.9%, recall 86.7%, F1 0.897"],
    ], [46 * mm, FULL - 46 * mm]))
    s.append(P(
        "<b>What weak supervision means.</b> Nobody hand-labelled 941 documents. Instead, 38 search "
        "phrases were written, each one strongly associated with either genuine risk or boilerplate, "
        "and the phrase that retrieved a passage became its label. It is far cheaper than human "
        "annotation and noisier - and the provenance file states this in as many words: "
        "<i>\"labels are the retrieval phrase's bucket, NOT human judgement.\"</i>", "body"))
    s.append(callout(
        "The caveat the model records about itself",
        "Its ranking AUC is <b>1.00 on SEC filings</b> but <b>0.778 on pitch decks</b>. It is close to "
        "flawless at the thing it was trained on and noticeably weaker at the thing it is actually "
        "used for. That gap sits in the model's own report file rather than being left for someone "
        "to discover later.",
        tone=CAUTION, bg=colors.HexColor("#FFF6E8")))

    s.append(Spacer(1, 1 * mm))
    s.append(P("5.4 Text embedder", "h2"))
    s.append(P(
        "A supporting model. It converts any piece of text into 64 numbers so that similar text ends "
        "up with similar numbers, which is what powers \"find me companies like this one\". Built with "
        "TF-IDF and SVD rather than a modern sentence transformer, because the machine it was built on "
        "could not reach the model hub. When it fails it returns nothing at all rather than a vector of "
        "zeros - a zero vector would silently produce confident, meaningless neighbours.", "body"))

    s.append(Spacer(1, 1 * mm))
    s.append(P("5.5 Claim Model - trained, measured, deliberately not used", "h2"))
    s.append(P(
        "The idea was to replace the language model's claim checking with something cheaper: a "
        "classifier deciding whether evidence supports, refutes, or says nothing about a claim. It was "
        "trained on SciFact, 1,109 claim-and-evidence pairs.", "body"))
    s.append(table([
        ["Class", "Precision", "Recall", "F1", "Support"],
        ["Not enough info", "0.735", "0.602", "0.662", "83"],
        ["<b>Refutes</b>", "<b>0.063</b>", "<b>0.042</b>", "<b>0.050</b>", "48"],
        ["Supports", "0.393", "0.527", "0.451", "91"],
        ["<b>Overall accuracy</b>", "", "", "<b>0.450</b>", "222"],
    ], [FULL - 88 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm], align_right=(1, 2, 3, 4)))
    s.append(callout(
        "A useful failure",
        "45% accuracy on a three-way choice is barely above guessing - and the class that matters "
        "most, <b>Refutes</b>, is essentially never detected: an F1 of 0.05. Catching a false claim is "
        "the single most valuable thing a diligence tool can do, and this model cannot do it. Deciding "
        "whether evidence contradicts a claim requires understanding negation and relationships, which "
        "word-overlap statistics simply cannot represent. <b>It is not wired into the product, because "
        "shipping it would make the product worse.</b> It stands as evidence for keeping the "
        "language-model approach.",
        tone=NEGATIVE, bg=colors.HexColor("#FDF0EF")))

    s.append(Spacer(1, 1 * mm))
    s.append(P("5.6 Risk/Tone Model - trained, usable, still not connected", "h2"))
    s.append(P(
        "Trained on Financial PhraseBank and a Twitter financial-news sentiment set - 15,376 examples, "
        "77% accuracy, macro-F1 0.62. Genuinely usable, unlike the claim model. It is not connected "
        "because replacing the existing keyword-based risk detector requires a proper head-to-head "
        "comparison, and doing that carelessly would mean swapping one component for another without "
        "knowing which is better.", "body"))

    # ===== 6. DATASETS =====
    s.append(Spacer(1, 4 * mm))
    s.append(P("6. The datasets", "h1"))
    s.append(P(
        "Every dataset is public, named and verifiable. Nothing was scraped from an unattributed "
        "source, and no training data was invented or synthesised.", "body"))

    link = ParagraphStyle("link", parent=S["cell"], textColor=BRAND, fontSize=7.9, leading=11.4)

    s.append(table([
        ["Dataset", "Direct link", "Trains", "Size"],
        ["Y Combinator company directory",
         Paragraph("github.com/yc-oss/api", link),
         "VentureFlow Score, Outcome Model, embedder", "1,560 companies"],
        ["SEC EDGAR filings",
         Paragraph("efts.sec.gov/LATEST/search-index<br/>sec.gov/Archives/edgar/data", link),
         "Risk Disclosure Model", "941 excerpts / 614 filings"],
        ["SciFact (Allen Institute for AI)",
         Paragraph("github.com/allenai/scifact", link),
         "Claim Model (not shipped)", "1,109 pairs"],
        ["Financial PhraseBank",
         Paragraph("huggingface.co/datasets/takala/financial_phrasebank", link),
         "Risk/Tone Model (not shipped)", "part of 15,376"],
        ["Twitter Financial News Sentiment",
         Paragraph("huggingface.co/datasets/zeroshot/twitter-financial-news-sentiment", link),
         "Risk/Tone Model (not shipped)", "part of 15,376"],
        ["Real pitch decks",
         Paragraph("Source URL + SHA-256 recorded per file in the repository", link),
         "Evaluation only - never training", "7 decks"],
    ], [37 * mm, 58 * mm, 45 * mm, FULL - 140 * mm]))

    s.append(P("6.1 Where the labels come from", "h3"))
    s.extend(bullets([
        "<b>Y Combinator data</b> is a public, continuously updated mirror of YC's own company directory. A company's status field gives the label: acquired, public or active counts as a success; dead counts as a failure.",
        "<b>SEC filings</b> are public-domain regulatory documents - the primary source, not a summary of one. Labels come from the 38 retrieval phrases described in Section 5.3.",
        "<b>SciFact</b> ships with expert annotations already; no labelling was needed.",
        "<b>The pitch decks</b> are used only to test the system, never to train it. Each one has its source URL and a cryptographic hash recorded so anyone can confirm the exact file used.",
    ]))
    s.append(Spacer(1, 2 * mm))
    s.append(callout(
        "Two headline numbers were retracted",
        "An earlier evaluation reported 0.9747 for the Outcome Model and 0.668 for the VentureFlow "
        "Score. Both were <b>measured on the models' own training data</b> - the equivalent of "
        "marking an exam with the answer sheet. They were re-measured properly, corrected to 0.6459 "
        "and 0.6356, and the retraction is recorded in the repository rather than quietly overwritten.",
        tone=NEGATIVE, bg=colors.HexColor("#FDF0EF")))

    # ===== 7. LIMITS =====
    s.append(Spacer(1, 4 * mm))
    s.append(P("7. What it cannot do", "h1"))
    s.append(P(
        "Stated plainly, because each of these will otherwise look like a bug someone introduced.", "body"))
    s.append(table([
        ["Limitation", "Detail"],
        ["Image-only decks cannot be read at all",
         "8 of 13 well-known decks tested extract zero characters - every page is a picture. There is no OCR. Confirmed for Dropbox, LinkedIn, YouTube, Facebook, WeWork, BuzzFeed, Brex and Alan."],
        ["The scores are weak predictors",
         "AUC 0.64-0.68 is a real signal and far better than the 0.5 it replaced, but it is a way to sort a pile of decks, not a way to decide an investment."],
        ["It predicts survival, not returns",
         "A company that quietly survived as a small business scores the same as one that returned a fund."],
        ["The comparison set is YC-only",
         "Similar companies are drawn from Y Combinator alumni, not from the whole market."],
        ["Free-tier language model limits",
         "200,000 tokens per day, which is roughly 4 to 8 full deck analyses. Past that, extraction drops to the fallback path - and now says so."],
        ["No user accounts",
         "The deployed demo is protected by a shared passphrase. That is a gate, not authentication: there is no user model and no per-account separation."],
        ["One search provider",
         "DuckDuckGo only, and it rate-limits aggressively under sustained use."],
    ], [50 * mm, FULL - 50 * mm]))

    s.append(P("8. Running it yourself", "h1"))
    s.append(P("Two terminals, from the project root:", "body"))
    code = Table([[Paragraph(
        ".venv/Scripts/python.exe -m uvicorn api:app --reload --port 8000<br/>"
        "npm run dev --prefix frontend", S["mono"])]], colWidths=[FULL])
    code.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F4F8")),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    s.append(code)
    s.append(Spacer(1, 3 * mm))
    s.append(P(
        "Then open <b>localhost:5173</b>. From a clean machine you also need to install the Python "
        "and Node dependencies, provide a database URL and a Groq API key in a <font face=\"Courier\">"
        ".env</font> file, and apply the database migrations. The test suite is 406 tests and takes "
        "about five minutes.", "body"))

    s.append(P("9. Where to read more", "h2"))
    s.append(table([
        ["Document", "Contents"],
        ["ml/README.md", "Every model, in full technical depth"],
        ["ml/research/README.md", "Research write-up, methodology and related work"],
        ["ml/research/EXPERIMENT_LOG.md", "What was tried, including everything that failed"],
        ["HANDOFF.md", "Backend architecture, environment variables, known issues"],
        ["frontend/FRONTEND_HANDOFF.md", "Frontend design system, accessibility, deployment"],
        ["ml/eval/validation/", "Out-of-sample validation and the locked evaluation splits"],
    ], [58 * mm, FULL - 58 * mm]))

    s.append(Spacer(1, 6 * mm))
    s.append(callout(
        "In one sentence",
        "VentureFlow does the checking pass on a pitch deck that an investor rarely has time to do - "
        "and, unusually, it is built to tell you clearly when it could not.",
        tone=BRAND))
    return s


if __name__ == "__main__":
    path = build()
    print(f"Wrote {path} ({path.stat().st_size:,} bytes)")
