import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Must precede the agent imports below: forces stdout/stderr to UTF-8 so their
# progress prints cannot raise UnicodeEncodeError on Windows. See
# console_safety.py -- this was silently killing risk analysis on every run.
from dotenv import load_dotenv

import console_safety  # noqa: F401  (imported for side effect)

load_dotenv()

import warnings

warnings.filterwarnings("ignore")

import json
import re

from agents.claim_verifier import verify_claim
from agents.investment_agents import run_investment_agents
from agents.risk_detector import score_risk
from groq_client import MODEL, get_client, pace_for
from rag_engine import build_context, format_context_for_llm

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are VentureFlow AI, a senior VC due diligence analyst at a top-tier firm.

CRITICAL RULES — breaking these makes the report worthless:
1. ONLY state facts that are directly evidenced by the provided data
2. If you don't have evidence for a claim, say "Insufficient data" — never guess
3. When claims are unverified, explicitly say so and lower your confidence
4. Never invent competitors, financials, team backgrounds, or market sizes
5. If a company has fewer than 2 verified claims, flag this prominently
6. Distinguish between "verified by web search" vs "stated in document only"

Your tone: direct, evidence-based, professional investment memo style."""

def _fallback_ai_analysis(
    company_name: str,
    quality: dict,
    claim_results: list,
    risk_result: dict,
    revenue: float,
    burn_rate: float,
    runway_months: float,
    synthesis_error: Exception = None,
    market_comparables: dict | None = None,
) -> str:
    verified = sum(1 for r in claim_results if r.get("verdict") == "SUPPORTS")
    refuted = sum(1 for r in claim_results if r.get("verdict") == "REFUTES")
    uncertain = sum(1 for r in claim_results if r.get("verdict") == "NOT_ENOUGH_INFO")
    risk_level = risk_result.get("risk_level") or risk_result.get("overall_risk_level") or "UNKNOWN"

    financial_lines = []
    financial_lines.append(f"- Annual revenue: ${revenue:,.0f}" if revenue else "- Annual revenue: Insufficient data")
    financial_lines.append(f"- Monthly burn: ${burn_rate:,.0f}" if burn_rate else "- Monthly burn: Insufficient data")
    financial_lines.append(f"- Runway: {runway_months} months" if runway_months else "- Runway: Insufficient data")

    concern_lines = risk_result.get("key_concerns") or ["Insufficient external evidence to identify specific concerns."]
    positive_lines = risk_result.get("positive_factors") or ["No independently verified positive factors found."]
    red_flag_lines = risk_result.get("red_flags") or ["None identified from available evidence."]

    # The comparables section of this memo used to be a hardcoded "insufficient
    # database evidence" line. It printed even when comparables.py had returned
    # five real matches, so the memo contradicted the Comparable Companies table
    # rendered a few inches below it in the same PDF.
    comparables = (market_comparables or {}).get("comparables") or []
    if comparables:
        comparable_lines = "\n".join(
            f"- {c.get('name')} ({c.get('industry', 'n/a')}, {c.get('batch', 'n/a')}) "
            f"-- {c.get('outcome', 'unknown outcome')}, "
            f"similarity {float(c.get('similarity') or 0):.2f}"
            for c in comparables[:5]
        )
    else:
        comparable_lines = (
            "Insufficient database evidence was available for a reliable "
            "comparable-company analysis."
        )

    error_note = (
        "\n\nSynthesis note: AI synthesis is temporarily unavailable. "
        "This preliminary memo uses the evidence collected so far."
        if synthesis_error
        else ""
    )

    # State extraction coverage in the memo itself, not only in a side panel.
    # The complaint this answers is that a reader saw a confident completeness
    # score in the prose and an incomplete claims table beneath it, with
    # nothing in the text connecting the two.
    coverage_pct = quality.get("extraction_coverage_pct")
    coverage_note = ""
    if coverage_pct is not None:
        coverage_note = (
            f" Extraction coverage for this deck was {coverage_pct}%"
            f" ({quality.get('extraction_verdict', 'UNKNOWN')})."
        )
        if quality.get("extraction_verdict") in {"LOW", "EMPTY"}:
            coverage_note += (
                " Most of the deck's slides did not reach a structured field, so"
                " gaps below may be parsing failures rather than gaps in the deck."
            )

    return f"""1. EXECUTIVE SUMMARY
{company_name} has been reviewed with {quality.get('quality', 'UNKNOWN')} input completeness ({quality.get('score', 0)}/100 -- a measure of whether the analysis inputs arrived, NOT of how much of the deck was parsed).{coverage_note} This memo should be treated as preliminary until unsupported claims and missing financials are verified.

2. CLAIM VERIFICATION ANALYSIS
- Claims checked: {len(claim_results)}
- Supported: {verified}
- Refuted: {refuted}
- Uncertain: {uncertain}

3. RISK ASSESSMENT
- Overall risk level: {risk_level}
- Risk score: {risk_result.get('overall_score', 30)}/100
- Key concerns: {'; '.join(concern_lines)}

4. FINANCIAL ANALYSIS
{chr(10).join(financial_lines)}

5. COMPARABLE COMPANIES
{comparable_lines}

6. RED FLAGS
{chr(10).join(f'- {item}' for item in red_flag_lines)}

7. GREEN FLAGS / POSITIVE SIGNALS
{chr(10).join(f'- {item}' for item in positive_lines)}

8. FINAL VERDICT
NEEDS MORE DILIGENCE. The available evidence is not strong enough for an investment decision without follow-up validation.

