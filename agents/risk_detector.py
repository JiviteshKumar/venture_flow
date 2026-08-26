import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import json
from ddgs import DDGS

from agents.deck_financials import analyse as analyse_financials
from groq_client import MODEL, get_client

# ----------------------------
# Risk keyword dictionary
# ----------------------------
RISK_SIGNALS = {
    "financial_risk": [
        "revenue decline", "net loss", "cash burn", "going concern",
        "debt covenant", "liquidity risk", "impairment", "write-down",
        "restatement", "material weakness", "negative cash flow",
        "insolvency", "bankruptcy", "default"
    ],
    "legal_risk": [
        "litigation", "lawsuit", "SEC investigation", "regulatory action",
        "class action", "subpoena", "indictment", "fraud allegation",
        "patent infringement", "antitrust", "criminal charges", "settlement"
    ],
    "operational_risk": [
        "key person", "supply chain", "customer concentration",
        "data breach", "cybersecurity", "product recall",
        "manufacturing defect", "quality control", "system outage"
    ],
    "market_risk": [
        "market share loss", "competitive pressure", "pricing pressure",
        "demand decline", "market saturation", "disruptive technology",
        "industry headwinds", "regulatory change", "tariff"
    ],
    "management_risk": [
        "CEO resignation", "executive departure", "board conflict",
        "governance failure", "insider selling", "related party",
        "conflict of interest", "whistleblower", "misconduct"
    ],
}

# ----------------------------
# Web search
# ----------------------------
def search_company_risks(company: str) -> list:
    query = f"{company} risk lawsuit fraud SEC investigation 2024 2025"
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=8):
                results.append({
                    "title":   r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url":     r.get("href", ""),
                })
    except Exception as e:
        print(f"  Search error: {e}")
    return results

# ----------------------------
# Signal detection
# ----------------------------
def detect_signals(text: str) -> dict:
    text_lower = text.lower()
    detected   = {}

    for category, signals in RISK_SIGNALS.items():
        found = []
        for signal in signals:
            if signal.lower() in text_lower:
                idx     = text_lower.find(signal.lower())
                context = text[max(0, idx-80):idx+120].strip()
                found.append({"signal": signal, "context": context})
        if found:
            detected[category] = found

    return detected

# ----------------------------
# AI Risk Analysis
# ----------------------------
def groq_risk_analysis(company: str, text_signals: dict,
                       web_signals: dict, web_snippets: list,
                       source_text: str = "") -> dict:
    """Judge risk from the deck/filing text plus keyword and web signals.

    `source_text` was added on 23 Aug 2026 after `ml/scripts/eval_risk_detector.py`
    measured this function for the first time. It had never received the
    document at all -- only the *output* of `detect_signals()`, i.e. the list
    of phrases the keyword dictionary had already matched. The consequence is
    the opposite of what the architecture claims: the LLM could not find any
    risk the keyword list had not already found, and on a document where the
    dictionary matched nothing it was asked to assess a company it had been
    told nothing about. It answered accordingly, returning
    `overall_risk_level: "UNKNOWN"` with a null score on 13 of the 28 labeled
    benchmark excerpts -- including a pitch-deck paragraph disclosing 78%
    customer concentration and one disclosing an unresolved IP dispute with a
    departed founder, neither of which uses any dictionary phrase.

    Defaulted to "" rather than made required so existing callers keep working;
    both live call sites pass it.
    """
    relevant_snippets = [
        r for r in web_snippets
        if company.lower() in r.get("title", "").lower()
        or company.lower() in r.get("snippet", "").lower()
    ]

    snippets_to_use = relevant_snippets if relevant_snippets else []
    no_web_data = len(relevant_snippets) == 0

    snippets_block = "\n".join([
        f"- {r['title']}: {r['snippet'][:200]}"
        for r in snippets_to_use[:8]
    ]) if snippets_to_use else f"No web results specifically about {company} found."

    document_block = (
        source_text[:6000] if source_text and source_text.strip()
        else "No document text was supplied."
    )

    prompt = f"""You are a senior risk analyst at a top VC firm.
Analyze ONLY the risk profile for: {company}

CRITICAL:
- Only report risks about {company}
- Ignore other companies completely
- Do NOT hallucinate risks
- Judge the DOCUMENT TEXT itself, not just the pre-matched keyword signals.
  The keyword signals are a lexical pre-pass and miss risks stated in plain
  language (customer concentration, short runway, founder departure, unclear
  IP ownership). Read the document for those.
- Generic risk-factor boilerplate, safe-harbour language and standard
  accounting-policy notes are NOT red flags. Language such as "could have a
  material adverse effect" or "we face intense competition", with no specific
  adverse event disclosed, is routine and must not raise the risk level.
- Always return a concrete "overall_risk_level" of LOW, MEDIUM or HIGH and a
  numeric "overall_score" from 0 to 100. Never return null and never return
  "UNKNOWN": if the document discloses nothing adverse, that is LOW, not
  unknown.

DOCUMENT TEXT:
{document_block}

KEYWORD SIGNALS MATCHED IN THAT TEXT:
{json.dumps(text_signals, indent=2) if text_signals else "None found"}

WEB DATA:
{snippets_block}

{"NOTE: No web data found. Judge from the document text alone." if no_web_data else ""}

Respond with ONLY valid JSON:
{{
  "overall_risk_level": "MEDIUM",
  "overall_score": 35,
  "key_concerns": [],
  "positive_factors": [],
  "ai_reasoning": "",
  "red_flags": []
}}"""

    try:
        response = get_client().chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Strict risk analysis. JSON only."},
                {"role": "user", "content": prompt}
            ],
            # Constrained JSON output and a larger budget, for the same reason
            # agents/investment_agents.py already uses them: the current model
            # spends part of its completion budget on an internal reasoning
            # trace, so a budget tuned for Llama 3.3 truncates the answer.
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=1500,
        )

        raw = (response.choices[0].message.content or "").strip()
        if not raw:
            raise ValueError(
                f"empty completion (finish_reason={response.choices[0].finish_reason})"
            )

        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]

        result = json.loads(raw)

        return result

    except Exception as e:
        print(f"  Groq risk error: {e}")
        return {
            "overall_risk_level": "UNKNOWN",
            "overall_score": 30,
            "key_concerns": [],
            "positive_factors": [],
            "ai_reasoning": "Error in analysis",
            "_degraded": True,
            "_degraded_reason": "risk analysis provider call failed",
            "red_flags": [],
        }

