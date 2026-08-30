"""How much of the deck actually reached a structured field.

Why this exists. Before this module, "we found nothing in this deck" and
"there was nothing in this deck to find" produced byte-identical output: an
empty claims table and an `INSUFFICIENT DATA` recommendation. Those are
opposite situations. The first is a parsing defect and the report is wrong;
the second is an honest reading of a thin deck and the report is right. A
partner reading the memo had no way to tell them apart -- and in the audit
that prompted this work they were not distinguishable even to the engineer who
wrote the pipeline: a deck whose middle seven slides were silently dropped was
labelled `HIGH data quality (100/100)`.

So this measures the one thing that separates them: of the text the extractor
was given, how much of it can be found again in the structured output.

## Why slides are the headline unit

The obvious metric is "share of lines mapped", and on its own it is
misleading in both directions. Extraction legitimately *summarises* -- 14
claims from a 146-line deck is a good result, not a 10% failure -- so line
coverage reads alarmingly low even when nothing is wrong. Worse, it is
trivially inflated: the old regex path copied the deck's first 1,200
characters verbatim into `description`, which made a third of the deck
"mapped" while structuring none of it.

The failure this exists to catch is *whole slides contributing nothing*. So
the headline number is slide coverage -- the share of content slides that put
at least one line into a structured field -- and the report names the slides
that contributed nothing. That is both the signal that discriminates the bug
and the thing a partner can act on: "slides 3, 5 and 7 are not represented
below" is checkable against the PDF in ten seconds.

Line coverage is kept as a secondary detail for depth within a slide.

## Deliberately mechanical

This does not ask an LLM whether the extraction was good, because a model that
missed a slide is not well placed to notice it missed a slide. It is string
accounting, which cannot be talked out of a low number.

The number is a *coverage* signal, not a *quality* signal, and the naming
throughout keeps that distinction. High coverage does not mean the claims are
true -- that is what claim verification is for. Low coverage means a reader
should suspect the parser before they suspect the founder.
"""
from __future__ import annotations

import re
from typing import Any

# Lines that are page furniture rather than deck content: a slide number, a
# running footer repeating the company name, a bare "3 / 9". The extractor
# sees these and correctly maps them nowhere, so counting them as missed
# content would depress every score by a constant and make the metric useless
# for comparing decks.
_FURNITURE_PATTERNS = (
    r"^\d{1,3}$",                          # bare slide number
    r"^\d{1,3}\s*/\s*\d{1,3}$",            # "3 / 9"
    r"^(page|slide)\s+\d+",                # "Page 4"
    r"^(confidential|proprietary|copyright|all rights reserved)\b",
    r"^\W+$",                              # rules, bullets, decorative glyphs
)
_FURNITURE_RE = [re.compile(p, re.IGNORECASE) for p in _FURNITURE_PATTERNS]

# Tokens too common to carry evidence that a line was mapped. Without this a
# line sharing only "the of and a" with a claim would read as covered.
_STOPWORDS = frozenset("""
a an the and or but of in on at to for with from by as is are was were be been
being it its this that these those we our you your they their he she his her
will would can could may might must shall should do does did not no nor so
than then there here what which who whom how when where why all any both each
few more most other some such only own same too very just also into over under
""".split())

_TOKEN_RE = re.compile(r"[A-Za-z0-9$%.\-]+")

# A line counts as mapped when this share of its meaningful tokens reappears in
# a single structured value. 0.6 rather than 1.0 because extraction legitimately
# normalises as it goes -- "Overall Market $4.2B annually and growing" becomes
# "Overall market $4.2B annually and growing" -- and legitimately drops filler.
# Requiring an exact match would report ~0% coverage on a perfect extraction.
_MAPPED_THRESHOLD = 0.6

# A `description` longer than this is a raw text dump, not a summary, and is
# excluded from the mapping targets. The schema asks for "1-2 sentences"; the
# regex fallback instead assigns `text[:1200]`. Counting that as structure is
# precisely the laundering this module exists to detect -- it would let an
# extractor that structured nothing at all report a third of the deck covered.
_MAX_DESCRIPTION_CHARS = 400

# Below this the report tells the reader the extraction itself is suspect.
LOW_COVERAGE_THRESHOLD = 50.0

