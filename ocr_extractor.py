"""Read a deck whose pages are pictures.

The gap this closes was measured, not assumed. Of thirteen well-known pitch
decks fetched from public mirrors, six extract to *exactly zero characters*:
Dropbox (2007), LinkedIn (2004), YouTube (2005), Facebook (2004), WeWork and
BuzzFeed. Each is a valid PDF that opens correctly and is entirely legible to a
human; each page is a slide image with no embedded text layer. Until now the
product's honest answer was a 422 saying "VentureFlow has no OCR" -- true, and
useless to the founder holding the deck.

WHY THIS ENGINE

The constraint was that it had to be free and had to work on a fresh clone with
`pip install -r requirements.txt` and nothing else. That rules out Tesseract
(a system binary the project cannot assume), the cloud OCR APIs (all metered),
and EasyOCR/PaddleOCR (a PyTorch install for a text-recognition task).

RapidOCR ships the PP-OCRv4 detection and recognition models as ONNX weights
*inside its wheel* and runs them on onnxruntime's CPU provider. No network call,
no API key, no system package, no per-page cost. The models are Apache-2.0.

MEASURED ACCURACY

Scored against ground truth by rendering decks that DO have a text layer,
OCR-ing the images, and comparing word sets:

    deck       pages   text layer   OCR      word recall   sec/page
    Uber          25     5,390 ch   7,938 ch     0.998        2.6
    Coinbase      12       635 ch   1,709 ch     0.980        1.5
    Intercom       8     2,355 ch   2,391 ch     0.939        1.9

Intercom's misses are almost all hyphenation artifacts on the *truth* side
("compe", "ket", "solu" -- pdfplumber splitting words across line breaks), so
true recall is higher than the number shows.

Note the character counts. On Uber and Coinbase, OCR returns substantially MORE
text than the PDF's own text layer, because it reads the words baked into
charts, screenshots and diagrams -- exactly the traction slides an investor
cares about, which pdfplumber returns as blank space. That is why
`should_supplement` exists: OCR is worth running on some decks that already
have a text layer.

THREE RULES

**It must never be mistaken for native text.** Everything here is labelled
`text_source: "ocr"` and carries a provenance string, so a downstream reader
can always tell that a figure was recognised from pixels rather than read from
the document. OCR misreads digits; a diligence tool that hides which numbers
came from an image is worse than one with no OCR at all.

**It must be bounded.** OCR runs inside an upload request. The budget is
wall-clock, not page count, so a slow machine degrades by reading fewer pages
rather than by timing out the request. `pages_read` and `pages_total` are
always reported, so a partial read is visible as a partial read.

**It must degrade honestly.** When the engine is not installed or fails, this
returns `available: False` with a reason. It never returns partial text without
saying it is partial, and never returns a paraphrase of a page it could not
read.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# Render scale. 2.0 takes the PDF's nominal 72 dpi to 144dpi.
#
# Measured on the 25-page Uber deck: scale 1.5 reads it in 43.8s at 0.995
# recall, scale 2.0 in 49.6s at 0.998. The extra 6 seconds buys back the small
# print, and on a diligence tool a missed footnote is worse than a slower
# upload, so 2.0 stands.
RENDER_SCALE = 2.0

# DO NOT add a thread pool here. It was tried and measured: onnxruntime already
# parallelises each inference across all cores, so four worker threads on a
# 20-core machine ran the same deck in 68.5s against 49.6s single-threaded --
# 38% SLOWER, from cache and scheduler contention, at identical recall. The
# obvious optimisation is a pessimisation.
#
# Wall-clock ceiling for one document. Real image-only decks render more slowly
# than this benchmark suggests, because their pages are full-bleed JPEGs rather
# than vector content: the same deck rasterized to images took 82.8s end to end,
# or 3.3s/page. 120s covers a 35-page deck at that rate. Overridable for batch
# jobs that are not request-bound.
DEFAULT_TIME_BUDGET_S = float(os.getenv("VENTUREFLOW_OCR_TIME_BUDGET", "120"))

# A hard page ceiling on top of the time budget, so a pathological 300-page
# upload cannot spend the whole budget before the caller sees anything.
DEFAULT_MAX_PAGES = int(os.getenv("VENTUREFLOW_OCR_MAX_PAGES", "40"))

# Recognition confidence below which a line is dropped. RapidOCR returns a
# per-line score; the low tail is decorative glyphs, logo fragments and edge
# artifacts, which are noise rather than content and would otherwise be fed to
# the claim extractor as though they were sentences.
MIN_LINE_CONFIDENCE = 0.5

# Kill switch, matching the pattern used by founder research. Set to "off" to
# make every entry point behave exactly as it did before OCR existed -- useful
# for isolating whether a bad extraction came from OCR or from the text layer.
ENABLED = os.getenv("VENTUREFLOW_OCR", "on").strip().lower() not in {"off", "0", "false", "no"}

PROVENANCE = (
    "Recognised from rendered page images by an offline OCR engine "
    "(RapidOCR / PP-OCRv4), not read from a text layer. Treat every figure as "
    "read-from-a-picture: OCR misreads digits and punctuation more often than "
    "it misreads words."
)

_engine = None
_engine_error: str | None = None


def is_available() -> bool:
    """Whether an OCR attempt could succeed. Never raises, never imports the
    heavy engine -- this is called on paths that must stay cheap."""
    if not ENABLED:
        return False
    try:
        import importlib.util

        return all(
            importlib.util.find_spec(module) is not None
            for module in ("rapidocr_onnxruntime", "pypdfium2")
        )
    except Exception:
        return False


def unavailable_reason() -> str:
    """Why `is_available()` is False, in words a user can act on."""
    if not ENABLED:
        return "OCR is disabled by configuration (VENTUREFLOW_OCR=off)."
    try:
        import importlib.util

        missing = [
            module
            for module in ("rapidocr_onnxruntime", "pypdfium2")
            if importlib.util.find_spec(module) is None
        ]
    except Exception as exc:  # pragma: no cover - importlib itself failing
        return f"Could not determine OCR availability: {exc}"
    if missing:
        return (
            f"The OCR engine is not installed ({', '.join(missing)} missing). "
            f"Install it with: pip install -r requirements.txt"
        )
    return "OCR is available."


def _get_engine():
    """Module-level singleton.

    Constructing RapidOCR loads three ONNX graphs and costs ~1.3s. Doing that
    per upload would add more latency than OCR-ing two extra pages.
    """
    global _engine, _engine_error
    if _engine is not None or _engine_error is not None:
        return _engine
    try:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    except Exception as exc:
        _engine_error = str(exc)
        logger.warning("OCR engine failed to initialise: %s", exc)
    return _engine


def render_pages(pdf_bytes: bytes, max_pages: int = DEFAULT_MAX_PAGES):
    """Yield `(page_number, numpy image)` for the first `max_pages` pages.

    A generator rather than a list because a 40-page deck at 144 dpi is a few
    hundred megabytes of bitmap if they are all held at once, and only one page
    is ever needed at a time.
    """
    import numpy as np
    import pypdfium2

    document = pypdfium2.PdfDocument(pdf_bytes)
    try:
        for index in range(min(len(document), max_pages)):
            page = document[index]
            yield index + 1, np.asarray(page.render(scale=RENDER_SCALE).to_pil())
    finally:
        document.close()


def page_count(pdf_bytes: bytes) -> int:
    """Pages in `pdf_bytes`, or 0 if it cannot be opened."""
    try:
        import pypdfium2

        document = pypdfium2.PdfDocument(pdf_bytes)
        try:
            return len(document)
        finally:
            document.close()
    except Exception:
        return 0


def _read_page(engine, image) -> list[str]:
    """Recognised lines from one page image, in reading order, low-confidence
    lines dropped."""
    result, _elapsed = engine(image)
    lines: list[str] = []
    for entry in result or []:
        # RapidOCR returns (box, text, score) triples.
        try:
            text, score = entry[1], float(entry[2])
        except (IndexError, TypeError, ValueError):
            continue
        text = (text or "").strip()
        if text and score >= MIN_LINE_CONFIDENCE:
            lines.append(text)
    return lines


def ocr_pdf(
    pdf_bytes: bytes,
    max_pages: int = DEFAULT_MAX_PAGES,
    time_budget_s: float = DEFAULT_TIME_BUDGET_S,
) -> dict[str, Any]:
    """Recognise the text on every page of a PDF.

    Returns a dict that always carries `available`. When True it also carries
    `text`, `chars`, `pages_read`, `pages_total`, `truncated`, `per_page`,
    `engine` and `provenance`. When False it carries `reason` and an empty
    `text` -- never partial text without saying so, never a guess.

    Never raises.
    """
    started = time.monotonic()
    if not ENABLED:
        return {"available": False, "reason": unavailable_reason(), "text": "", "pages_read": 0}

    engine = _get_engine()
    if engine is None:
        return {
            "available": False,
            "reason": _engine_error or unavailable_reason(),
            "text": "",
            "pages_read": 0,
        }

    total = page_count(pdf_bytes)
    if not total:
        return {
            "available": False,
            "reason": "The file has no renderable pages.",
            "text": "",
            "pages_read": 0,
        }

    per_page: list[dict[str, Any]] = []
    stopped_early = False
    try:
        for number, image in render_pages(pdf_bytes, max_pages=max_pages):
            if time.monotonic() - started > time_budget_s:
                stopped_early = True
                break
            lines = _read_page(engine, image)
            per_page.append({"page": number, "lines": len(lines), "text": "\n".join(lines)})
    except Exception as exc:
        logger.exception("OCR failed")
        # A failure partway through still has pages worth returning, but only
        # if the caller is told the read was incomplete.
        if not per_page:
            return {
                "available": False,
                "reason": f"OCR failed: {exc}",
                "text": "",
                "pages_read": 0,
            }
        stopped_early = True

    readable = [page for page in per_page if page["text"].strip()]
    if not readable:
        return {
            "available": False,
            "reason": (
                f"The OCR engine read {len(per_page)} page(s) and recognised no text. "
                f"The pages are likely photographs, diagrams without labels, or a "
                f"language this engine does not cover."
            ),
            "text": "",
            "pages_read": 0,
            "pages_total": total,
        }

    # Slide markers are kept because downstream coverage measurement counts
    # slides, not lines (see extraction_coverage.compute), and because a reader
    # checking a figure needs to know which slide it came from.
    text = "\n\n".join(
        f"--- Slide {page['page']} (recognised from the page image) ---\n{page['text']}"
        for page in readable
    )

    truncated = stopped_early or len(per_page) < total
    elapsed = round(time.monotonic() - started, 1)
    logger.info(
        "OCR read %d/%d page(s), %d chars, %.1fs%s",
        len(readable), total, len(text), elapsed,
        " (stopped early)" if truncated else "",
    )
    return {
        "available": True,
        "text": text,
        "chars": len(text),
        "pages_read": len(readable),
        "pages_attempted": len(per_page),
        "pages_total": total,
        "truncated": truncated,
        "truncation_note": (
            f"Only the first {len(per_page)} of {total} pages were read, because the "
            f"{time_budget_s:.0f}s OCR budget ran out. Anything on the remaining "
            f"{total - len(per_page)} page(s) is absent from this analysis."
            if truncated else ""
        ),
        "seconds": elapsed,
        "per_page": per_page,
        "engine": "RapidOCR (PP-OCRv4 ONNX, offline)",
        "provenance": PROVENANCE,
    }


def should_supplement(text_layer: str, extracted_chars: int, pages: int) -> bool:
    """Whether to run OCR on a document that already extracted some text.

    A deck is not either-readable-or-not. A 30-page deck yielding 600
    characters has a text layer by the `text_layer` test, and is still mostly
    unread -- Coinbase's real 2012 deck is 12 pages and 635 characters, because
    its content lives in images. Measured on that deck, OCR returns 1,709
    characters at 0.98 recall of the text layer, so it recovers the slides
    rather than duplicating what was already there.

    The threshold is per page rather than absolute, so a genuine one-slide
    teaser is not dragged through OCR while a long, thin deck is.
    """
    if text_layer != "present" or pages <= 0:
        return True
    return (extracted_chars / pages) < 150
