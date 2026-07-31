import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import warnings
warnings.filterwarnings("ignore")

import json
from groq import Groq
from agents.claim_verifier import verify_claim
from agents.risk_detector import score_risk
from agents.investment_agents import run_investment_agents
from rag_engine import build_context, format_context_for_llm

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL  = "llama-3.3-70b-versatile"

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

    error_note = f"\n\nSynthesis note: Groq report generation failed ({synthesis_error}). This fallback memo uses deterministic pipeline outputs only." if synthesis_error else ""

    return f"""1. EXECUTIVE SUMMARY
{company_name} has been reviewed with {quality.get('quality', 'UNKNOWN')} data quality ({quality.get('score', 0)}/100). This memo should be treated as preliminary until unsupported claims and missing financials are verified.

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
Insufficient database evidence was available for a reliable comparable-company analysis.

6. RED FLAGS
{chr(10).join(f'- {item}' for item in red_flag_lines)}

7. GREEN FLAGS / POSITIVE SIGNALS
{chr(10).join(f'- {item}' for item in positive_lines)}

8. FINAL VERDICT
NEEDS MORE DILIGENCE. The available evidence is not strong enough for an investment decision without follow-up validation.

9. CONFIDENCE LEVEL
{min(75, max(20, quality.get('score', 50)))}%. Confidence is constrained by data quality and the number of independently verified claims.{error_note}"""

def assess_data_quality(
    claims_to_verify: list,
    company_description: str,
    filing_text: str,
    revenue: float,
) -> dict:
    """
    Before running expensive analysis, assess if we have
    enough data to produce a reliable report.
    Returns quality score and warnings.
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

    return {
        "quality":   quality,
        "score":     score,
        "warnings":  warnings_list,
        "can_proceed": score >= 30,
    }

def run_due_diligence(
    company_name:        str,
    company_description: str   = "",
    claims_to_verify:    list  = None,
    filing_text:         str   = "",
    revenue:             float = None,
    burn_rate:           float = None,
    runway_months:       float = None,
) -> dict:

    print(f"\n{'='*60}")
    print(f"VentureFlow AI — {company_name}")
    print(f"{'='*60}\n")

    report = {
        "company":  company_name,
        "sections": {}
    }

    # ── Pre-flight data quality check ──────────────────────────
    quality = assess_data_quality(
        claims_to_verify, company_description, filing_text, revenue
    )
    report["data_quality"] = quality
    print(f"Data quality: {quality['quality']} ({quality['score']}/100)")
    if quality["warnings"]:
        for w in quality["warnings"]:
            print(f"  Warning: {w}")

    if not quality["can_proceed"]:
        report["final_score"]    = 0
        report["recommendation"] = "INSUFFICIENT DATA — Please provide more company information"
        report["risk_level"]     = "UNKNOWN"
        report["sections"]["ai_analysis"] = (
            "Unable to complete due diligence. Insufficient data provided. "
            "Please upload the pitch deck or provide company description, "
            "claims to verify, and financial metrics."
        )
        return report

    # ── 1. Claim Verification ──────────────────────────────────
    print("[1/4] Verifying claims with web search + Groq AI...")
    claim_results = []
    if claims_to_verify:
        for claim in claims_to_verify[:5]:
            try:
                result = verify_claim(claim, verbose=True)
            except Exception as e:
                print(f"  Claim verification error: {e}")
                result = {
                    "claim": claim,
                    "verdict": "NOT_ENOUGH_INFO",
                    "confidence": 0.0,
                    "reasoning": f"Verification failed: {e}",
                    "key_evidence": "",
                    "sources": [],
                    "total_sources": 0,
                    "full_pages_read": 0,
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
    print("\n[2/4] Detecting risk signals...")
    risk_text   = filing_text or company_description
    try:
        risk_result = score_risk(risk_text, company=company_name)
    except Exception as e:
        print(f"  Risk analysis error: {e}")
        risk_result = {
            "risk_level": "UNKNOWN",
            "overall_risk_level": "UNKNOWN",
            "overall_score": 30,
            "key_concerns": [f"Risk analysis failed: {e}"],
            "positive_factors": [],
            "ai_reasoning": "Risk analysis unavailable.",
            "red_flags": [],
            "total_signals": 0,
        }
    risk_result["risk_level"] = risk_result.get("risk_level") or risk_result.get("overall_risk_level") or "UNKNOWN"
    risk_result["overall_score"] = risk_result.get("overall_score", 30)
    risk_result["key_concerns"] = risk_result.get("key_concerns") or []
    risk_result["positive_factors"] = risk_result.get("positive_factors") or []
    risk_result["red_flags"] = risk_result.get("red_flags") or []
    risk_result["total_signals"] = risk_result.get("total_signals", 0)
    report["sections"]["risk"] = risk_result

    print("\n[3/6] Running market, bull, bear and team analysis agents...")
    specialist_results = run_investment_agents(
        company=company_name,
        document=risk_text,
        claims=claim_results,
        risk=risk_result,
    )
    report["sections"].update(specialist_results)

    # ── 3. RAG Retrieval ───────────────────────────────────────
    print("\n[4/6] Retrieving database evidence...")
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
    except Exception as e:
        print(f"  RAG error: {e}")
        formatted_context = "Database context unavailable"
        rag_stats = {
            "claims_retrieved": 0,
            "docs_retrieved":   0,
            "sentiment_retrieved": 0
        }
    report["sections"]["rag_context"] = rag_stats

    # ── 4. Groq Synthesis ──────────────────────────────────────
    print("\n[5/6] Groq AI synthesizing report...")

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
    risk_score = risk_result.get("overall_score", 30)

    risk_str = (
        f"RISK ANALYSIS:\n"
        f"  Level: {risk_level} "
        f"(Score: {risk_score}/100)\n"
        f"  Key Concerns: {', '.join(risk_result.get('key_concerns', [])) or 'None identified'}\n"
        f"  Red Flags: {', '.join(risk_result.get('red_flags', [])) or 'None identified'}\n"
        f"  AI Reasoning: {risk_result.get('ai_reasoning', '')}\n"
    )

    quality_str = (
        f"DATA QUALITY: {quality['quality']} ({quality['score']}/100)\n"
        f"  Warnings: {'; '.join(quality['warnings']) or 'None'}\n"
    )

    user_message = f"""You are conducting due diligence on {company_name}.