# Under this many characters of extractable text, a coverage percentage says
# more about how little the deck contained than about how well it was parsed.
# 900 is roughly a page of prose; the corpus deck that prompted this holds 635
# characters across twelve slides.
_THIN_DECK_CHARS = 900


def _tokens(text: str) -> set[str]:
    return {
        t.lower().strip(".-")
        for t in _TOKEN_RE.findall(text or "")
        if t.lower() not in _STOPWORDS and len(t.strip(".-")) > 1
    }


def _is_furniture(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) < 3:
        return True
    return any(rx.match(stripped) for rx in _FURNITURE_RE)


def _structured_values(structured: dict[str, Any]) -> list[str]:
    """Every string the structured output actually carries.

    Read defensively: this runs against the LLM path, the regex fallback and
    the empty path, and those three return overlapping but different key sets.
    """
    values: list[str] = []

    description = structured.get("description")
    if isinstance(description, str) and 0 < len(description.strip()) <= _MAX_DESCRIPTION_CHARS:
        values.append(description)

    for key in ("stage", "sector", "domain"):
        value = structured.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)

    for claim in structured.get("claims") or []:
        if isinstance(claim, str):
            values.append(claim)
        elif isinstance(claim, dict) and claim.get("claim"):
            values.append(str(claim["claim"]))

    for founder in structured.get("founders") or []:
        if isinstance(founder, dict):
            values.append(
                " ".join(
                    str(founder.get(k, "")) for k in ("name", "role", "background")
                ).strip()
            )
        elif isinstance(founder, str):
            values.append(founder)

    # Numeric fields are evidence that a financial line was read, even though
    # they carry no text of their own. Render them so the line that stated
    # them can match.
    for key in ("revenue", "burn_rate", "runway_months", "team_size"):
        value = structured.get(key)
        if isinstance(value, (int, float)) and value:
            values.append(f"{key} {value:g} {int(value):,}")

    for item in structured.get("metadata_evidence") or []:
        if isinstance(item, str):
            values.append(item)

    return [v for v in values if v.strip()]


def compute(
    deck_text: str,
    structured: dict[str, Any],
    slides: list[str] | None = None,
) -> dict[str, Any]:
    """Return how much of the deck reached a structured field.

    `slides` is the per-page text when the caller has it (see
    `pdf_extractor.extract_pages_from_pdf`). Without it the whole deck is
    treated as a single slide and only line coverage is meaningful.

    Never raises and never blocks an analysis: a coverage metric that could
    fail an otherwise good run would be worse than no metric.
    """
    try:
        return _compute(deck_text, structured, slides)
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "available": False,
            "reason": f"Coverage could not be computed: {type(exc).__name__}: {exc}",
        }


def _content_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in (text or "").splitlines()
        if line.strip() and not _is_furniture(line.strip())
    ]


