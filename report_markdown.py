"""Markdown rendering of a due-diligence report.

Content comes from `report_document.build_report_blocks()`, the same function
`report_pdf.py` and `report_docx.py` render.

Markdown is the format that actually gets pasted into a Notion page, a Slack
thread or a git-tracked deal file, and unlike the other two it stays diffable --
re-running an analysis on the same company a month later and diffing the two
exports is a real workflow this makes possible.
"""
from __future__ import annotations

from typing import Any

from report_document import build_report_blocks


def _escape_cell(text: str) -> str:
    """Pipes inside a cell would silently split it into two columns."""
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def build_report_markdown(report: dict[str, Any], generated_on: str) -> str:
    """A Markdown document for a report dict shaped like the API's
    DiligenceResponse (or the equivalent raw_output)."""
    lines: list[str] = []

    for block in build_report_blocks(report, generated_on):
        kind = block["kind"]
        if kind == "title":
            lines += [f"# {block['text']}", ""]
        elif kind == "meta":
            lines += [f"_{block['text']}_", ""]
        elif kind == "heading":
            lines += [f"## {block['text']}", ""]
        elif kind == "text":
            lines += [str(block["text"]).strip(), ""]
        elif kind == "bullets":
            lines += [f"- {item}" for item in block["items"] or ["None identified."]]
            lines.append("")
        elif kind == "table":
            header = block["header"]
            lines.append("| " + " | ".join(_escape_cell(c) for c in header) + " |")
            lines.append("| " + " | ".join("---" for _ in header) + " |")
            for row in block["rows"]:
                lines.append("| " + " | ".join(_escape_cell(c) for c in row) + " |")
            lines.append("")
        elif kind == "caveat":
            # Blockquote rather than plain text: the small print has to stay
            # visually distinct from the findings in a format that has no font
            # sizes to distinguish them with.
            lines += [f"> {block['text']}", ""]

    return "\n".join(lines).rstrip() + "\n"