# ----------------------------
# MAIN WRAPPER (FIXED)
# ----------------------------
def score_risk(text: str, company: str = "") -> dict:
    print(f"\n🔍 Running risk analysis for: {company}")

    # 1. Detect signals from input text.
    #
    # Two detectors, deliberately. RISK_SIGNALS is a dictionary of SEC-filing
    # vocabulary and it is genuinely good at what it was built for -- F1 0.815
    # on ml/eval/risk_benchmark.jsonl. What it cannot do is read a pitch deck:
    # measured on the same benchmark it missed ALL THREE deck-register red
    # flags, because a founder writes "our anchor customer represents $1.9M of
    # that figure" rather than "customer concentration", and "monthly burn is
    # $410K against $1.1M cash on hand" rather than "going concern".
    #
    # agents/deck_financials covers that register by parsing the quantities and
    # computing the relationships between them. It composes with the dictionary
    # rather than replacing it, because the two are strong on different document
    # types and the pipeline sees both.
    text_signals = detect_signals(text)

    financials = analyse_financials(text)
    for signal in financials["signals"]:
        text_signals.setdefault(signal["category"], []).append({
            "signal": signal["signal"],
            "context": signal["context"],
            "severity": signal["severity"],
            "detector": signal["detector"],
            "why": signal["why"],
        })

    # 2. Fetch web results
    web_results = search_company_risks(company)

    # 3. Detect signals from web snippets
    web_text = " ".join([r["snippet"] for r in web_results])
    web_signals = detect_signals(web_text)

    # 4. Run AI analysis
    result = groq_risk_analysis(
        company=company,
        text_signals=text_signals,
        web_signals=web_signals,
        web_snippets=web_results,
        source_text=text,
    )

    # 5. Add signal count (fixed logic)
    total_text_signals = sum(len(v) for v in text_signals.values())
    total_web_signals  = sum(len(v) for v in web_signals.values())

    # Normalize the AI response to the contract consumed by the API/UI.
    # Older prompts returned overall_risk_level; the frontend expects risk_level.
    result["risk_level"] = result.get("risk_level") or result.get("overall_risk_level") or "MEDIUM"
    result["overall_score"] = result.get("overall_score", 30)
    result["key_concerns"] = result.get("key_concerns") or []
    result["positive_factors"] = result.get("positive_factors") or []
    result["red_flags"] = result.get("red_flags") or []
    result["ai_reasoning"] = result.get("ai_reasoning") or "Risk analysis completed from available evidence."
    result["total_signals"] = total_text_signals + total_web_signals

    # The company's financial position, computed rather than asked for. Carried
    # on the risk result so the report can state runway, burn multiple and
    # customer concentration as facts derived from the deck, each with the
    # sentence it came from, instead of leaving them to an LLM that may or may
    # not have noticed them.
    result["financial_state"] = financials["state"]
    result["financial_metrics"] = financials["metrics"]
    result["deck_signals"] = financials["signals"]

    return result