def _compute(
    deck_text: str,
    structured: dict[str, Any],
    slides: list[str] | None,
) -> dict[str, Any]:
    if slides:
        slide_texts = list(slides)
    else:
        slide_texts = [deck_text or ""]

    value_tokens = [t for t in (_tokens(v) for v in _structured_values(structured)) if t]

    def is_mapped(line: str) -> bool:
        line_tokens = _tokens(line)
        if not line_tokens:
            return False
        for candidate in value_tokens:
            if len(line_tokens & candidate) / len(line_tokens) >= _MAPPED_THRESHOLD:
                return True
        return False

    slide_reports: list[dict[str, Any]] = []
    total_lines = mapped_lines = 0
    total_chars = mapped_chars = 0
    unmapped_all: list[str] = []

    for index, slide_text in enumerate(slide_texts, start=1):
        lines = _content_lines(slide_text)
        if not lines:
            # An image-only or purely decorative slide. Recorded, but it is not
            # a content slide and must not count against coverage.
            slide_reports.append(
                {
                    "slide": index,
                    "heading": "",
                    "content_lines": 0,
                    "mapped_lines": 0,
                    "represented": None,
                    "note": "no extractable text (image-only or decorative)",
                }
            )
            continue

        mapped_here = [line for line in lines if is_mapped(line)]
        unmapped_here = [line for line in lines if line not in mapped_here]
        unmapped_all.extend(unmapped_here)

        total_lines += len(lines)
        mapped_lines += len(mapped_here)
        total_chars += sum(len(line) for line in lines)
        mapped_chars += sum(len(line) for line in mapped_here)

        slide_reports.append(
            {
                "slide": index,
                "heading": lines[0][:60],
                "content_lines": len(lines),
                "mapped_lines": len(mapped_here),
                "represented": bool(mapped_here),
                "note": "",
            }
        )

    content_slides = [s for s in slide_reports if s["represented"] is not None]
    represented = [s for s in content_slides if s["represented"]]
    image_only = [s for s in slide_reports if s["represented"] is None]

    slide_coverage = (
        len(represented) / len(content_slides) * 100.0 if content_slides else 0.0
    )
    line_coverage = (mapped_chars / total_chars * 100.0) if total_chars else 0.0

    if not content_slides:
        return {
            "available": True,
            "coverage_pct": 0.0,
            "line_coverage_pct": 0.0,
            "content_slides": 0,
            "represented_slides": 0,
            "image_only_slides": len(image_only),
            "content_lines": 0,
            "mapped_lines": 0,
            "unrepresented_slides": [],
            "unmapped_examples": [],
            "verdict": "EMPTY",
            "interpretation": (
                "The deck yielded no extractable text at all. This is almost "
                "always an image-only PDF with no text layer, not an empty deck. "
                "Nothing below is evidence about the company."
            ),
        }

    if slide_coverage >= 80:
        verdict = "HIGH"
        interpretation = (
            "Most slides contributed content to the structured output. An "
            "'insufficient data' finding below reflects the deck's own content "
            "rather than a parsing gap."
        )
    elif slide_coverage >= LOW_COVERAGE_THRESHOLD:
        verdict = "PARTIAL"
        interpretation = (
            "Some slides contributed nothing to the structured output. Read the "
            "findings below as possibly incomplete, and check the unrepresented "
            "slides before concluding the deck is thin."
        )
    else:
        verdict = "LOW"
        interpretation = (
            "WARNING: most of this deck's slides contributed nothing to the "
            "structured output. Treat any 'insufficient data' finding below as "
            "likely a parsing gap in this tool, NOT as evidence that the deck "
            "lacks content. The unrepresented slides are listed above."
        )

    # A high percentage over very little text is not the same finding as a high
    # percentage over a full deck, and the number alone cannot tell them apart.
    #
    # Coinbase's 2012 deck is the worked example: 12 slides holding 635
    # characters in total, almost all of it slide headings and taglines. Every
    # line reached a field, so coverage is a legitimate 100% -- and reading that
    # as "we understood this deck" would be wrong, because there was barely
    # anything to understand and several captured "claims" are titles rather
    # than assertions. Saying so here costs nothing and stops a perfect score
    # being quoted as proof of a good extraction.
    thin = total_chars < _THIN_DECK_CHARS
    if thin:
        interpretation += (
            f" Note: this deck yielded only {total_chars} characters of text across "
            f"{len(content_slides)} slides, much of it likely headings rather than "
            f"assertions. A high coverage percentage over this little text means the "
            f"parser missed little, NOT that the deck said much -- read the captured "
            f"items themselves before relying on this number."
        )

    return {
        "available": True,
        # Headline: share of content slides that reached a structured field.
        "coverage_pct": round(slide_coverage, 1),
        "content_chars": total_chars,
        "mapped_chars": mapped_chars,
        "thin_text": thin,
        # Secondary: depth within slides.
        "line_coverage_pct": round(line_coverage, 1),
        "content_slides": len(content_slides),
        "represented_slides": len(represented),
        "image_only_slides": len(image_only),
        "content_lines": total_lines,
        "mapped_lines": mapped_lines,
        "unrepresented_slides": [
            {"slide": s["slide"], "heading": s["heading"]}
            for s in content_slides
            if not s["represented"]
        ],
        "unmapped_examples": sorted(unmapped_all, key=len, reverse=True)[:8],
        "slides": slide_reports,
        "verdict": verdict,
        "interpretation": interpretation,
    }
