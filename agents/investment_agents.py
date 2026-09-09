"""Evidence-grounded specialist agents for VentureFlow investment analysis."""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import observability
from groq_client import note_provider_failure, MODEL, get_client, pace_for, settle_usage

logger = logging.getLogger(__name__)


def _describe_provider_failure(exc: Exception) -> str:
    """Name the infrastructure failure so downstream can tell it from a real
    low-confidence answer."""
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    if "rate_limit" in lowered or "429" in lowered:
        return "provider rate limit / quota exhausted"
    if "timeout" in lowered or "timed out" in lowered:
        return "provider timeout"
    if "connection" in lowered or "network" in lowered:
        return "provider unreachable"
    if "authentication" in lowered or "401" in lowered or "api key" in lowered:
        return "provider credentials rejected"
    return f"provider error ({type(exc).__name__})"


def _degraded(fallback: dict[str, Any], reason: str) -> dict[str, Any]:
    """Tag a fallback so the pipeline can distinguish an INFRASTRUCTURE failure
    from a genuine confidence-0 judgement about the company.

    Without this marker the two are identical downstream -- both are a dict
    with confidence 0 -- and `ventureflow_agent` treated the pair the same,
    capping the headline score at 30. Measured on 40 stored reports: 25 were
    capped and 19 of those were capped purely because Groq returned 429 to all
    four agents. The product was reporting an exhausted API quota as a verdict
    on the company, and 18 of 40 decks scored an identical 30/100 as a result.
    """
    out = dict(fallback)
    out["_degraded"] = True
    out["_degraded_reason"] = reason
    # Aggregated, not just logged. These are the events that matter most and
    # crash-only error tracking sees none of them: the code caught the
    # exception, degraded politely, and returned a plausible answer.
    observability.track_degradation(
        "specialist_fallback", component=out.get("_component", "specialist_agent"),
        reason=reason,
    )
    return out


