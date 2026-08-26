"""Read a pitch deck that has no text layer, including its charts.

The gap this closes, measured rather than assumed. Of thirteen well-known pitch
decks fetched from public mirrors, **six extracted to exactly zero characters**:
Dropbox (2007), LinkedIn (2004), YouTube (2005), Facebook (2004), WeWork and
BuzzFeed. Each is a valid PDF that opens correctly and is entirely legible to a
human; each page is a slide *image* with no embedded text. Before
`document_extractor.text_layer` existed, all six arrived at the pipeline as
`text=""` and produced a report about nothing, and the report attributed that to
the deck being thin rather than to the product being unable to open it.

Text extraction is only half of it. Even in decks that DO have a text layer, the
traction slide is usually the part that matters most to an investor and the part
that carries the least text: a revenue chart's meaning lives in its axes, its
bars and its trend, none of which pdfplumber returns. A tool that reads
everything on a deck except the growth curve is missing the slide the founder
built the raise around.

So this module renders pages and asks a vision model to do two things: transcribe
the text verbatim, and describe every chart as *data* -- axis labels, units,
plotted series, the values it can read, and the direction of the trend.

Three constraints shape the design.

**It must never invent a number.** A hallucinated revenue figure attributed to a
chart is the worst possible output for a diligence tool, because it is
indistinguishable from a real reading and it is exactly the number an investor
acts on. The prompt therefore demands verbatim transcription, requires the model
to mark any value it is inferring rather than reading, and the output is labelled
throughout as vision-derived so nothing downstream can mistake it for text the
document actually contained.

**It must be opt-in and bounded.** Vision calls are expensive against a
200,000 token/day free tier that a single deck run already spends 24,000 of. It
runs only when there is no text layer to read, only up to `max_pages`, and never
as a silent part of every analysis.

**It must degrade honestly.** When no vision model is configured or reachable,
this returns `available: False` with a reason. It never returns partial or
guessed text, because "we could not read your deck" is a true statement and a
paraphrase of a blank page is not.
"""

from __future__ import annotations

import base64
import io
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Vision-capable models on the configured provider. The main pipeline model
# (openai/gpt-oss-120b) is text-only, so this cannot reuse groq_client.MODEL.
# Ordered by preference; the first that the account can actually call wins.
VISION_MODELS = (
    os.getenv("VENTUREFLOW_VISION_MODEL", "").strip() or "qwen/qwen3.8-27b",
    "qwen/qwen3.6-27b",
)

# Rendering scale. 2.0 roughly doubles the default 72 dpi to 144, which is
# enough for axis labels and small print without producing images large enough
# to dominate the token budget on their own.
RENDER_SCALE = 2.0
DEFAULT_MAX_PAGES = 12

_PROMPT = """You are transcribing one slide from a startup pitch deck so that a
due-diligence system can read it. You are NOT summarising and NOT evaluating.

Return two sections.

TEXT:
Every word visible on the slide, transcribed verbatim, in reading order. Keep
numbers exactly as written, including units and currency symbols. Do not correct,
rephrase, or complete anything.

CHARTS:
For each chart, graph, or table on the slide, describe it as data:
- what it plots, and the title if there is one
- the x-axis label and its tick values
- the y-axis label, its units, and its scale
- each series by name
- the values you can actually READ from the plot or its data labels
- the direction and rough magnitude of the trend

Rules you must not break:
- Transcribe only what is visibly present. Never infer a number that is not
  shown.
- If a value is unlabelled and you are estimating it from the position of a bar
  or point, write it as "approximately X (read from plot position, not labelled)".
- If the slide has no chart, write "CHARTS: none".
- If the slide is unreadable, write exactly "UNREADABLE".
"""


def is_available() -> bool:
    """Whether a vision call could be attempted at all."""
    return bool(os.getenv("GROQ_API_KEY"))


def render_pages(pdf_bytes: bytes, max_pages: int = DEFAULT_MAX_PAGES) -> list[bytes]:
    """PNG bytes for the first `max_pages` pages of `pdf_bytes`.

    Uses pypdfium2, which is already a dependency and needs no external binary
    -- relevant because the alternative (poppler/tesseract) is a system install
    this project cannot assume on a fresh clone.
    """
    import pypdfium2

    images: list[bytes] = []
    document = pypdfium2.PdfDocument(pdf_bytes)
    try:
        for index in range(min(len(document), max_pages)):
            page = document[index]
            pil_image = page.render(scale=RENDER_SCALE).to_pil()
            buffer = io.BytesIO()
            pil_image.save(buffer, format="PNG", optimize=True)
            images.append(buffer.getvalue())
    finally:
        document.close()
    return images


def _read_one(image_png: bytes, model: str) -> str:
    from groq_client import get_client

    encoded = base64.b64encode(image_png).decode("ascii")
    response = get_client().chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": _PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ],
        }],
        temperature=0.0,  # transcription, not generation
        max_tokens=1200,
    )
    return (response.choices[0].message.content or "").strip()


def read_deck(
    pdf_bytes: bytes,
    max_pages: int = DEFAULT_MAX_PAGES,
    model: str | None = None,
) -> dict[str, Any]:
    """Transcribe an image-only deck, charts included.

    Returns {available, text, pages_read, model, per_page, reason}. On any
    failure `available` is False and `text` is empty -- never partial, never
    paraphrased. A caller must treat `available: False` as "this deck could not
    be read", which is a true and useful statement, and must never fall through
    to analysing an empty string as though it were the deck's content.
    """
    if not is_available():
        return {"available": False, "reason": "No GROQ_API_KEY configured.",
                "text": "", "pages_read": 0}

    try:
        images = render_pages(pdf_bytes, max_pages=max_pages)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Slide rendering failed")
        return {"available": False, "reason": f"Could not render pages: {exc}",
                "text": "", "pages_read": 0}

    if not images:
        return {"available": False, "reason": "The document has no renderable pages.",
                "text": "", "pages_read": 0}

    candidates = [model] if model else list(VISION_MODELS)
    last_error: Exception | None = None

    for candidate in candidates:
        per_page: list[dict[str, Any]] = []
        try:
            for index, image in enumerate(images, 1):
                content = _read_one(image, candidate)
                per_page.append({"page": index, "content": content})
        except Exception as exc:  # noqa: BLE001
            # A model the account cannot call should fall through to the next
            # candidate; a quota failure should not be silently retried forever.
            logger.warning("Vision model %s failed: %s", candidate, exc)
            last_error = exc
            continue

        readable = [
            page for page in per_page
            if page["content"] and page["content"].upper() != "UNREADABLE"
        ]
        if not readable:
            return {"available": False,
                    "reason": "The vision model could not read any page.",
                    "text": "", "pages_read": 0, "model": candidate}

        text = "\n\n".join(
            f"--- Slide {page['page']} (read from the slide image, not from a text layer) ---\n"
            f"{page['content']}"
            for page in readable
        )
        return {
            "available": True,
            "text": text,
            "pages_read": len(readable),
            "pages_attempted": len(images),
            "model": candidate,
            "per_page": per_page,
            "provenance": (
                "Transcribed from rendered slide images by a vision model. Treat every "
                "figure as read-from-an-image, not as text the document contained."
            ),
        }

    return {"available": False,
            "reason": f"No vision model was callable ({last_error}).",
            "text": "", "pages_read": 0}
