"""Schema-validated claim + financial extraction, with the original regex
extractor kept as an automatic fallback.

Why this exists: `pdf_extractor.py`'s `extract_claims_from_text` /
`extract_company_info` are hand-tuned regexes, and FIELD_NOTES.md already
flags them as known to mangle multi-column deck layouts and to miss any
phrasing outside their patterns. This module asks the LLM to produce the same
structured fields directly from the deck text, constrained by an explicit
JSON schema and validated with Pydantic before anything downstream is allowed
to trust it. An unparseable response, an invalid response, or an LLM call
that raises are all treated as failures -- the caller silently falls back to
the regex extractor, never to unvalidated free text. The `_method` field in
the return value records which path actually produced the result, so this
degrades honestly instead of quietly.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

import pdf_extractor as _regex_extractor
from groq_client import MODEL, get_client, pace_for

logger = logging.getLogger(__name__)


class ExtractedClaim(BaseModel):
    claim: str = Field(min_length=10, max_length=300)
    category: Literal[
        "financial", "market", "product", "team", "traction", "legal", "other"
    ] = "other"


class ExtractedFounder(BaseModel):
    """A named person from the deck's team slide.

    Added 23 Aug 2026. `agents/founder_verifier.py` had existed unused since
    the third pass because nothing ever populated `DiligenceRequest.founders`:
    the upload form has no founders field and extraction did not look for one,
    so the Founder Analysis tab was structurally guaranteed to be empty. This
    is the automatic half of the fix; the upload form now also lets the user
    correct or add names before submitting.
    """

    name: str = Field(min_length=3, max_length=80)
    role: str = Field(default="", max_length=120)
    background: str = Field(default="", max_length=600)


class ExtractedFinancials(BaseModel):
    description: str = ""
    revenue: float | None = Field(default=None, ge=0)
    burn_rate: float | None = Field(default=None, ge=0)
    runway_months: float | None = Field(default=None, ge=0, le=600)
    claims: list[ExtractedClaim] = Field(default_factory=list, max_length=16)
    founders: list[ExtractedFounder] = Field(default_factory=list, max_length=5)


_SCHEMA_PROMPT = """Return ONLY a JSON object with this exact shape, no prose, no markdown fences:
{
  "description": "<1-2 sentence company summary from the text>",
  "revenue": <annualized revenue in USD as a plain number, or null if not stated>,
  "burn_rate": <monthly burn in USD as a plain number, or null if not stated>,
  "runway_months": <runway in months as a plain number, or null if not stated>,
  "claims": [
    {"claim": "<a specific, checkable statement from the text, near-verbatim>", "category": "financial|market|product|team|traction|legal|other"}
  ],
  "founders": [
    {"name": "<a person named in the text as a founder or executive>", "role": "<their stated title>", "background": "<their stated prior experience, verbatim-ish>"}
  ]
}
Rules:
- Consider EVERY slide's content, whatever its heading says. A slide titled
  "1-Click Car Service" is a product/solution slide; one titled "Progress to
  Date" is traction. Never skip a slide because its heading is not a word you
  expected -- headings carry no authority here, content does.
- A claim is any specific, checkable assertion the deck makes: a number, a
  named market or its size, a stated business model or revenue split, a named
  customer or launch city, a certification, a comparison, a growth rate, or a
  concrete product capability. It does NOT have to contain a digit.
- Cover the whole deck. If eight slides make substantive assertions, return
  claims drawn from all eight, not several from one.
- Never invent a number, name or fact that is not present in the text.
- If a field is not stated anywhere in the text, use null (for numbers) or an
  empty list (for claims). Do not guess.
- Return at most 14 claims, ranked by how verifiable/specific they are.
- For "founders", scan the ENTIRE text -- title slide, subtitles, captions,
  footers, body copy -- for real people named as founding, leading or raising
  for this company. A name in a title-slide subtitle such as
  "Pre-seed - Raised $200K (Ada Lovelace & Grace Hopper)" counts; so does
  "Jane Doe, Founder" set under a logo. A dedicated team slide is NOT
  required, and most decks do not have one.
- Only list a person the text actually names. Never infer a founder from the
  company name, and never supply a name you happen to know from outside this
  text: an invented name would be sent to a live web search and produce a
  background check on nobody.
- Set "role" to the title the text states, or "" if it states none."""


def extract_structured(text: str, company: str = "") -> dict[str, Any]:
    """Best-effort schema-validated extraction. Always returns a usable dict
    with `description`, `revenue`, `burn_rate`, `runway_months`, `claims`,
    and `_method` (one of "llm_schema", "regex_fallback", "empty") recording
    which path actually produced the result."""
    if not text or not text.strip():
        return {**_regex_fallback("", company), "_method": "empty"}

    reason = ""


    prompt = f"{_SCHEMA_PROMPT}\n\nDECK TEXT:\n{text[:8000]}"

    try:
        # Free-tier pacing -- see groq_client.TokenPacer.
        pace_for(len(prompt), 1600)
        response = get_client().chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract structured facts from startup pitch decks. "
                        "Output valid JSON only, matching the requested schema exactly."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=1600,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        parsed = ExtractedFinancials.model_validate(json.loads(raw))
        return {
            "description": parsed.description or text[:1200].strip(),
            "revenue": parsed.revenue,
            "burn_rate": parsed.burn_rate,
            "runway_months": parsed.runway_months,
            "claims": [c.claim for c in parsed.claims],
            "founders": [f.model_dump() for f in parsed.founders],
            "_method": "llm_schema",
        }
    except (json.JSONDecodeError, ValidationError) as exc:
        reason = f"invalid JSON/schema from the model: {exc}"
        logger.warning("Structured extraction %s; falling back to regex", reason)
    except (NameError, AttributeError, TypeError, ImportError) as exc:
        # These are bugs in this file, not provider trouble. Both used to land
        # in the same silent warning, so `pace_for(len(prompt), ...)` -- a
        # NameError on a variable that did not exist -- disabled this entire
        # code path on every call and still read as a degraded provider. Log
        # loudly enough that the next one does not survive an audit.
        reason = f"extraction bug ({type(exc).__name__}): {exc}"
        logger.error(
            "Structured extraction is BROKEN, not degraded: %s. Falling back "
            "to regex, which is materially worse. Fix this.",
            reason,
            exc_info=True,
        )
    except Exception as exc:
        reason = f"provider call failed: {type(exc).__name__}: {exc}"
        logger.warning("Structured extraction %s; falling back to regex", reason)

    return {
        **_regex_fallback(text, company),
        "_method": "regex_fallback",
        "_fallback_reason": reason,
    }


def _regex_fallback(text: str, company: str = "") -> dict[str, Any]:
    info = _regex_extractor.extract_company_info(text)
    claims = _regex_extractor.extract_claims_from_text(text)
    founders = _regex_extractor.extract_founders(text)

    # Deck metadata the score model consumes and nothing was producing.
    # `stage` and `sector` are the model's two largest levers -- 42 and 24
    # points of range -- and every analysis ever run passed "unknown" for both.
    # `deck_metadata` abstains rather than guesses: measured on the seven-deck
    # corpus it returns 3 correct values, 0 wrong, and 11 "not stated".
    from deck_metadata import extract as extract_metadata

    metadata = extract_metadata(text, company=company)
    return {
        **info,
        "claims": claims,
        "founders": founders,
        "stage": metadata.stage,
        "sector": metadata.sector,
        "team_size": metadata.team_size,
        "github_url": metadata.github_url,
        "domain": metadata.domain,
        "metadata_evidence": metadata.evidence,
    }
