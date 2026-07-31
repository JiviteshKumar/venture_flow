"""Evidence-grounded specialist agents for VentureFlow investment analysis."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from groq import Groq

MODEL = "llama-3.3-70b-versatile"
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))


def _json_agent(role: str, task: str, evidence: str, fallback: dict[str, Any]) -> dict[str, Any]:
    """Run one specialist and return a safe fallback on provider/JSON failure."""
    prompt = f"""You are the {role} in a VC due-diligence team.

{task}

RULES:
- Use only the supplied deck evidence and claim-verification results.
- Never invent a market size, founder background, customer, competitor, or metric.
- If evidence is absent, use "Insufficient data" and lower confidence.
- Every non-empty finding must include a short verbatim evidence excerpt.
- Return ONLY valid JSON matching the requested shape.

EVIDENCE:
{evidence[:14000]}
"""
    try:
        result = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Return strict JSON only; do not use markdown."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=1000,
        )
        raw = result.choices[0].message.content.strip()
        raw = raw[raw.find("{") : raw.rfind("}") + 1]
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else fallback
    except Exception:
        return fallback


def _evidence_block(document: str, claims: list[dict[str, Any]], risk: dict[str, Any]) -> str:
    claim_lines = [
        f"- {claim.get('verdict', 'UNKNOWN')}: {claim.get('claim', '')}"
        for claim in claims
    ]
    return (
        f"PITCH DECK TEXT:\n{document or 'No readable deck text.'}\n\n"
        f"CLAIM RESULTS:\n{'\n'.join(claim_lines) or 'No claims were extracted.'}\n\n"
        f"RISK SIGNALS:\n{json.dumps(risk, default=str)[:3000]}"
    )


def run_investment_agents(company: str, document: str, claims: list[dict[str, Any]], risk: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Run independent bull, bear, market and team specialists in parallel."""
    del company  # Company identity is already included in supplied deck evidence.
    evidence = _evidence_block(document, claims, risk)
    jobs = {
        "market": (
            "market-validation analyst",
            "Assess market definition, buyer/problem evidence, growth signals and competition mentioned in the deck. Return JSON with keys confidence, market_definition, signals (finding/evidence), gaps, recommendation.",
            {"confidence": 0, "market_definition": "Insufficient data", "signals": [], "gaps": ["Insufficient market evidence in the deck."], "recommendation": "Validate market size and buyer demand."},
        ),
        "team": (
            "founder and team diligence analyst",
            "Assess only team capabilities, hiring gaps and execution evidence present in the deck. Return JSON with keys confidence, overall_assessment, capabilities (area/score/evidence), strengths, gaps, questions.",
            {"confidence": 0, "overall_assessment": "Insufficient team information", "capabilities": [], "strengths": [], "gaps": ["Deck does not provide enough team evidence."], "questions": ["Provide founder biographies and relevant operating experience."]},
        ),
        "bull_case": (
            "bull-case investment analyst",
            "Build the strongest evidence-backed investment case. Include only verified claims or direct deck evidence. Return JSON with keys confidence, thesis, signals (finding/evidence), conditions_to_invest.",
            {"confidence": 0, "thesis": "Insufficient evidence for a bull case", "signals": [], "conditions_to_invest": ["Verify key commercial and product claims."]},
        ),
        "bear_case": (
            "bear-case investment analyst",
            "Build the strongest evidence-backed downside case using refuted/unverified claims, red flags and missing evidence. Return JSON with keys confidence, thesis, signals (finding/evidence), diligence_required.",
            {"confidence": 0, "thesis": "Insufficient evidence for a complete bear case", "signals": [], "diligence_required": ["Validate financials, market demand and team execution."]},
        ),
    }
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
        futures = {executor.submit(_json_agent, role, task, evidence, fallback): name for name, (role, task, fallback) in jobs.items()}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return results
