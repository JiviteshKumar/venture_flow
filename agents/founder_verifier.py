"""Founder/team verification agent.

Cross-checks a claimed founder's background against public web evidence,
using the same search-then-judge pattern as `agents/claim_verifier.py` (this
module reuses that file's `search_web` / `fetch_page_text` helpers rather
than duplicating the scraping logic). Addresses the "cross-check team claims
against public records instead of trusting the deck" ship-list item.
"""
from __future__ import annotations

import json
import logging

from agents.claim_verifier import search_web
from groq_client import MODEL, get_client

logger = logging.getLogger(__name__)

VALID_ASSESSMENTS = {"CONSISTENT", "CONTRADICTS", "NOT_ENOUGH_INFO"}


def _search_founder(name: str, company: str) -> list[dict]:
    queries = [
        f'"{name}" {company} founder',
        f'"{name}" LinkedIn {company}',
        f'"{name}" background experience career',
    ]
    seen_urls: set[str] = set()
    results: list[dict] = []
    for query in queries:
        for r in search_web(query, max_results=5):
            if r["url"] and r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                results.append(r)
    return results


def _judge(name: str, company: str, deck_context: str, evidence: list[dict]) -> dict:
    evidence_block = "\n".join(
        f"[{i}] {r['title']}\nURL: {r['url']}\nSnippet: {r['snippet']}"
        for i, r in enumerate(evidence[:10], 1)
    )
    prompt = f"""You are a strict due-diligence researcher checking a founder's
public background, not a biographer -- be skeptical of coincidental name
matches (a common name may return evidence about a different person).

CLAIMED FOUNDER: {name}
COMPANY: {company or "not specified"}
PITCH DECK CONTEXT (may or may not mention this person's background): {deck_context[:1500] or "none provided"}

PUBLIC SEARCH EVIDENCE:
{evidence_block}

Assess whether the public evidence is:
- CONSISTENT: evidence plausibly corroborates this person having a relevant background (be specific about what it shows)
- CONTRADICTS: evidence conflicts with claims in the deck context, or with what a founder of this company would be expected to have
- NOT_ENOUGH_INFO: evidence is too thin, generic, or ambiguous (e.g. a common name) to conclude anything

Respond with ONLY valid JSON, no other text:
{{"assessment": "CONSISTENT", "confidence": 0.7, "evidence_summary": "2 sentences citing specific evidence, or explaining why evidence was insufficient"}}"""

    try:
        response = get_client().chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a skeptical due-diligence researcher. Respond with valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=400,
        )
        raw = response.choices[0].message.content.strip()
        if "```" in raw:
            for part in raw.split("```"):
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    raw = part
                    break
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]
        result = json.loads(raw)
        if result.get("assessment") not in VALID_ASSESSMENTS:
            result["assessment"] = "NOT_ENOUGH_INFO"
        return result
    except json.JSONDecodeError:
        return {"assessment": "NOT_ENOUGH_INFO", "confidence": 0.0, "evidence_summary": "Could not parse the assessment."}
    except Exception:
        logger.exception("Founder-verification judgment failed")
        return {"assessment": "NOT_ENOUGH_INFO", "confidence": 0.0, "evidence_summary": "Founder verification was temporarily unavailable."}


def verify_founder(name: str, company: str = "", deck_context: str = "") -> dict:
    """Never raises. Returns a dict with `available`; when True, also
    `assessment`, `confidence`, `evidence_summary`, and `sources`."""
    name = (name or "").strip()
    if not name:
        return {"available": False, "reason": "No founder name provided."}

    try:
        evidence = _search_founder(name, company)
    except Exception:
        logger.exception("Founder web search failed for %s", name)
        return {"available": False, "reason": "Web search was temporarily unavailable."}

    if not evidence:
        return {
            "available": True,
            "name": name,
            "assessment": "NOT_ENOUGH_INFO",
            "confidence": 0.0,
            "evidence_summary": "No public evidence found for this person.",
            "sources": [],
        }

    judgment = _judge(name, company, deck_context, evidence)
    return {
        "available": True,
        "name": name,
        "assessment": judgment.get("assessment", "NOT_ENOUGH_INFO"),
        "confidence": judgment.get("confidence", 0.0),
        "evidence_summary": judgment.get("evidence_summary", ""),
        "sources": [r["url"] for r in evidence[:5]],
    }


def verify_founders(names: list[str], company: str = "", deck_context: str = "") -> list[dict]:
    """Verify up to 3 founders (kept small -- each one is several web
    requests + an LLM call, and this runs inline in the diligence pipeline)."""
    return [verify_founder(name, company, deck_context) for name in (names or [])[:3]]