9. CONFIDENCE LEVEL
{min(75, max(20, quality.get('score', 50)))}%. Confidence is constrained by input completeness, extraction coverage and the number of independently verified claims.{error_note}"""

# The escapes below are word boundaries. This line previously held two
# LITERAL BACKSPACE BYTES (0x08) where those belong -- almost certainly an
# editor or paste accident, and invisible in every diff and review since,
# because a backspace renders as nothing at all.
#
# The pattern therefore demanded an actual control character either side of
# the year, matched no real text, and _infer_deck_vintage() returned "" for
# every deck ever analysed. Together with the argument-order bug fixed in
# api.py, that left claim verification with no temporal anchor whatsoever in
# production -- which is the grounding added specifically to stop the verifier
# judging a 2011 metric against 2026 evidence and calling growth a lie.
_YEAR_RE = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")


def _infer_deck_vintage(text: str) -> str:
    """Best guess at when a deck was written, or "" if there is no basis.

    Takes the EARLIEST plausible year, not the first one encountered.

    Measured across the seven-deck corpus, first-match inference was wrong on
    six of seven and wrong in one direction -- always too late: Airbnb's 2009
    deck inferred 2011, Mint's 2007 deck inferred 2012, Uber's 2008 deck
    inferred 2010. The later years come from copyright lines, re-publication
    stamps added by whoever re-hosted the file, and forward-looking market
    projections. The deck's own vintage is at or before every year it mentions
    as history, so the minimum is the better estimate.

    Still only a guess, and a wrong-but-historical year is far less harmful than
    none: the verifier's job here is to avoid reading a 2011 metric against 2026
    evidence, and any plausible past anchor achieves that. When nothing is
    found the prompt's unknown-date branch carries the same instruction
    explicitly.
    """
    years = [int(y) for y in _YEAR_RE.findall(text or "")]
    if not years:
        return ""
    return str(min(years))



# What `assess_data_quality` actually measures, in the words the report now
# uses. It was labelled "Data Quality", which a reader reasonably took to mean
# "we captured this deck correctly" -- and in the audit that prompted this
# pass, a report showed `HIGH data quality (100/100)` directly above a claims
# table holding two of a nine-slide deck's twenty content lines. The score was
# not wrong; it was answering a different question than the one its name
# implied. It asks whether the ANALYSIS INPUTS arrived, never whether the deck
# was read properly. `extraction_coverage` answers that second question, and
# the two are reported side by side so neither can stand in for the other.
INPUT_COMPLETENESS_LABEL = "Input Completeness"
INPUT_COMPLETENESS_MEASURES = (
    "Whether the analysis inputs were present: description length, how many "
    "claims were supplied, and whether revenue was given. This is NOT a "
    "measure of how much of the deck was successfully parsed -- see "
    "Extraction Coverage for that."
)


def assess_data_quality(
    claims_to_verify: list,
    company_description: str,
    filing_text: str,
    revenue: float,
    coverage: dict | None = None,
) -> dict:
    """Assess whether the analysis INPUTS are complete enough to proceed.

    Deliberately NOT a measure of extraction fidelity -- see
    `INPUT_COMPLETENESS_MEASURES` above and `extraction_coverage.py`. The
    returned `score` is unchanged by this pass because it feeds
    `_evidence_components`; only the naming, the warnings and the attached
    coverage context are new.
    """
    warnings_list = []
    score = 100

    # Check if we have any description
    combined_text = (company_description or "") + (filing_text or "")
    if len(combined_text) < 100:
        warnings_list.append("Very limited company description provided — analysis may be shallow")
        score -= 30

    # Check claims
    if not claims_to_verify or len(claims_to_verify) == 0:
        warnings_list.append("No specific claims provided — skipping claim verification")
        score -= 20
    elif len(claims_to_verify) < 2:
        warnings_list.append("Only 1 claim provided — limited verification coverage")
        score -= 10

    # Check financials
    if not revenue:
        warnings_list.append("No revenue data provided — financial analysis will be limited")
        score -= 15

    quality = "HIGH" if score >= 80 else "MEDIUM" if score >= 50 else "LOW"

    result = {
        "quality":   quality,
        "score":     score,
        "warnings":  warnings_list,
        "can_proceed": score >= 30,
        # Naming, so no reader can take this for a parsing-completeness score.
        "label":     INPUT_COMPLETENESS_LABEL,
        "measures":  INPUT_COMPLETENESS_MEASURES,
    }

    # Attach extraction coverage as adjacent context, never as an input to
    # `score`. A low-coverage warning is surfaced HERE as well as in its own
    # section, because this is the block a reader looks at when deciding
    # whether to trust an "insufficient data" verdict, and it is precisely the
    # place the old label misled them.
    if coverage and coverage.get("available"):
        result["extraction_coverage_pct"] = coverage.get("coverage_pct")
        result["extraction_verdict"] = coverage.get("verdict")
        if coverage.get("verdict") in {"LOW", "EMPTY"}:
            result["warnings"] = warnings_list + [
                f"Extraction coverage is {coverage.get('coverage_pct')}% "
                f"({coverage.get('represented_slides', 0)} of "
                f"{coverage.get('content_slides', 0)} content slides reached a "
                f"structured field). Findings below may be incomplete because "
                f"the deck was not fully parsed, not because the deck is thin."
            ]
    return result


def _safe_print(text: str) -> None:
    """Print LLM-authored text without letting the console encoding kill the
    run.

    Found by doing a live end-to-end run rather than a mocked one. On Windows
    sys.stdout defaults to the ANSI codepage (cp1252 here), and the memo
    regularly contains characters outside it -- the run that surfaced this
    contained U+2011 NON-BREAKING HYPHEN. A bare print() therefore raised
    UnicodeEncodeError *after* the report had been fully built, so a complete
    and correct report was destroyed on its way to the console. Worth being
    precise about the blast radius: this is console rendering only, and the
    returned dict and the persisted JSON were always fine -- but the
    exception propagated out of run_due_diligence(), so the caller lost the
    report anyway.
    """
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def _coerce_confidence(value: object) -> float:
    """Turn a specialist agent's self-reported confidence into a float in
    [0, 1], whatever shape the LLM decided to emit it in.

    This exists because of a real outage. The specialist-agent prompt asks
    for "keys confidence, ..." without ever stating that confidence must be
    numeric. Llama 3.3 happened to answer with numbers, so a bare
    float(result["confidence"]) worked for as long as that model was the
    only one used. When Groq decommissioned it and the app moved to
    openai/gpt-oss-120b, the new model started answering "confidence":
    "low" -- and float("low") raises ValueError, which propagated out of
    run_due_diligence() and failed the entire report. An LLM-authored field
    should never have been parsed with an unguarded float() in the first
    place; the prompt has also been tightened, but this coercion is the part
    that actually has to hold when a future model answers differently again.
    """
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        confidence = float(value)
    elif isinstance(value, str):
        text = value.strip().lower().rstrip("%")
        words = {"none": 0.0, "very low": 0.1, "low": 0.25, "medium": 0.5,
                 "moderate": 0.5, "high": 0.8, "very high": 0.95}
        if text in words:
            return words[text]
        try:
            confidence = float(text)
        except ValueError:
            return 0.0
        if "%" in value:
            confidence /= 100.0
    else:
        return 0.0
    # Models report this on a 0-1 scale or a 0-100 one depending on mood.
    if confidence > 1.0:
        confidence /= 100.0
    return max(0.0, min(1.0, confidence))


def _coerce_number(value: object, default: float) -> float:
    """Return a usable float from an LLM-authored numeric field.

    This exists because of the exact failure the product was shipping:

        File "ventureflow_agent.py", line 236, in _evidence_penalty
            penalty += max(0.0, min(0.20, (risk_score / 100.0) * 0.20))
        TypeError: unsupported operand type(s) for /: 'NoneType' and 'float'

    `risk_score` came from `risk_result.get("overall_score", 30)`, and that
    idiom does not do what it looks like it does here. The default applies only
    when the key is *absent*; when the risk agent returns the key with a null
    value -- which it does whenever its own LLM call fails, e.g. under a rate
    limit -- `.get` faithfully returns None, and the arithmetic downstream
    raises. The exception escaped every try/except in the pipeline and failed
    the whole job, which is exactly the degradation contract this codebase
    otherwise follows everywhere.

    Any number that originated in a model response has to be coerced rather
    than trusted; `.get(key, default)` is not a null guard.
    """
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%"))
        except ValueError:
            return default
    return default


def _evidence_components(
    refuted: int,
    supported: int,
    n_claims: int,
    risk_score: float,
    has_revenue: bool,
    quality_score: float,
    specialist_confidences: list[float] | None = None,
) -> dict[str, float]:
    """How much this report's own verified evidence should pull the model's
    prior down, broken out per term so the report can show its work.

    The VentureFlow Score model is trained on company characteristics and has
    never read this deck. Claim verification, risk detection and data quality
    are what the pipeline actually established about *this* company, so they
    have to reach the headline number somehow.

    This is intentionally a transparent bounded formula and not a second
    trained layer. Fitting one would require labelled data linking
    claim-verification outcomes to eventual company outcomes, and no such
    dataset exists -- inventing the relationship and calling it learned would
    be exactly the kind of thing this codebase refuses to do elsewhere. The
    weights below are a stated prior, are visible as `evidence_penalty` on
    every report, and should be replaced by a fitted layer once enough
    outcome-labelled reports accumulate to fit one honestly.
    """
    # Every argument here can originate in a model response, so all of them
    # are coerced. Guarding only risk_score -- the one that actually raised --
    # would leave the same landmine under the other three.
    refuted = int(_coerce_number(refuted, 0))
    supported = int(_coerce_number(supported, 0))
    n_claims = int(_coerce_number(n_claims, 0))
    risk_score = _coerce_number(risk_score, 30)
    quality_score = _coerce_number(quality_score, 50)

    components: dict[str, float] = {}

    # Each refuted claim is direct negative evidence about this company.
    components["refuted_claims"] = min(0.30, refuted * 0.10)

    # How much checkable evidence the deck offered at all, graded rather than
    # stepped. This used to be a flat +0.12 at n_claims == 0 and nothing at
    # n_claims == 1, which meant a deck with a single throwaway claim was
    # treated as materially better evidenced than one with none. The endpoints
    # are unchanged (0 claims still costs 0.12) so prior reports stay
    # comparable; what changed is that 1 and 2 now sit between the endpoints
    # instead of falling off a step.
    components["claim_sparsity"] = round(
        max(0.0, min(1.0, (3 - n_claims) / 3.0)) * 0.12, 4
    )

    # Of the claims that *were* checked, how many survived. Also graded: the
    # old rule fired only when supported == 0, so 1-of-8 supported and 8-of-8
    # supported were scored identically.
    if n_claims > 0:
        unsupported_fraction = max(0.0, min(1.0, 1.0 - (supported / float(n_claims))))
        components["claims_unsupported"] = round(unsupported_fraction * 0.10, 4)
    else:
        components["claims_unsupported"] = 0.0

    # What the specialist agents actually concluded, when they concluded
    # anything. Degraded agents are excluded by the caller: an agent that never
    # ran is not an agent that judged the company harshly, and conflating those
    # two is the exact defect this whole pass exists to remove. When every
    # specialist was degraded this term is 0.0 and the report says so
    # separately via `provider_degraded`.
    answered = [_coerce_confidence(c) for c in (specialist_confidences or []) if c is not None]
    if answered:
        mean_confidence = sum(answered) / len(answered)
        components["specialist_uncertainty"] = round(
            max(0.0, min(1.0, 1.0 - mean_confidence)) * 0.15, 4
        )
    else:
        components["specialist_uncertainty"] = 0.0

    components["risk_signals"] = round(max(0.0, min(0.20, (risk_score / 100.0) * 0.20)), 4)
    components["no_revenue"] = 0.0 if has_revenue else 0.05
    components["data_quality"] = round(
        max(-0.05, min(0.05, (50.0 - quality_score) / 500.0)), 4
    )
    return components


def _evidence_penalty(
    refuted: int,
    supported: int,
    n_claims: int,
    risk_score: float,
    has_revenue: bool,
    quality_score: float,
    specialist_confidences: list[float] | None = None,
) -> float:
    """Total evidence adjustment, as a probability delta in [0, 0.60].

    See `_evidence_components` for the per-term rationale. The 0.60 bound is a
    deliberate ceiling on how far this report's own evidence may move a trained
    model's prior -- 60 points is already an enormous deduction -- but it is a
    *bound*, not a target: the distribution of realised penalties across stored
    reports is checked in `ml/scripts/check_score_distribution.py` precisely so
    that a pile-up at the ceiling would be visible rather than silent. That is
    the failure mode the removed hard cap had.
    """
    total = sum(
        _evidence_components(
            refuted=refuted, supported=supported, n_claims=n_claims,
            risk_score=risk_score, has_revenue=has_revenue,
            quality_score=quality_score,
            specialist_confidences=specialist_confidences,
        ).values()
    )
    return max(0.0, min(0.60, total))


def _legacy_formula_score(
    refuted: int,
    supported: int,
    n_claims: int,
    risk_score: float,
    has_revenue: bool,
    quality_score: float,
) -> float:
    """The original hand-tuned scoring formula, retained only as the fallback
    for when the trained model cannot be loaded.

    It is not defensible as a primary score -- the constants were chosen by
    hand and never validated against an outcome -- but a working approximate
    score beats failing the report outright, which is why it stays.
    """
    refuted = int(_coerce_number(refuted, 0))
    supported = int(_coerce_number(supported, 0))
    n_claims = int(_coerce_number(n_claims, 0))
    risk_score = _coerce_number(risk_score, 30)
    quality_score = _coerce_number(quality_score, 50)

    claim_penalty = refuted * 15
    if n_claims == 0:
        claim_penalty += 20
    elif supported == 0:
        claim_penalty += 10
    financial_penalty = 0 if has_revenue else 10
    quality_bonus = (quality_score - 50) * 0.2
    raw = 100 - (risk_score * 0.5) - claim_penalty - financial_penalty + quality_bonus
    return max(0.0, min(100.0, raw))


def run_due_diligence(
    company_name:        str,
    company_description: str   = "",
    claims_to_verify:    list  = None,
    filing_text:         str   = "",
    revenue:             float = None,
    burn_rate:           float = None,
    runway_months:       float = None,
    sector:               str  = None,
    team_size:            int  = None,
    github_url:            str  = None,
    founders:             list = None,
    deck_date:            str  = "",
    stage:                str  = "",
    deck_slides:          list = None,
    extraction_method:    str  = "",
    extraction_fallback_reason: str = "",
    on_stage=None,
) -> dict:

    print(f"\n{'='*60}")
    print(f"VentureFlow AI — {company_name}")
    print(f"{'='*60}\n")

    report = {
        "company":  company_name,
        "sections": {}
    }

    def _stage(label: str) -> None:
        """Report the pipeline's real current step to the caller.

        api._run_analysis_job passes a callback that writes this to the job
        row, so the frontend can show what is actually happening instead of
        advancing labels on an unrelated fixed timer. Best-effort: a progress
        callback must never be able to fail an analysis.
        """
        print(f"[stage] {label}")
        if on_stage is not None:
            try:
                on_stage(label)
            except Exception:
                logger.debug("Stage callback failed for %r", label, exc_info=True)

    # ── Extraction coverage ────────────────────────────────────
    #
    # How much of the deck reached a structured field, measured before any
    # analysis runs. This is the number that separates "the deck said little"
    # from "we dropped most of what it said", which the report previously
    # could not distinguish at all -- both produced "insufficient data".
    # See extraction_coverage.py.
    from extraction_coverage import compute as _compute_coverage

    coverage = _compute_coverage(
        filing_text or company_description or "",
        {
            "description":   company_description,
            "claims":        claims_to_verify or [],
            "founders":      founders or [],
            "revenue":       revenue,
            "burn_rate":     burn_rate,
            "runway_months": runway_months,
            "sector":        sector,
            "team_size":     team_size,
        },
        deck_slides,
    )
    report["extraction_coverage"] = coverage
    report["sections"]["extraction_coverage"] = coverage

    # ── Which extraction path produced this report ──────────────
    #
    # The defect that started this whole body of work was a NameError in
    # structured_extractor that made the schema path raise on EVERY call. A
    # bare `except Exception` caught it, extraction silently fell back to
    # regex, and every analysis for an unknown number of weeks was produced by
    # the materially worse path with nothing anywhere saying so. It took a
    # manual audit against the original PDF to notice.
    #
    # The fix is not just to log it. A report has to be able to tell its own
    # reader which path produced it, because the reader is the person deciding
    # whether to trust the claims table -- and "this came from the regex
    # fallback" is exactly the caveat they need and could not previously get.
    provenance = {
        "method": extraction_method or "unknown",
        "is_fallback": extraction_method in {"regex_fallback", "empty"},
        "fallback_reason": extraction_fallback_reason or "",
    }
    if provenance["is_fallback"]:
        provenance["warning"] = (
            "This report's facts were extracted by the REGEX FALLBACK, not the "
            "schema-validated LLM extractor. The fallback captures materially "
            "less of a deck and misses phrasing the schema path handles. Treat "
            "claim counts and coverage below as a floor, not a measurement of "
            "the deck. Reason: " + (extraction_fallback_reason or "not recorded")
        )
        # Loud on purpose. A silent fallback is the original bug.
        logger.error(
            "EXTRACTION DEGRADED for %s: regex fallback was used instead of the "
            "schema extractor. Reason: %s",
            company_name, extraction_fallback_reason or "not recorded",
        )
        print(f"  !! EXTRACTION DEGRADED: {provenance['warning']}")
    elif extraction_method:
        print(f"Extraction method: {extraction_method}")
    report["extraction_provenance"] = provenance
    report["sections"]["extraction_provenance"] = provenance
    if coverage.get("available"):
        print(
            f"Extraction coverage: {coverage['coverage_pct']}% "
            f"({coverage.get('represented_slides', 0)}/"
            f"{coverage.get('content_slides', 0)} content slides) "
            f"[{coverage['verdict']}]"
        )
        if coverage["verdict"] in {"LOW", "EMPTY"}:
            print(f"  {coverage['interpretation']}")

    # ── Pre-flight input completeness check ────────────────────
    quality = assess_data_quality(
        claims_to_verify, company_description, filing_text, revenue, coverage
    )
    report["data_quality"] = quality
    print(
        f"{quality['label']}: {quality['quality']} ({quality['score']}/100)"
        f"  -- {quality['measures'][:60]}..."
    )
    if quality["warnings"]:
        for w in quality["warnings"]:
            print(f"  Warning: {w}")

    if not quality["can_proceed"]:
        report["final_score"]    = 0
        report["incomplete_analysis"] = True
        report["recommendation"] = "INSUFFICIENT DATA — Please provide more company information"
        report["risk_level"]     = "UNKNOWN"
        insufficient = (
            "Unable to complete due diligence. Insufficient data provided. "
            "Please upload the pitch deck or provide company description, "
            "claims to verify, and financial metrics."
        )
        # Never let this message stand alone when coverage says the content
        # was there and we lost it. That combination -- content present,
        # nothing extracted, report says "insufficient data" -- is the exact
        # failure this pass exists to make impossible to miss.
        if coverage.get("available") and coverage.get("verdict") in {"LOW", "EMPTY"}:
            insufficient += (
                f"\n\nIMPORTANT: extraction coverage for this deck was "
                f"{coverage['coverage_pct']}% "
                f"({coverage.get('represented_slides', 0)} of "
                f"{coverage.get('content_slides', 0)} content slides reached a "
                f"structured field). The deck may well contain the missing "
                f"information; this tool did not capture it. Do not read the "
                f"verdict above as a judgement about the company."
            )
        report["sections"]["ai_analysis"] = insufficient
        return report

    # ── 1. Claim Verification ──────────────────────────────────
    _stage("Verifying claims against live web search")
    claim_results = []
    if claims_to_verify:
        for claim in claims_to_verify[:5]:
            try:
                # The company name and deck context are what make a deck claim
                # searchable at all. Without them "Seed round target is $8M" is
                # a generic string, and retrieval returns generic pages -- see
                # the worked example in agents/claim_verifier.build_queries.
                result = verify_claim(
                    claim,
                    verbose=True,
                    company=company_name,
                    context=(company_description or "")[:600],
                    # The deck's vintage. Without it the verifier judges a 2011
                    # metric against 2026 evidence and calls growth a lie -- see
                    # the four wrong REFUTES documented in
                    # agents/claim_verifier.groq_judge.
                    as_of=deck_date or _infer_deck_vintage(filing_text or company_description),
                )
            except Exception:
                logger.exception("Claim verification failed")
                result = {
                    "claim": claim,
                    "verdict": "NOT_ENOUGH_INFO",
                    "confidence": 0.0,
                    "reasoning": "Claim verification was temporarily unavailable.",
                    "key_evidence": "",
                    "sources": [],
                    "total_sources": 0,
                    "full_pages_read": 0,
                    "_degraded": True,
                    "_degraded_reason": "claim verification raised",
                }
            claim_results.append(result)

    supported = sum(1 for r in claim_results if r["verdict"] == "SUPPORTS")
    refuted   = sum(1 for r in claim_results if r["verdict"] == "REFUTES")
    uncertain = sum(1 for r in claim_results if r["verdict"] == "NOT_ENOUGH_INFO")

    report["sections"]["claims"] = {
        "checked":   len(claim_results),
        "supported": supported,
        "refuted":   refuted,
        "uncertain": uncertain,
        "details":   claim_results,
        "reliability_note": (
            "HIGH — multiple claims verified"  if supported >= 2 and refuted == 0 else
            "MEDIUM — some claims unverified"   if uncertain > 0 else
            "LOW — claims refuted by evidence"  if refuted > 0 else
            "UNVERIFIED — no claims checked"
        )
    }

    # ── 2. Risk Detection ──────────────────────────────────────
    _stage("Detecting risk signals in the deck")
    risk_text   = filing_text or company_description
    try:
        risk_result = score_risk(risk_text, company=company_name)
    except Exception:
        logger.exception("Risk analysis failed")
        risk_result = {
            "risk_level": "UNKNOWN",
            "overall_risk_level": "UNKNOWN",
            "overall_score": 30,
            "key_concerns": ["Risk analysis was temporarily unavailable."],
            "positive_factors": [],
            "ai_reasoning": "Risk analysis unavailable.",
            "red_flags": [],
            "total_signals": 0,
            "_degraded": True,
            "_degraded_reason": "risk analysis raised",
        }
    risk_result["risk_level"] = risk_result.get("risk_level") or risk_result.get("overall_risk_level") or "UNKNOWN"
    risk_result["overall_score"] = _coerce_number(risk_result.get("overall_score"), 30)
    risk_result["key_concerns"] = risk_result.get("key_concerns") or []
    risk_result["positive_factors"] = risk_result.get("positive_factors") or []
    risk_result["red_flags"] = risk_result.get("red_flags") or []
    risk_result["total_signals"] = risk_result.get("total_signals", 0)
    report["sections"]["risk"] = risk_result

    # ── Financial state, computed deterministically from the deck ────────
    #
    # agents/deck_financials parses the quantities out of the deck and computes
    # the relationships between them -- runway, burn multiple, customer
    # concentration, growth. It runs inside score_risk, so the numbers arrive on
    # `risk_result`; they are lifted onto the report here because they are a
    # first-class finding about the company, not a by-product of risk scoring.
    #
    # It also BACKFILLS the three financial inputs. Those used to come solely
    # from the LLM structured extractor, which returns null whenever it does not
    # notice a figure or the provider is down -- so a deck that plainly states
    # $410K monthly burn against $1.1M cash could reach the scorer with no
    # financials at all, and be penalised for "no revenue data" on a page full
    # of it. Backfill is only ever additive: a value the caller supplied is
    # never overwritten, and every backfilled figure records that it was
    # derived rather than given.
    financial_state = risk_result.get("financial_state") or {}
    report["sections"]["financial_state"] = financial_state
    backfilled = []
    if not revenue and financial_state.get("annual_revenue"):
        revenue = float(financial_state["annual_revenue"])
        backfilled.append("revenue")
    if not burn_rate and financial_state.get("monthly_burn"):
        burn_rate = float(financial_state["monthly_burn"])
        backfilled.append("burn_rate")
    if not runway_months and financial_state.get("runway_months"):
        runway_months = float(financial_state["runway_months"])
        backfilled.append("runway_months")
    report["sections"]["financials_backfilled_from_deck"] = backfilled
    if backfilled:
        print(f"  Financial state read from the deck: {', '.join(backfilled)}")

    # Data quality was assessed before any of this existed, on the caller's
    # inputs alone. Re-assess once, so a deck whose financials were recovered
    # from its own text is not still marked down for not having them.
    if backfilled:
        quality = assess_data_quality(
            claims_to_verify, company_description, filing_text, revenue, coverage
        )
        report["data_quality"] = quality

    # ── Founder/team verification — additive, evidence-grounded ──
    #
    # See agents/founder_verifier.py. Runs BEFORE the specialist agents, on
    # purpose: it used to run after them, which meant the team analyst -- the
    # agent that produces the capability scores behind the Founder Analysis
    # radar -- never saw the one piece of independent, non-deck evidence about
    # the team that this pipeline gathers. It was scoring founders from the
    # deck alone, and on a deck with no team slide that means scoring them from
    # nothing. Moving this up costs nothing (the two are independent) and gives
    # the agent something real to reason over.
    #
    # `founders` is populated from the upload form, which pre-fills it from
    # structured_extractor's read of the deck's team slide. Empty stays a
    # legitimate answer -- most decks have no team slide -- and the report says
    # so rather than showing an unexplained empty chart.
    founder_discovery: dict = {"attempted": False}
    if founders:
        _stage("Checking founder backgrounds against public evidence")
        try:
            from agents.founder_verifier import verify_founders as _verify_founders
            founder_verification = _verify_founders(founders, company=company_name, deck_context=company_description)
            for entry in founder_verification:
                # Where the NAME came from, which is a different question from
                # where the background evidence came from. A partner reading
                # this needs to know whether the deck disclosed its team or
                # whether this tool went and found one.
                entry["origin"] = "deck"
                entry["origin_label"] = "Named in the deck"
        except Exception:
            logger.exception("Founder verification unavailable")
            founder_verification = []
    else:
        # ── Section B: the deck named nobody, so go and find out ──
        #
        # This used to be a dead end: "No founder names were submitted", full
        # stop, no background check possible. Most decks do not name their
        # team, so the tool's single most investor-relevant check was
        # unavailable on the majority of real inputs -- while the founders of
        # those companies are, almost always, public record.
        #
        # agents/founder_research.py does the search and enforces the
        # anti-fabrication guard (every returned name must appear verbatim in
        # retrieved source text). A confirmed "we searched and found nothing"
        # is a legitimate result and is reported as one; a plausible guess is
        # not, and cannot survive that module's grounding check.
        _stage("Searching public sources for undisclosed founders")
        try:
            from agents.founder_research import discover_founders
            founder_discovery = discover_founders(
                company_name,
                stage=stage or "",
                deck_date=deck_date or "",
                context=(company_description or filing_text or "")[:400],
            )
            founder_discovery["attempted"] = True
        except Exception:
            logger.exception("Founder discovery unavailable")
            founder_discovery = {
                "attempted": True,
                "found": False,
                "reason": "Founder research was temporarily unavailable.",
            }

        founder_verification = []
        if founder_discovery.get("found"):
            discovered = founder_discovery.get("founders", [])
            try:
                from agents.founder_verifier import verify_founders as _verify_founders
                founder_verification = _verify_founders(
                    [f["name"] for f in discovered],
                    company=company_name,
                    deck_context=company_description,
                )
            except Exception:
                logger.exception("Founder verification unavailable")
                founder_verification = []

            # Carry the discovery provenance onto each verified founder, so the
            # UI never blends "the deck told us this" with "we found this
            # ourselves". The two carry different weight in diligence and must
            # stay visibly distinct.
            sources_by_name = {
                f["name"]: f.get("discovery_sources", []) for f in discovered
            }
            for entry in founder_verification:
                entry["origin"] = "external_research"
                entry["origin_label"] = "Not in the deck - found by public search"
                entry["discovery_sources"] = sources_by_name.get(entry.get("name"), [])

    report["sections"]["founder_verification"] = founder_verification
    report["sections"]["founder_discovery"] = founder_discovery

    if founder_discovery.get("attempted"):
        if founder_discovery.get("found"):
            print(
                f"  Founders not in the deck; public search identified: "
                f"{', '.join(f['name'] for f in founder_discovery['founders'])}"
            )
        else:
            print(f"  Founder search: {founder_discovery.get('reason', 'not found')}")

    _stage("Running market, team, bull and bear agents")
    specialist_results = run_investment_agents(
        company=company_name,
        document=risk_text,
        claims=claim_results,
        risk=risk_result,
        founder_checks=founder_verification,
    )
    report["sections"].update(specialist_results)

    # ── Outcome Model — trained signal, additive only ───────────
    # This is the first real trained-and-evaluated model in the pipeline
    # (see ml/models/outcome_model_report.json for methodology and metrics).
    # It never blocks or overrides the rest of the analysis: if the model
    # file is missing/untrained, ml.inference returns available=False and
    # the report simply omits this section, same defensive pattern as every
    # other optional signal in this function.
    try:
        from ml.inference import score_company as _score_company
        ml_outcome = _score_company(
            text=(company_description or filing_text or "")[:2000],
            industry=sector or "unknown",
            team_size=team_size or 0,
        )
    except Exception:
        logger.exception("Outcome model unavailable")
        ml_outcome = {"available": False, "reason": "Outcome model raised an unexpected error."}
    report["sections"]["ml_outcome_model"] = ml_outcome

    # ── Technical/GitHub score — rule-based rubric, not a model ─
    # See technical_scoring.py's module docstring for why this is a
    # transparent rubric rather than a trained model. Additive and
    # never blocking, same defensive pattern as every other optional signal.
    if github_url:
        try:
            from technical_scoring import score_repo as _score_repo
            technical_score = _score_repo(github_url)
        except Exception:
            logger.exception("Technical/GitHub scoring unavailable")
            technical_score = {"available": False, "reason": "Technical scoring raised an unexpected error."}
    else:
        technical_score = {"available": False, "reason": "No GitHub URL was provided."}
    report["sections"]["technical_score"] = technical_score

    # ── Real comparable-company benchmarking ─────────────────────
    # See comparables.py / market_data.py. Additive, never blocks the report.
    try:
        from market_data import get_market_data_provider
        market_comparables = get_market_data_provider().comparables(company_description or filing_text or "")
    except Exception:
        logger.exception("Market comparables unavailable")
        market_comparables = {"available": False, "reason": "Comparable-company lookup raised an unexpected error."}
    report["sections"]["market_comparables"] = market_comparables

    # ── 3. RAG Retrieval ───────────────────────────────────────
    _stage("Retrieving evidence from prior reports")
    query = f"{company_name} {company_description[:200]} financial performance"
    try:
        rag_context       = build_context(query)
        formatted_context = format_context_for_llm(rag_context)
        # ``rag_engine.build_context`` returns completed diligence reports, not
        # the legacy claim/document/sentiment collections.  Keeping this mapping
        # aligned avoids a KeyError which used to turn every successful context
        # lookup into a misleading "RAG error" in the analysis logs.
        relevant_reports = rag_context.get("relevant_reports", [])
        rag_stats = {
            "reports_retrieved": len(relevant_reports),
        }
    except Exception:
        logger.exception("Report context retrieval failed")
        formatted_context = "Database context unavailable"
        rag_stats = {
            "claims_retrieved": 0,
            "docs_retrieved":   0,
            "sentiment_retrieved": 0
        }
    report["sections"]["rag_context"] = rag_stats

    # ── 4. Groq Synthesis ──────────────────────────────────────
    _stage("Writing the investment memo")

    # Build structured evidence summary for Groq
    metrics_str = "FINANCIAL METRICS:\n"
    metrics_str += f"  Annual Revenue: ${revenue:,.0f}\n"    if revenue        else "  Annual Revenue: Not provided\n"
    metrics_str += f"  Monthly Burn:   ${burn_rate:,.0f}\n"  if burn_rate      else "  Monthly Burn:   Not provided\n"
    metrics_str += f"  Runway:         {runway_months} months\n" if runway_months else "  Runway:         Not provided\n"

    claims_str = "CLAIM VERIFICATION RESULTS:\n"
    if claim_results:
        for cr in claim_results:
            icon = "VERIFIED" if cr["verdict"] == "SUPPORTS" else \
                   "REFUTED"  if cr["verdict"] == "REFUTES"  else "UNVERIFIED"
            claims_str += (
                f"  [{icon}] {cr['claim'][:120]}\n"
                f"    Confidence: {cr.get('confidence', 0):.0%} | "
                f"Sources checked: {cr.get('total_sources', 0)}\n"
                f"    Evidence: {cr.get('key_evidence', 'None')[:150]}\n\n"
            )
    else:
        claims_str += "  No claims provided for verification.\n"

    risk_level = risk_result.get("risk_level") or risk_result.get("overall_risk_level") or "MEDIUM"
    risk_score = _coerce_number(risk_result.get("overall_score"), 30)

    # The memo must be told the company's financial position explicitly, with
    # provenance. Left implicit, the LLM either omits runway entirely or invents
    # a figure -- and an invented runway is the most consequential hallucination
    # this product could ship.
    state_lines = []
    for key, label in (
        ("annual_revenue", "Annual revenue"), ("mrr", "MRR"), ("arr", "ARR"),
        ("monthly_burn", "Monthly burn"), ("cash_on_hand", "Cash on hand"),
        ("runway_months", "Runway (months)"), ("burn_multiple", "Burn multiple"),
        ("largest_customer_share", "Largest customer share of revenue"),
        ("growth_multiple", "Revenue growth multiple"),
    ):
        value = (risk_result.get("financial_state") or {}).get(key)
        if value is None:
            continue
        if key == "largest_customer_share":
            state_lines.append(f"  {label}: {value:.0%}")
        elif key in ("burn_multiple", "growth_multiple", "runway_months"):
            state_lines.append(f"  {label}: {value:g}")
        else:
            state_lines.append(f"  {label}: ${value:,.0f}")
    source = (risk_result.get("financial_state") or {}).get("runway_source")
    if state_lines:
        financial_state_str = (
            "FINANCIAL STATE (computed deterministically from the deck text, not by an LLM):\n"
            + "\n".join(state_lines)
            + (f"\n  Runway basis: {source}" if source else "")
            + "\n  These figures are parsed from the deck and each carries the sentence it "
              "came from. Treat them as stated-by-the-founder, not as independently verified.\n"
        )
    else:
        financial_state_str = (
            "FINANCIAL STATE: no financial quantities could be parsed from the deck text. "
            "Do NOT estimate revenue, burn or runway -- say they were not disclosed.\n"
        )

    risk_str = (
        f"RISK ANALYSIS:\n"
        f"  Level: {risk_level} "
        f"(Score: {risk_score}/100)\n"
        f"  Key Concerns: {', '.join(risk_result.get('key_concerns', [])) or 'None identified'}\n"
        f"  Red Flags: {', '.join(risk_result.get('red_flags', [])) or 'None identified'}\n"
        f"  AI Reasoning: {risk_result.get('ai_reasoning', '')}\n"
    )

    # ── VentureFlow Score — computed BEFORE synthesis, deliberately ──────
    # The ordering here is the whole point of this pass. The score used to be
    # computed after the LLM had already written the memo, which meant the
    # narrative was the source of the number's justification rather than an
    # explanation of it. Now the trained model produces the number first and
    # the number is handed to the LLM as a fact to explain. If this block is
    # ever moved back below the synthesis call, the product silently reverts
    # to LLM-authored scoring.
    specialist_confidences = [
        _coerce_confidence(result.get("confidence", 0))
        for result in specialist_results.values()
        if isinstance(result, dict)
    ]
    all_specialists_failed = bool(specialist_confidences) and all(
        confidence <= 0 for confidence in specialist_confidences
    )

    # Infrastructure failure is not a judgement about the company.
    #
    # This is the single most damaging defect this product has had. Measured
    # across 40 stored reports: 25 were score-capped, and 19 of those were
    # capped purely because Groq returned 429 to all four specialist agents.
    # The result was that 18 of 40 different startups scored an identical
    # 30/100 with an identical recommendation -- a due-diligence tool that
    # could not tell two decks apart, because an exhausted API quota was being
    # reported as a verdict.
    #
    # The VentureFlow Score does not read the specialists at all. It scores
    # company characteristics, and on 150 real YC companies it has a healthy
    # spread (8-86, sd 24.3, 50 distinct values across 150). When the LLM layer
    # falls over, that number is still the best estimate available and should
    # survive; what degrades is the *narrative*, not the score.
    #
    # So the cap is now reserved for the one case where the product genuinely
    # knows nothing about the company: no readable deck text at all. Everything
    # else is reported as degraded -- visibly, with the reason -- while keeping
    # the model's number and blocking a decisive INVEST/PASS.
    degraded_components = [
        {"component": name, "reason": result.get("_degraded_reason", "unknown")}
        for name, result in specialist_results.items()
        if isinstance(result, dict) and result.get("_degraded")
    ]
    # Detected on an explicit flag, never on the wording of a message.
    #
    # This block previously string-compared `reasoning` against "Claim
    # verification is temporarily unavailable." -- and there are TWO fallback
    # sites for a failed claim check, one here in the pipeline and one inside
    # agents/claim_verifier, wording it "was" and "is" respectively. Only the
    # "is" variant matched, so a claim that failed via the pipeline's own
    # exception handler was recorded at confidence 0.0 with `provider_degraded`
    # left False.
    #
    # Caught on the very first real deck run: Airbnb's "There are 10.6M trips
    # booked worldwide" came back "Claim verification was temporarily
    # unavailable" at confidence 0.0, and the report declared itself
    # not degraded. That is the original constant-score defect wearing a
    # different hat -- an infrastructure failure being counted as a finding
    # about the company -- reintroduced by matching on prose. The risk branch
    # had the same fault: it looked for "Error in analysis" while the
    # pipeline's own fallback writes "Risk analysis unavailable."
    for result in claim_results:
        if isinstance(result, dict) and result.get("_degraded"):
            degraded_components.append({
                "component": "claim_verification",
                "reason": result.get("_degraded_reason", "provider unavailable"),
            })
            break
    if risk_result.get("_degraded"):
        degraded_components.append({
            "component": "risk_analysis",
            "reason": risk_result.get("_degraded_reason", "provider unavailable"),
        })
    provider_degraded = bool(degraded_components)

    # Only the specialists that actually answered may push the score down. An
    # agent that never ran has expressed no opinion about the company, and
    # feeding its zero into the evidence term would resurrect -- quietly, and
    # in a harder place to see -- the exact confusion the marker above exists
    # to remove.
    answering_confidences = [
        _coerce_confidence(result.get("confidence", 0))
        for result in specialist_results.values()
        if isinstance(result, dict) and not result.get("_degraded")
    ]

    evidence_components = _evidence_components(
        refuted=refuted,
        supported=supported,
        n_claims=len(claim_results),
        risk_score=risk_score,
        has_revenue=bool(revenue),
        quality_score=quality["score"],
        specialist_confidences=answering_confidences,
    )
    evidence_penalty = max(0.0, min(0.60, sum(evidence_components.values())))
    report["sections"]["evidence_components"] = {
        name: round(value, 4) for name, value in evidence_components.items()
    }
    try:
        from ml.venturescore import blend_with_evidence
        from ml.venturescore import score_company as _venture_score
        venture_score_result = _venture_score(
            description=company_description or filing_text or "",
            one_liner=(company_description or "")[:120],
            industry=sector,
            # Was hardcoded None. Measured: sweeping stage across
            # Seed/Early/Growth moves the score 42 points -- more than industry
            # (24) and more than the entire text (25). Hardcoding it discarded
            # the model's largest single lever and is a direct cause of every
            # real deck landing in a 9-point band.
            stage=stage or None,
            location=None,
        )
        # Bidirectional evidence fusion.
        #
        # `_evidence_components` already fed claim verification, risk detection
        # and specialist confidence into the score -- the framing that they only
        # reached the memo was wrong. What was wrong was the ASYMMETRY. Measured
        # by sweeping the evidence inputs to their extremes:
        #
        #     worst-case evidence -> +0.785 penalty (clamped to 0.60, -60 points)
        #     best-case evidence  -> -0.025          (i.e. +2.5 points)
        #
        # A deck whose every claim was independently verified, with no risk
        # signals and disclosed financials, could earn 2.5 points, while a deck
        # with refuted claims lost 60. The pipeline could prove a company sound
        # and barely move the number.
        #
        # ml/evidence_fusion gives the positive direction real weight (up to
        # +20 points) while keeping the negative side dominant at -60, because
        # for a diligence tool the cost of missing a red flag exceeds the cost of
        # under-crediting a good deck. It is arithmetic over structured counts,
        # never over free text, so the memo still cannot author the number.
        try:
            from ml.evidence_fusion import extract_features, fuse

            fusion_features = extract_features(
                claim_results, risk_result, specialist_results,
                revenue=revenue, burn_rate=burn_rate, runway_months=runway_months,
            )
            fusion = fuse(
                venture_score_result.get("probability_exit_or_survive", 0.5),
                fusion_features,
            )
            # blend_with_evidence subtracts, so a positive delta is passed
            # negated. Reusing it keeps one code path for the range clamping and
            # the score_range shift.
            venture_score_result = blend_with_evidence(
                venture_score_result, -fusion["delta"],
            )
            venture_score_result["evidence_fusion"] = fusion
            report["sections"]["evidence_fusion"] = fusion
        except Exception:
            # Never let the fusion take down a report. Falling back to the
            # one-directional penalty is strictly the previous behaviour.
            logger.exception("Evidence fusion failed; falling back to the penalty term")
            venture_score_result = blend_with_evidence(venture_score_result, evidence_penalty)
    except Exception:
        logger.exception("VentureFlow Score model unavailable")
        venture_score_result = {"available": False, "reason": "VentureFlow Score raised an unexpected error."}
    # Say which scored inputs the deck did not supply.
    #
    # The score model's two largest levers are stage (42 points of range) and
    # industry (24). When a deck does not state them the model receives
    # "unknown" for both and the number it returns is a population prior with
    # very little of this company in it -- but the report used to present that
    # number identically to one computed from a fully-specified deck.
    #
    # This does not change the score. It changes what the report is willing to
    # claim about it, which is the honest half: a reader can see that the
    # biggest input was missing and discount accordingly.
    missing_inputs = []
    if not stage:
        missing_inputs.append({
            "input": "stage",
            "range_points": 42,
            "consequence": "The largest single input to the score. Without it the "
                           "model scores this deck as stage-unknown, which is a "
                           "population average rather than a read on this company.",
        })
    if not sector:
        missing_inputs.append({
            "input": "industry/sector",
            "range_points": 24,
            "consequence": "The second-largest input. Absent, the model cannot "
                           "place the company against its own sector's base rate.",
        })
    if missing_inputs:
        venture_score_result["missing_inputs"] = missing_inputs
        venture_score_result["degraded_inputs"] = True
        venture_score_result["degraded_note"] = (
            "This score was computed without "
            + " and ".join(m["input"] for m in missing_inputs)
            + ", which together account for up to "
            + str(sum(m["range_points"] for m in missing_inputs))
            + " points of the model's range. The deck did not state "
            + ("them" if len(missing_inputs) > 1 else "it")
            + ", and nothing was assumed in "
            + ("their" if len(missing_inputs) > 1 else "its")
            + " place. Treat the number as correspondingly less specific to this "
            + "company."
        )
    else:
        venture_score_result["degraded_inputs"] = False

    report["sections"]["venture_score"] = venture_score_result
    report["score_inputs_missing"] = [m["input"] for m in missing_inputs]

    if venture_score_result.get("available"):
        model_block = (
            "VENTUREFLOW SCORE (produced by a trained, calibrated model -- NOT by you):\n"
            f"  Score: {venture_score_result['venture_score']}/100 "
            f"(90% range {venture_score_result['score_range'][0]}-{venture_score_result['score_range'][1]})\n"
            f"  Model confidence: {venture_score_result['confidence']} "
            f"(feature coverage {venture_score_result['feature_coverage']:.0%}, "
            f"ensemble spread {venture_score_result['ensemble_std']:.3f})\n"
            f"  Base rate for comparable companies: {venture_score_result['base_rate']:.1%}\n"
            # Expressed in score POINTS, not as the underlying probability
            # delta. A live run showed the model reading "-0.17" as 0.17
            # points and reporting "67 - 0.17 = 66.8, rounded to 50", which
            # is arithmetic nonsense presented confidently to an investor.
            # The units have to be unambiguous in the prompt itself.
            f"  Model-only score before this report's evidence: "
            f"{venture_score_result.get('model_only_score')}/100\n"
            f"  Evidence adjustment applied: "
            f"-{venture_score_result.get('evidence_penalty', 0) * 100:.0f} points "
            f"(from refuted claims, risk signals and missing financials), giving "
            f"{venture_score_result.get('model_only_score')} - "
            f"{venture_score_result.get('evidence_penalty', 0) * 100:.0f} = "
            f"{venture_score_result['venture_score']}/100\n"
            f"  Model: {venture_score_result['model']['family']}, "
            f"CV ROC-AUC {venture_score_result['model']['cv_roc_auc']} "
            f"CI95 {venture_score_result['model']['cv_roc_auc_ci95']}, "
            f"ECE {venture_score_result['model']['cv_ece']}, "
            f"n={venture_score_result['model']['trained_n']}\n"
        )
    else:
        model_block = (
            "VENTUREFLOW SCORE: unavailable for this report "
            f"({venture_score_result.get('reason', 'unknown reason')}). "
            "Do not invent a score of your own -- say that the model score was unavailable.\n"
        )

    quality_str = (
        f"INPUT COMPLETENESS: {quality['quality']} ({quality['score']}/100)\n"
        f"  This measures whether the analysis INPUTS arrived (description "
        f"length, claim count, revenue present). It is NOT a measure of how "
        f"much of the deck was successfully parsed. Never describe it as "
        f"'data quality' and never present it as evidence that the deck was "
        f"read completely.\n"
        f"  Warnings: {'; '.join(quality['warnings']) or 'None'}\n"
    )
    coverage_block = ""
    if quality.get("extraction_coverage_pct") is not None:
        coverage_block = (
            f"EXTRACTION COVERAGE: {quality['extraction_coverage_pct']}% "
            f"({quality.get('extraction_verdict')})\n"
            f"  The share of the deck's content slides that reached a "
            f"structured field. If this is LOW, say so plainly in the memo and "
            f"attribute missing findings to incomplete parsing rather than to "
            f"the company.\n"
        )
    fallback_block = ""
    _prov = report.get("extraction_provenance") or {}
    if _prov.get("is_fallback"):
        fallback_block = (
            f"EXTRACTION METHOD: {_prov.get('method')} (DEGRADED FALLBACK)\n"
            f"  The facts below were extracted by a regex fallback, not the "
            f"schema extractor, because: {_prov.get('fallback_reason') or 'not recorded'}. "
            f"State plainly in the memo that extraction was degraded and that "
            f"missing findings may be extraction failures rather than gaps in "
            f"the deck.\n"
        )
    quality_str = quality_str + coverage_block + fallback_block

    user_message = f"""You are conducting due diligence on {company_name}.

