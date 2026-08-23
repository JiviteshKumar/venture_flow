"""One entry point for turning an uploaded deck into text, whatever format it
arrived in.

Before this file the product accepted PDF and nothing else, which is a real
limitation rather than a cosmetic one: founders send decks as .pptx more often
than as .pdf, and a tool that rejects the native format makes the user export
first. The alternative to this module -- a second extraction path per format,
each with its own claim and financial parsing -- is how the two extractors in
this repository would have become four. So every format converges on plain
text here and then goes through exactly the same
`structured_extractor.extract_structured()` pipeline the PDF path already used.

Formats:
    .pdf            pdfplumber, with the column-aware reader in pdf_extractor
    .pptx           python-pptx: shape text, tables, and speaker notes
    .docx           python-docx: paragraphs and tables, headings kept
    .txt .md        decoded directly (for decks already converted to text)

Every reader returns `(text, page_count)` where page_count is pages, slides or
an estimate, and raises `UnsupportedDocument` for a format it cannot read.
Nothing here swallows an extraction failure into empty text: an empty deck and
a broken parser must not look the same to the caller.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class UnsupportedDocument(Exception):
    """Raised for a file extension no reader handles."""


# Extension -> the human-facing name used in error messages and the UI.
SUPPORTED_FORMATS: dict[str, str] = {
    ".pdf": "PDF",
    ".pptx": "PowerPoint",
    ".docx": "Word",
    ".txt": "plain text",
    ".md": "Markdown",
}

# Content types browsers actually send for the formats above. Checked as a
# hint only -- the extension decides, because browsers disagree about .md and
# some send application/octet-stream for anything they do not recognise.
SUPPORTED_CONTENT_TYPES: set[str] = {
    "application/pdf",
    "application/x-pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "application/octet-stream",
}


def extension_of(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def is_supported(filename: str) -> bool:
    return extension_of(filename) in SUPPORTED_FORMATS


def _extract_pdf(data: bytes) -> tuple[str, int]:
    import pdfplumber

    from pdf_extractor import extract_page_text

    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            text = extract_page_text(page)
            if text:
                parts.append(text.strip())
        page_count = len(pdf.pages)
    return "\n".join(parts), page_count


def _shape_text(shape) -> list[str]:
    """Text from one pptx shape, recursing into groups and tables.

    Grouped shapes matter on real decks -- a team slide is usually one group
    per person -- and a reader that only looks at top-level shapes silently
    drops all of them.
    """
    parts: list[str] = []
    shape_type = getattr(shape, "shape_type", None)
    if str(shape_type) == "GROUP (6)" or getattr(shape, "shapes", None) is not None:
        for child in getattr(shape, "shapes", []):
            parts.extend(_shape_text(child))
        return parts
    if getattr(shape, "has_table", False):
        for row in shape.table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
        return parts
    if getattr(shape, "has_text_frame", False):
        for paragraph in shape.text_frame.paragraphs:
            line = "".join(run.text for run in paragraph.runs).strip()
            if line:
                parts.append(line)
    return parts


def _order_shapes(shapes: list, slide_width: float) -> list:
    """Put a slide's shapes into human reading order, columns respected.

    pptx stores shapes in z-order, which is the order the deck was built in,
    not the order anyone reads. Sorting by (top, left) fixes that for a
    single-column slide and breaks a multi-column one in exactly the way
    `page.extract_text()` breaks a multi-column PDF: on the PetVoice team
    slide it produced three names, then three job titles, then three
    biographies, so pairing any founder with their own role required guessing.

    Columns are found by clustering shape centres rather than by the empty-gap
    histogram the PDF reader uses. Shapes are sparse where words are dense: a
    slide has twenty boxes, not five hundred glyphs, so a histogram over them
    is mostly empty and every whitespace band looks like a gutter. Clustering
    centres is the reliable read on this input, and the two readers stay
    honest about being different algorithms rather than sharing one that suits
    neither.
    """
    boxes = [
        {
            "shape": shape,
            "x0": float(shape.left or 0),
            "x1": float((shape.left or 0) + (shape.width or 0)),
            "top": float(shape.top or 0),
        }
        for shape in shapes
    ]
    by_position = sorted(boxes, key=lambda b: (b["top"], b["x0"]))
    if len(boxes) < 3 or slide_width <= 0:
        return [b["shape"] for b in by_position]

    # Full-width shapes -- the slide title, a subtitle banner -- span every
    # gutter, so including them in the clustering merges all the columns into
    # one. They are placed by the spans-a-boundary check further down instead.
    narrow = [b for b in boxes if (b["x1"] - b["x0"]) <= 0.5 * slide_width]
    if len(narrow) < 3:
        return [b["shape"] for b in by_position]

    split_gap = 0.12 * slide_width

    def boundaries_from(candidates: list[dict]) -> list[float]:
        centres = sorted((b["x0"] + b["x1"]) / 2 for b in candidates)
        return [
            (low + high) / 2
            for low, high in zip(centres, centres[1:])
            if high - low > split_gap
        ]

    # Converge on the boundaries. The 50%-width cutoff above does not catch
    # every spanning shape: a slide title occupying 45% of the width is narrow
    # by that test, and its centre sits between two real columns, which drags
    # the boundary far enough right that a genuine column's card background
    # then looks like it spans a gutter. Re-deriving the boundaries with the
    # straddlers removed settles it in one or two passes; bounded so a
    # pathological slide cannot loop.
    contributors = narrow
    boundaries = boundaries_from(contributors)
    for _ in range(3):
        if not boundaries:
            break
        remaining = [
            b for b in contributors
            if not any(b["x0"] < edge < b["x1"] for edge in boundaries)
        ]
        if len(remaining) == len(contributors) or len(remaining) < 3:
            break
        contributors = remaining
        boundaries = boundaries_from(contributors)

    if not boundaries:
        return [b["shape"] for b in by_position]
    columns = list(zip([0.0, *boundaries], [*boundaries, slide_width]))

    def column_of(box: dict) -> int:
        midpoint = (box["x0"] + box["x1"]) / 2
        for index, (low, high) in enumerate(columns):
            if low <= midpoint < high:
                return index
        return len(columns) - 1

    ordered: list = []
    block: list[dict] = []

    def flush() -> None:
        for column in range(len(columns)):
            for box in sorted(
                (b for b in block if column_of(b) == column), key=lambda b: b["top"]
            ):
                ordered.append(box["shape"])
        block.clear()

    for box in sorted(boxes, key=lambda b: (b["top"], b["x0"])):
        spans_gutter = any(box["x0"] < low < box["x1"] for low, _ in columns[1:])
        if spans_gutter:
            # A title bar or a full-width footer: belongs to no column, and
            # everything above it is a completed group.
            flush()
            ordered.append(box["shape"])
        else:
            block.append(box)
    flush()
    return ordered


def _extract_pptx(data: bytes) -> tuple[str, int]:
    from pptx import Presentation

    presentation = Presentation(io.BytesIO(data))
    slide_width = float(presentation.slide_width or 0)
    parts: list[str] = []
    for slide in presentation.slides:
        slide_parts: list[str] = []
        for shape in _order_shapes(list(slide.shapes), slide_width):
            slide_parts.extend(_shape_text(shape))
        notes = getattr(slide, "notes_slide", None) if slide.has_notes_slide else None
        if notes is not None and notes.notes_text_frame is not None:
            note_text = notes.notes_text_frame.text.strip()
            if note_text:
                slide_parts.append(f"Speaker notes: {note_text}")
        if slide_parts:
            parts.append("\n".join(slide_parts))
    return "\n".join(parts), len(presentation.slides)


def _extract_docx(data: bytes) -> tuple[str, int]:
    import docx

    document = docx.Document(io.BytesIO(data))
    parts: list[str] = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    text = "\n".join(parts)
    # Word has no page count without rendering the document, so this is an
    # estimate at roughly 2,500 characters per page and is labelled as one
    # everywhere it surfaces.
    return text, max(1, len(text) // 2500 + (1 if len(text) % 2500 else 0))


def _extract_text(data: bytes) -> tuple[str, int]:
    """Decode a .txt/.md upload, guessing the encoding conservatively.

    Order matters, and getting it wrong is silent rather than loud. utf-16 was
    tried second here and it must not be: without a byte-order mark, utf-16
    accepts almost any even-length byte string and returns plausible-looking
    CJK instead of raising. A perfectly ordinary Windows-encoded deck note
    ("Fleet size 80 - 100 trucks", cp1252) came back as
    '\\u6c46\\u6565\\u2074...' and was passed downstream as the deck's text. So
    utf-16 is only attempted when a BOM actually says so, and cp1252 -- what
    Word's "save as plain text" produces on Windows, and the encoding this
    project has already been bitten by once (see console_safety.py) -- is tried
    before latin-1, which likewise never raises and would otherwise mangle
    every smart quote.
    """
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or data[:4] in (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"):
        candidates = ("utf-16", "utf-8", "cp1252", "latin-1")
    else:
        candidates = ("utf-8", "cp1252", "latin-1")
    for encoding in candidates:
        try:
            text = data.decode(encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        text = data.decode("utf-8", errors="replace")
    return text, max(1, len(text) // 2500 + (1 if len(text) % 2500 else 0))


_READERS = {
    ".pdf": _extract_pdf,
    ".pptx": _extract_pptx,
    ".docx": _extract_docx,
    ".txt": _extract_text,
    ".md": _extract_text,
}


def extract_document(filename: str, data: bytes) -> dict:
    """Read any supported deck format into text.

    Returns {text, page_count, format, extension}. Raises
    `UnsupportedDocument` for an unhandled extension and lets a genuine parse
    error propagate -- the caller turns that into a 422 with the real reason,
    which is more useful than "could not extract readable text" for a file
    that was simply the wrong kind of thing.
    """
    extension = extension_of(filename)
    reader = _READERS.get(extension)
    if reader is None:
        supported = ", ".join(sorted(SUPPORTED_FORMATS))
        raise UnsupportedDocument(
            f"{extension or 'This file'} is not a supported deck format. Supported: {supported}"
        )
    text, page_count = reader(data)
    return {
        "text": text,
        "page_count": page_count,
        "format": SUPPORTED_FORMATS[extension],
        "extension": extension,
    }
