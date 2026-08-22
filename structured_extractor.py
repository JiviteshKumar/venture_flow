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
from groq_client import MODEL, get_client

logger = logging.getLogger(__name__)


class ExtractedClaim(BaseModel):
    claim: str = Field(min_length=10, max_length=300)
    category: Literal[
        "financial", "market", "product", "team", "traction", "legal", "other"
    ] = "other"


class ExtractedFinancials(BaseModel):
    description: str = ""
    revenue: float | None = Field(default=None, ge=0)
    burn_rate: float | None = Field(default=None, ge=0)
    runway_months: float | None = Field(default=None, ge=0, le=600)
    claims: list[ExtractedClaim] = Field(default_factory=list, max_length=8)


_SCHEMA_PROMPT = """Return ONLY a JSON object with this exact shape, no prose, no markdown fences:
{
  "description": "<1-2 sentence company summary from the text>",
  "revenue": <annualized revenue in USD as a plain number, or null if not stated>,
  "burn_rate": <monthly burn in USD as a plain number, or null if not stated>,
  "runway_months": <runway in months as a plain number, or null if not stated>,
  "claims": [
    {"claim": "<a specific, checkable statement from the text, near-verbatim>", "category": "financial|market|product|team|traction|legal|other"}
  ]
}
Rules:
- Only include claims that state a specific, checkable fact: a number, a
  named certification, a named customer, a comparison, a growth rate.
- Never invent a number that is not present in the text.
- If a field is not stated anywhere in the text, use null (for numbers) or an
  empty list (for claims). Do not guess.
- Return at most 6 claims, ranked by how verifiable/specific they are."""


def extract_structured(text: str) -> dict[str, Any]:
    """Best-effort schema-validated extraction. Always returns a usable dict
    with `description`, `revenue`, `burn_rate`, `runway_months`, `claims`,
    and `_method` (one of "llm_schema", "regex_fallback", "empty") recording
    which path actually produced the result."""
    if not text or not text.strip():
        return {**_regex_fallback(""), "_method": "empty"}

    try:
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
                {"role": "user", "content": f"{_SCHEMA_PROMPT}\n\nDECK TEXT:\n{text[:8000]}"},
            ],
            temperature=0.0,
            max_tokens=900,
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
            "_method": "llm_schema",
        }
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning(
            "Structured extraction returned invalid JSON/schema, falling back to regex: %s",
            exc,
        )
    except Exception as exc:
        logger.warning(
            "Structured extraction LLM call failed, falling back to regex: %s", exc
        )

    return {**_regex_fallback(text), "_method": "regex_fallback"}


def _regex_fallback(text: str) -> dict[str, Any]:
    info = _regex_extractor.extract_company_info(text)
    claims = _regex_extractor.extract_claims_from_text(text)
    return {**info, "claims": claims}