COMPANY DESCRIPTION:
{company_description or filing_text or 'Not provided'}

{metrics_str}

{claims_str}

{risk_str}

{financial_state_str}

{quality_str}

{model_block}

SPECIALIST ANALYSES (evidence-grounded):
{json.dumps(specialist_results, default=str)}

DATABASE EVIDENCE (similar companies from our financial database):
{formatted_context}

Write a professional investment memo with these exact sections.
For each section, clearly state what is EVIDENCED vs what is UNCERTAIN.
If data is missing for a section, say "Insufficient data" — do not invent numbers.

CRITICAL — YOUR ROLE RELATIVE TO THE SCORE:
The VentureFlow Score above was produced by a trained, calibrated statistical
model, not by you. Your job is to EXPLAIN that number using the evidence in
this prompt — never to compute, override, or silently disagree with it.
- Do not state any overall score other than the one given above.
- If the evidence you see seems inconsistent with the model's score, say so
  explicitly and explain the tension. That disagreement is useful to an
  investor; quietly substituting your own number is not.
- Respect the model's stated confidence. If it says confidence is low, your
  memo must not read as decisive.

---
1. EXECUTIVE SUMMARY
(2-3 sentences. State the investment opportunity and your confidence level.)

1b. WHAT DRIVES THE VENTUREFLOW SCORE
(Explain the score above in plain language for an investor: what pulled it up,
what pulled it down, how much of the movement came from the evidence
adjustment vs. the model's own prior, and how much weight the stated
confidence and range justify placing on it.)

