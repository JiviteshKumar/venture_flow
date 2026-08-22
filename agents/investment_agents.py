"""Evidence-grounded specialist agents for VentureFlow investment analysis."""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from groq_client import MODEL, get_client

logger = logging.getLogger(__name__)


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
- "confidence" MUST be a bare number between 0 and 1 (e.g. 0.35).
  Never write it as a word such as "low"/"medium"/"high", never as a
  percentage string, and never omit it.

EVIDENCE:
{evidence[:5000]}
"""
    # 5,000 chars, not the 14,000 this used to send. A real pitch deck's
    # extracted text is 1,300-1,500 chars; the rest of the old budget was the
    # JSON dump of the risk object, which is mostly structure the agent does
    # not need. Four agents times 14,000 chars was ~14k tokens of input per
    # report against an 8,000-token-per-minute ceiling, spent on padding.
    # response_format=json_object, and a larger token budget, because both
    # specialist agents were failing on real runs in two distinct ways:
    #
    #   json.decoder.JSONDecodeError: Expecting ',' delimiter: line 8 column 6
    #   json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
    #
    # The first is a truncated object -- max_tokens=1000 cut the JSON off
    # mid-structure. The current model (openai/gpt-oss-120b) is a reasoning
    # model that spends part of its completion budget on an internal reasoning
    # trace before emitting content, so a budget tuned for Llama 3.3 no longer
    # leaves room for the answer. The second is an empty completion, the same
    # cause taken to its limit. Both degraded to a confidence-0 fallback, so
    # bull and bear analysis silently vanished from finished reports.
    #
    # Groq supports constrained JSON output for this model (verified against
    # the live API), which removes the malformed-output class entirely rather
    # than parsing around it.
    try:
        result = get_client().chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Return strict JSON only; do not use markdown."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=2000,
        )
        choice = result.choices[0]
        raw = (choice.message.content or "").strip()
        if not raw:
            logger.warning(
                "Specialist agent %s returned empty content (finish_reason=%s); using fallback",
                role, choice.finish_reason,
            )
            return fallback
        if choice.finish_reason == "length":
            # Truncated despite the larger budget -- the object is unparseable
            # by definition, so say so plainly rather than logging a confusing
            # JSONDecodeError for what is really a budget problem.
            logger.warning("Specialist agent %s hit the token limit; using fallback", role)
            return fallback
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else fallback
    except Exception:
        logger.exception("Specialist agent failed: %s", role)
        return fallback


def _evidence_block(document: str, claims: list[dict[str, Any]], risk: dict[str, Any]) -> str:
    claim_lines = [
        f"- {claim.get('verdict', 'UNKNOWN')}: {claim.get('claim', '')}"
        for claim in claims
    ]
    # Python < 3.12 does not allow a backslash inside an f-string expression,
    # so the join has to happen on its own line before the f-string is built.
    claims_block = "\n".join(claim_lines) or "No claims were extracted."
    return (
        f"PITCH DECK TEXT:\n{document or 'No readable deck text.'}\n\n"
        f"CLAIM RESULTS:\n{claims_block}\n\n"
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
    # Run the specialists with limited concurrency rather than all four at once.
    #
    # These are independent analyses, so firing them in parallel is the obvious
    # design and was the original one. It does not survive Groq's free-tier
    # limit of 8,000 tokens per minute: four agents times a large evidence
    # block plus 1,000 output tokens each is roughly 18,000 tokens arriving in
    # the same instant, so most of the batch is rejected and falls back to
    # confidence-0 stubs. Because every agent degrades quietly, the report
    # still renders -- with nothing in it.
    #
    # Two workers keeps some overlap for latency while spreading the token
    # spend over the rate-limit window, and the SDK's Retry-After handling
    # (see groq_client.MAX_RETRIES) absorbs what still collides. Raise
    # GROQ_AGENT_CONCURRENCY if you move to a paid tier with real headroom.
    concurrency = max(1, int(os.environ.get("GROQ_AGENT_CONCURRENCY", "2")))
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(concurrency, len(jobs))) as executor:
        futures = {executor.submit(_json_agent, role, task, evidence, fallback): name for name, (role, task, fallback) in jobs.items()}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return results
