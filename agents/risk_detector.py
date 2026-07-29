import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import json
from ddgs import DDGS
from groq import Groq

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL  = "llama-3.3-70b-versatile"

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
                       web_signals: dict, web_snippets: list) -> dict:

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

    prompt = f"""You are a senior risk analyst at a top VC firm.
Analyze ONLY the risk profile for: {company}

CRITICAL:
- Only report risks about {company}
- Ignore other companies completely
- Do NOT hallucinate risks

TEXT SIGNALS:
{json.dumps(text_signals, indent=2) if text_signals else "None found"}

WEB DATA:
{snippets_block}

{"NOTE: No web data found. Use only text." if no_web_data else ""}

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
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Strict risk analysis. JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=800,
        )

        raw = response.choices[0].message.content.strip()

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
            "red_flags": [],
        }

# ----------------------------
# MAIN WRAPPER (FIXED)
# ----------------------------
def score_risk(text: str, company: str = "") -> dict:
    print(f"\n🔍 Running risk analysis for: {company}")

    # 1. Detect signals from input text
    text_signals = detect_signals(text)

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
        web_snippets=web_results
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

    return result