2. CLAIM VERIFICATION ANALYSIS
(For each claim: what the web says, whether it's verified, confidence %)

3. RISK ASSESSMENT
(List risks from HIGH to LOW. Cite specific evidence for each.)

4. FINANCIAL ANALYSIS
(Only discuss metrics that were provided. Mark anything unverified.)

5. COMPARABLE COMPANIES (from database)
(What does our database show about similar companies?)

6. RED FLAGS
(Bullet points. Only things with actual evidence. If none found, say "None identified.")

7. GREEN FLAGS / POSITIVE SIGNALS
(Bullet points. Only things with actual evidence.)

8. FINAL VERDICT
State one of: INVEST / PASS / NEEDS MORE DILIGENCE
Explain why in 2 sentences.

9. CONFIDENCE LEVEL
State 0-100%. Justify based on how much verified data you have.
If input completeness is LOW, or extraction coverage is LOW, confidence must be below 60%.
---"""

    try:
        # Free-tier pacing -- see groq_client.TokenPacer.
        pace_for(len(user_message), 2500)
        response = get_client().chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
            temperature=0.15,   # very low — maximise factual accuracy
            max_tokens=2500,
        )
        ai_analysis = response.choices[0].message.content
    except Exception as e:
        logger.exception("Groq report synthesis failed")
        ai_analysis = _fallback_ai_analysis(
            company_name=company_name,
            quality=quality,
            claim_results=claim_results,
            risk_result=risk_result,
            revenue=revenue,
            burn_rate=burn_rate,
            runway_months=runway_months,
            synthesis_error=e,
            market_comparables=market_comparables,
        )

    report["sections"]["ai_analysis"] = ai_analysis

    # ── Final score ────────────────────────────────────────────
    # The headline number comes from the trained, calibrated VentureFlow Score
    # model, already computed above (before synthesis, so the memo explains it
    # rather than authoring it). This block only turns that number into the
    # report's final_score and recommendation.
    #
    # The hand-tuned formula is kept, in _legacy_formula_score(), as the
    # fallback for when the model file is missing or fails to load. Falling
    # back to a worse-but-working score is correct here; failing the whole
    # report because a model file is absent is not, and would break the
    # degradation contract every other optional signal in this file follows.

    # "Nothing could be corroborated" and "the analysis did not run" are
    # different things, and conflating them made the product useless on the
    # deals it exists to evaluate.
    #
    # Found by running 20 real seed-stage decks through the pipeline. For an
    # early-stage company, public web search legitimately cannot corroborate
    # deck claims -- there is nothing written about the company yet, and the
    # verifier correctly refuses to credit same-name evidence about a
    # different business (checked directly: searching AgroPulse's claims
    # surfaces a real, unrelated agropulse.in). So every genuinely early deck
    # returned all-NOT_ENOUGH_INFO, which flipped `incomplete_analysis` and
    # hard-capped the score at 30. Twenty different startups scored 30/100
    # with the identical recommendation, and the trained model's estimate was
    # computed and then discarded every time. A due-diligence tool that
    # cannot rank one seed deck above another is not doing its job.
    #
    # `analysis_failed` now means exactly one thing: the product had no usable
    # input about this company -- no readable deck text at all, so there is
    # literally nothing to score and the honest output is a floor plus a
    # warning. Two things it deliberately no longer means:
    #
    #   1. "The LLM was down." That is `provider_degraded`, reported
    #      separately, and it no longer flattens the score.
    #   2. "The deck was thin." A content-free deck is a real and important
    #      signal, but it is a *graded* one and it is now priced through
    #      `_evidence_components()` -- specialist_uncertainty, claim_sparsity
    #      and claims_unsupported all rise smoothly as the deck says less.
    #
    # Point 2 is the part worth being careful about, because the obvious fix
    # to the constant-30 bug was to keep the cap and merely narrow when it
    # fires. That would have been the same defect with a smaller blast radius:
    # any hard cap maps a range of genuinely different decks onto one identical
    # number, which is precisely the behaviour that made 18 of 40 stored
    # reports read 30.0. A thin deck should therefore *fall*, not *snap*.
    #
    # What still holds the line on honesty: a thin deck cannot reach INVEST,
    # because `supported < 2` and the model's own low-confidence flag both
    # force NEEDS MORE DILIGENCE independently of the number.
    no_usable_input = not (risk_text or "").strip()
    analysis_failed = no_usable_input

    # Retained as a reported signal rather than a score lever. It is genuinely
    # interesting to a reader that every specialist that actually ran returned
    # zero confidence, and it is already priced into the score smoothly above.
    thin_evidence = (
        all_specialists_failed and not provider_degraded
    ) or not claim_results

    claims_unverified = bool(claim_results) and all(
        result.get("verdict") == "NOT_ENOUGH_INFO" for result in claim_results
    )
    incomplete_analysis = analysis_failed

    if venture_score_result.get("available"):
        final_score = float(venture_score_result["venture_score"])
        score_source = "venturescore_model"
    else:
        final_score = _legacy_formula_score(
            refuted=refuted, supported=supported, n_claims=len(claim_results),
            risk_score=risk_score, has_revenue=bool(revenue), quality_score=quality["score"],
        )
        score_source = "legacy_formula_fallback"

    # The ONLY surviving hard floor, and only for the one case where the
    # product genuinely knows nothing: there was no readable text. Anything
    # else keeps the model's number.
    if incomplete_analysis:
        final_score = min(final_score, 30)

    # A degraded run keeps the model's number -- the model did its job -- but is
    # never allowed to produce a decisive verdict, and says so on the report.
    if (provider_degraded or incomplete_analysis or thin_evidence
            or len(claim_results) == 0 or supported < 2
            or quality["quality"] == "LOW"):
        recommendation = "NEEDS MORE DILIGENCE"
    elif final_score >= 75 and refuted == 0:
        recommendation = "INVEST"
    elif final_score >= 50:
        recommendation = "NEEDS MORE DILIGENCE"
    else:
        recommendation = "PASS"

    # A low-confidence model score should not produce a decisive INVEST/PASS.
    # The model itself says when it does not have enough observed input to
    # justify one, and that judgement is respected here rather than overridden.
    if venture_score_result.get("confidence") == "low" and recommendation in ("INVEST", "PASS"):
        recommendation = "NEEDS MORE DILIGENCE"

    report["final_score"]    = round(final_score, 1)
    report["score_source"]   = score_source
    report["recommendation"] = recommendation
    report["risk_level"]     = risk_level
    report["incomplete_analysis"] = incomplete_analysis
    # Reported separately from incomplete_analysis so the UI can say which of
    # the two actually happened. "We searched and found nothing conclusive"
    # is a finding a VC should see stated plainly; "our pipeline broke" is a
    # different message entirely.
    report["claims_unverified"] = claims_unverified
    # Third, distinct state: the pipeline ran and the model scored the company,
    # but one or more LLM-backed components could not be reached. The score
    # stands (the model never depended on them); the narrative around it is
    # thinner, and the report says which parts and why rather than silently
    # presenting a diminished analysis as a complete one.
    report["provider_degraded"] = provider_degraded
    report["degraded_components"] = degraded_components
    # Fourth state, and the one that replaced the hard cap: the pipeline ran
    # fine and the company simply gave it very little to work with. Graded into
    # the score, reported as a flag, and blocked from a decisive verdict.
    report["thin_evidence"] = thin_evidence
    report["evidence_penalty"] = round(evidence_penalty, 4)

    # ── Firm-personalization ranking — mechanism, not yet active ─
    # See ml/personalization.py: this stays unavailable, honestly, until
    # enough of the user's own invest/pass decisions exist to fit on. Placed
    # here deliberately, after final_score is set, so it scores the report
    # that's actually returned rather than an in-progress one.
    try:
        from ml.personalization import personalize as _personalize
        personalized_ranking = _personalize(report)
    except Exception:
        logger.exception("Personalization layer unavailable")
        personalized_ranking = {"available": False, "reason": "Personalization layer raised an unexpected error."}
    report["sections"]["personalized_ranking"] = personalized_ranking

    print(f"\n{'='*60}")
    print(f"SCORE:          {final_score:.0f}/100")
    print(f"RECOMMENDATION: {recommendation}")
    print(f"RISK LEVEL:     {risk_level}")
    print(f"INPUT COMPLETENESS: {quality['quality']} ({quality['score']}/100)")
    _cov = report.get("extraction_coverage") or {}
    if _cov.get("available"):
        print(f"EXTRACTION COVERAGE: {_cov['coverage_pct']}% [{_cov['verdict']}]")
    print(f"{'='*60}")
    print("\nAI ANALYSIS:")
    _safe_print(ai_analysis)

    # encoding="utf-8" here for the same reason as _safe_print: the memo
    # routinely contains characters the Windows default codepage cannot
    # represent, and the default open() mode would raise on write.
    with open("due_diligence_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print("\nReport saved to due_diligence_report.json")

    return report

if __name__ == "__main__":
    run_due_diligence(
        company_name="CarbonCycle",
        company_description="""
        CarbonCycle is a direct air capture company achieving $80/tonne CO2 removal,
        10x cheaper than the $400-$1000 industry benchmark. Uses electrochemical
        process requiring 60% less energy than amine-based systems. Proprietary
        sorbent developed at MIT with 50,000 cycle lifespan. Pilot has removed 847
        tonnes over 14 months at 94.2% uptime. $18M in signed LOIs from Microsoft,
        Stripe Climate, and 3 EU corporates. Raising $8M Seed at $32M pre-money.
        Runway: 36 months post-raise. Monthly burn: $220K.
        """,
        claims_to_verify=[
            "CarbonCycle achieves direct air capture at $80 per tonne of CO2.",
            "Current direct air capture costs $400 to $1000 per tonne industry wide.",
            "The IPCC requires 10 billion tonnes of carbon removed annually by 2050.",
            "CarbonCycle's process uses 60% less energy than amine-based systems.",
        ],
        revenue=0,
        burn_rate=220_000,
        runway_months=36,
    )
