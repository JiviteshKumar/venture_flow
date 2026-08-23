"""Word (.docx) rendering of a due-diligence report.

Content comes from `report_document.build_report_blocks()`, the same function
`report_pdf.py` and `report_markdown.py` render, so the three exports cannot
disagree about what the analysis found. This file is only the python-docx half.

Word matters here for a specific reason rather than as a checkbox: an IC memo
gets edited before it is circulated, and a PDF cannot be. A VC who wants to add
their own note next to a red flag needs the .docx.
"""
from __future__ import annotations

import io
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

from report_document import build_report_blocks

MUTED = RGBColor(0x94, 0xA3, 0xB8)
META = RGBColor(0x4A, 0x55, 0x68)


def build_report_docx(report: dict[str, Any], generated_on: str) -> bytes:
    """Word document bytes for a report dict shaped like the API's
    DiligenceResponse (or the equivalent raw_output)."""
    document = Document()

    # Body text a shade smaller than Word's 11pt default, to match the density
    # of the PDF export rather than producing a visibly different document.
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)

    for block in build_report_blocks(report, generated_on):
        kind = block["kind"]
        if kind == "title":
            document.add_heading(block["text"], level=0)
        elif kind == "meta":
            paragraph = document.add_paragraph()
            run = paragraph.add_run(block["text"])
            run.font.size = Pt(9)
            run.font.color.rgb = META
        elif kind == "heading":
            document.add_heading(block["text"], level=1)
        elif kind == "text":
            # Blank lines in an LLM memo are paragraph breaks; emitting the
            # whole memo as one run would collapse its structure.
            for line in str(block["text"]).split("\n"):
                document.add_paragraph(line) if line.strip() else document.add_paragraph()
        elif kind == "bullets":
            for item in block["items"] or ["None identified."]:
                document.add_paragraph(str(item), style="List Bullet")
        elif kind == "table":
            table = document.add_table(rows=1, cols=len(block["header"]))
            table.style = "Light Grid Accent 1"
            for cell, text in zip(table.rows[0].cells, block["header"]):
                cell.text = str(text)
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.bold = True
            for row in block["rows"]:
                cells = table.add_row().cells
                for cell, text in zip(cells, row):
                    cell.text = str(text)
        elif kind == "caveat":
            paragraph = document.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
            run = paragraph.add_run(block["text"])
            run.font.size = Pt(8)
            run.font.color.rgb = MUTED

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