def _json_agent(role: str, task: str, evidence: str, fallback: dict[str, Any]) -> dict[str, Any]:
    """Run one specialist and return a safe fallback on provider/JSON failure."""
    prompt = f"""You are the {role} in a VC due-diligence team.

{task}

RULES:
- Use only the supplied deck evidence and claim-verification results.
- Never invent a market size, founder background, customer, competitor, or metric.
- If evidence is absent, say "Insufficient data".
- Every non-empty finding must include a short verbatim evidence excerpt.
- Return ONLY valid JSON matching the requested shape.

WHAT "confidence" MEANS HERE -- read this before choosing a number.

`confidence` is NOT how promising the company is, NOT how strong your case is,
and NOT how likely the company is to succeed. It is one thing only:

    the fraction of THIS assessment that rests on specific, quotable evidence
    in the material above, rather than on your own general knowledge or
    inference about companies of this kind.

A devastating bear case built entirely on quoted deck text is HIGH confidence.
An enthusiastic bull case built on plausible reasoning about the category is LOW
confidence. The number describes your evidence, not your conclusion.

Calibration anchors -- pick the band that matches, then a value inside it:

  0.85-1.00  Nearly every finding quotes the deck verbatim, and the load-bearing
             numbers were checked by claim verification.
  0.60-0.84  Most findings quote the deck, but key figures are unverified or
             the deck states them without support.
  0.35-0.59  Roughly half your assessment is quoted evidence; the rest is
             reasonable inference about this kind of company.
  0.15-0.34  Little quotable evidence. You are mostly reasoning from general
             knowledge of the category.
  0.00-0.14  No usable evidence for this specific question.

What counts as evidence, and what does not. This distinction decides the number.

EVIDENCE is a checkable particular: a figure, a date, a named customer or
partner, a headcount, a named prior employer, a stated contract term. Something
a diligence analyst could go and verify, and could be wrong about.

NOT EVIDENCE, however literally the deck says it: adjectives and claims of
significance -- "massive market", "transformative technology", "passionate
team", "strong relationships", "early traction has been encouraging", "uniquely
positioned". Quoting one of these verbatim does not make it evidence. It is the
deck asserting a conclusion, which is the thing you are supposed to assess.

Three rules that make this checkable:
- If your `signals` list is empty, confidence MUST be below 0.15.
- Confidence above 0.60 requires at least two findings whose excerpts each
  contain a checkable particular as defined above.
- A deck consisting mainly of adjectives and claims of significance, with few or
  no figures, dates or named entities, MUST score below 0.35 however
  enthusiastically it is written and however faithfully you quote it.

- "confidence" MUST be a bare number between 0 and 1 (e.g. 0.35).
  Never write it as a word such as "low"/"medium"/"high", never as a
  percentage string, and never omit it.
- "confidence_basis" MUST be one short sentence naming what you counted: how
  many of your findings carry a checkable particular (and what kind -- figures,
  dates, named entities), and what you had to infer. Counting bare quotes is
  not enough; say what the quotes actually contained.

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
        # Stay inside the free tier's 8,000 tokens/minute. Without this the
        # pipeline bursts its whole budget in seconds and every later call
        # 429s, which is how six of six real deck runs came back degraded.
        pace_for(len(prompt), 2000)
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
        # Return the completion budget this call reserved but did not use.
        # Bookkeeping only -- it cannot change what the model said, and it
        # stops the next call waiting on tokens nobody spent.
        settle_usage(result, len(prompt), 2000)
        choice = result.choices[0]
        raw = (choice.message.content or "").strip()
        if not raw:
            logger.warning(
                "Specialist agent %s returned empty content (finish_reason=%s); using fallback",
                role, choice.finish_reason,
            )
            return _degraded(fallback, f"empty completion (finish_reason={choice.finish_reason})")
        if choice.finish_reason == "length":
            # Truncated despite the larger budget -- the object is unparseable
            # by definition, so say so plainly rather than logging a confusing
            # JSONDecodeError for what is really a budget problem.
            logger.warning("Specialist agent %s hit the token limit; using fallback", role)
            return _degraded(fallback, "response truncated at the token limit")
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else _degraded(fallback, "response was not a JSON object")
    except Exception as exc:
        logger.exception("Specialist agent failed: %s", role)
        # Tell the daily-quota breaker, so the remaining components in
        # this run fail fast with an accurate reason instead of each
        # spending six retries rediscovering the same exhausted quota.
        note_provider_failure(exc)
        return _degraded({**fallback, "_component": role}, _describe_provider_failure(exc))


def _evidence_block(
    document: str,
    claims: list[dict[str, Any]],
    risk: dict[str, Any],
    founder_checks: list[dict[str, Any]] | None = None,
) -> str:
    claim_lines = [
        f"- {claim.get('verdict', 'UNKNOWN')}: {claim.get('claim', '')}"
        for claim in claims
    ]
    # Python < 3.12 does not allow a backslash inside an f-string expression,
    # so the join has to happen on its own line before the f-string is built.
    claims_block = "\n".join(claim_lines) or "No claims were extracted."

    # Founder background checks (agents/founder_verifier.py). This is the only
    # evidence about the team in this pipeline that does not come from the deck
    # the founders wrote, so withholding it from the team analyst -- which is
    # what happened until 23 Aug 2026, because verification ran after the
    # agents -- left that agent grading a team on its own self-description, or
    # on nothing at all when the deck had no team slide.
    founder_lines = [
        f"- {check.get('name', 'unknown')}: {check.get('assessment', 'NOT_ENOUGH_INFO')} "
        f"(confidence {check.get('confidence', 0)}) -- {check.get('evidence_summary', '')}"
        for check in (founder_checks or [])
        if check.get("available")
    ]
    founders_block = "\n".join(founder_lines) or (
        "No founder names were submitted, so no independent background check was run."
    )

    return (
        f"PITCH DECK TEXT:\n{document or 'No readable deck text.'}\n\n"
        f"CLAIM RESULTS:\n{claims_block}\n\n"
        f"FOUNDER BACKGROUND CHECKS (independent web evidence):\n{founders_block}\n\n"
        f"RISK SIGNALS:\n{json.dumps(risk, default=str)[:3000]}"
    )


def run_investment_agents(
    company: str,
    document: str,
    claims: list[dict[str, Any]],
    risk: dict[str, Any],
    founder_checks: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Run independent bull, bear, market and team specialists in parallel."""
    del company  # Company identity is already included in supplied deck evidence.
    evidence = _evidence_block(document, claims, risk, founder_checks)
    jobs = {
        "market": (
            "market-validation analyst",
            "Assess market definition, buyer/problem evidence, growth signals and competition mentioned in the deck. Return JSON with keys confidence, market_definition, signals (finding/evidence), gaps, recommendation.",
            {"confidence": 0, "confidence_basis": "No specialist output was produced.", "market_definition": "Insufficient data", "signals": [], "gaps": ["Insufficient market evidence in the deck."], "recommendation": "Validate market size and buyer demand."},
        ),
        "team": (
            "founder and team diligence analyst",
            "Assess team capabilities, hiring gaps and execution evidence. Use both the deck text and the FOUNDER BACKGROUND CHECKS section, which is independent web evidence about the named founders. "
            "Return JSON with keys confidence, confidence_basis, overall_assessment, capabilities (area/score/evidence), strengths, gaps, questions. "
            "`capabilities` must hold 4-6 named capability areas scored 0-100 (for example Technical Depth, Domain Experience, Commercial Execution, Prior Startup Experience, Team Completeness), each with a short verbatim evidence excerpt. "
            "Return capabilities as an empty list ONLY when there is genuinely no team evidence of any kind -- a scored area with nothing behind it is worse than an absent one.",
            {"confidence": 0, "confidence_basis": "No specialist output was produced.", "overall_assessment": "Insufficient team information", "capabilities": [], "strengths": [], "gaps": ["Deck does not provide enough team evidence."], "questions": ["Provide founder biographies and relevant operating experience."]},
        ),
        "bull_case": (
            "bull-case investment analyst",
            "Build the strongest evidence-backed investment case. Include only verified claims or direct deck evidence. Return JSON with keys confidence, confidence_basis, thesis, signals (finding/evidence), conditions_to_invest.",
            {"confidence": 0, "confidence_basis": "No specialist output was produced.", "thesis": "Insufficient evidence for a bull case", "signals": [], "conditions_to_invest": ["Verify key commercial and product claims."]},
        ),
        "bear_case": (
            "bear-case investment analyst",
            "Build the strongest evidence-backed downside case using refuted/unverified claims, red flags and missing evidence. Return JSON with keys confidence, confidence_basis, thesis, signals (finding/evidence), diligence_required.",
            {"confidence": 0, "confidence_basis": "No specialist output was produced.", "thesis": "Insufficient evidence for a complete bear case", "signals": [], "diligence_required": ["Validate financials, market demand and team execution."]},
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