COMPANY DESCRIPTION:
{company_description or filing_text or 'Not provided'}

{metrics_str}

{claims_str}

{risk_str}

{quality_str}

SPECIALIST ANALYSES (evidence-grounded):
{json.dumps(specialist_results, default=str)}

DATABASE EVIDENCE (similar companies from our financial database):
{formatted_context}

Write a professional investment memo with these exact sections.
For each section, clearly state what is EVIDENCED vs what is UNCERTAIN.
If data is missing for a section, say "Insufficient data" — do not invent numbers.

---
1. EXECUTIVE SUMMARY
(2-3 sentences. State the investment opportunity and your confidence level.)

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
If data quality is LOW, confidence must be below 60%.
---"""

    try:
        response = client.chat.completions.create(
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
        print(f"  Groq synthesis error: {e}")
        ai_analysis = _fallback_ai_analysis(
            company_name=company_name,
            quality=quality,
            claim_results=claim_results,
            risk_result=risk_result,
            revenue=revenue,
            burn_rate=burn_rate,
            runway_months=runway_months,
            synthesis_error=e,
        )

    report["sections"]["ai_analysis"] = ai_analysis

    # ── Final score ────────────────────────────────────────────
    # Penalise for: refuted claims, high risk, low data quality
    # ── Final score (safe key access) ─────────────────────────────
    claim_penalty = refuted * 15
    if len(claim_results) == 0:
        claim_penalty += 20
    elif supported == 0:
        claim_penalty += 10
    financial_penalty = 0 if revenue else 10
    quality_bonus = (quality["score"] - 50) * 0.2
    raw_score     = 100 - (risk_score * 0.5) - claim_penalty - financial_penalty + quality_bonus
    final_score   = max(0, min(100, raw_score))

    if len(claim_results) == 0 or supported < 2 or quality["quality"] == "LOW":
        recommendation = "NEEDS MORE DILIGENCE"
    elif final_score >= 75 and refuted == 0:
        recommendation = "INVEST"
    elif final_score >= 50:
        recommendation = "NEEDS MORE DILIGENCE"
    else:
        recommendation = "PASS"

    report["final_score"]    = round(final_score, 1)
    report["recommendation"] = recommendation
    report["risk_level"]     = risk_level

    print(f"\n{'='*60}")
    print(f"SCORE:          {final_score:.0f}/100")
    print(f"RECOMMENDATION: {recommendation}")
    print(f"RISK LEVEL:     {risk_level}")
    print(f"DATA QUALITY:   {quality['quality']}")
    print(f"{'='*60}")
    print("\nAI ANALYSIS:")
    print(ai_analysis)

    with open("due_diligence_report.json", "w") as f:
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
