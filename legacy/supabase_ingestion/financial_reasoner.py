from dotenv import load_dotenv
load_dotenv()

import json, re
from duckduckgo_search import DDGS
from sentence_transformers import SentenceTransformer, util
from base import supabase

embedder = SentenceTransformer("sentence-transformers/all-mpnet-base-v2")

def search_financial_data(query: str, max_results: int = 5) -> list:
    """Search for financial data and news."""
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", ""),
                })
    except Exception as e:
        print(f"Search error: {e}")
    return results

def extract_numbers(text: str) -> list[float]:
    """Extract all numbers from text."""
    # Match numbers like $1.2M, 45%, 3.5B, etc.
    patterns = [
        r'\$?([\d,]+\.?\d*)\s*[Bb]illion',
        r'\$?([\d,]+\.?\d*)\s*[Mm]illion',
        r'([\d,]+\.?\d*)%',
        r'\$([\d,]+\.?\d*)',
        r'([\d,]+\.?\d+)',
    ]
    numbers = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for m in matches:
            try:
                num = float(m.replace(",", ""))
                numbers.append(num)
            except:
                pass
    return numbers

def calculate_financial_metric(
    operation: str,
    values: list[float]
) -> dict:
    """Perform basic financial calculations."""
    if not values:
        return {"error": "No values provided"}

    results = {
        "operation": operation,
        "inputs": values,
    }

    if operation == "growth_rate" and len(values) >= 2:
        old, new = values[0], values[1]
        if old != 0:
            rate = ((new - old) / abs(old)) * 100
            results["result"] = round(rate, 2)
            results["interpretation"] = f"{rate:.1f}% {'increase' if rate > 0 else 'decrease'}"

    elif operation == "sum":
        results["result"] = sum(values)

    elif operation == "average":
        results["result"] = sum(values) / len(values)

    elif operation == "ratio" and len(values) >= 2:
        if values[1] != 0:
            results["result"] = round(values[0] / values[1], 3)

    elif operation == "margin" and len(values) >= 2:
        revenue, profit = values[0], values[1]
        if revenue != 0:
            margin = (profit / revenue) * 100
            results["result"] = round(margin, 2)
            results["interpretation"] = f"{margin:.1f}% margin"

    return results

def answer_financial_question(question: str) -> dict:
    """
    Answer financial questions by:
    1. Searching database for relevant QA pairs
    2. Searching web for current data
    3. Extracting and calculating numbers
    """
    print(f"  Question: {question[:80]}...")

    # 1. Search our TAT-QA database for similar questions
    result = supabase.table("qa_pairs")\
        .select("question,answer,answer_type,answer_scale")\
        .eq("source", "tat_qa")\
        .limit(500)\
        .execute()

    db_answer = None
    if result.data:
        q_tensor = embedder.encode(question, convert_to_tensor=True)
        db_qs = [r["question"] for r in result.data]
        db_embs = embedder.encode(db_qs, convert_to_tensor=True)
        sims = util.cos_sim(q_tensor, db_embs)[0]
        best_idx = int(sims.argmax())
        best_sim = float(sims[best_idx])

        if best_sim > 0.70:
            match = result.data[best_idx]
            db_answer = {
                "answer": match["answer"],
                "type": match["answer_type"],
                "scale": match["answer_scale"],
                "similarity": best_sim,
            }

    # 2. Search web for current data
    web_results = search_financial_data(question)
    web_context = " ".join([r["snippet"] for r in web_results[:3]])

    # 3. Extract numbers from web context
    numbers = extract_numbers(web_context)

    # 4. Build response
    response = {
        "question": question,
        "db_match": db_answer,
        "web_sources": [r["url"] for r in web_results[:3]],
        "web_context": web_context[:500],
        "extracted_numbers": numbers[:10],
    }

    # Use DB answer if high confidence, otherwise use web
    if db_answer and db_answer["similarity"] > 0.80:
        response["final_answer"] = db_answer["answer"]
        response["answer_source"] = "database"
        response["confidence"] = db_answer["similarity"]
    elif web_context:
        response["final_answer"] = web_context[:300]
        response["answer_source"] = "web_search"
        response["confidence"] = 0.5
    else:
        response["final_answer"] = "Insufficient data to answer"
        response["answer_source"] = "none"
        response["confidence"] = 0.0

    return response

def analyze_startup_financials(
    company_name: str,
    revenue: float = None,
    burn_rate: float = None,
    runway_months: float = None,
) -> dict:
    """
    Full due diligence financial analysis for a startup.
    Searches web for benchmarks and compares.
    """
    print(f"\nAnalyzing financials for: {company_name}")

    # Search for industry benchmarks
    search_results = search_financial_data(
        f"{company_name} revenue growth ARR funding valuation 2024 2025"
    )

    web_text = " ".join([r["snippet"] for r in search_results])
    web_numbers = extract_numbers(web_text)

    analysis = {
        "company": company_name,
        "provided_metrics": {},
        "web_intelligence": {
            "sources": [r["url"] for r in search_results[:3]],
            "context": web_text[:600],
            "numbers_found": web_numbers[:10],
        },
        "red_flags": [],
        "positive_signals": [],
        "recommendation": "",
    }

    # Analyze provided metrics
    if revenue is not None:
        analysis["provided_metrics"]["revenue"] = revenue
        if revenue < 100000:
            analysis["red_flags"].append("Revenue below $100K — very early stage")
        elif revenue > 1000000:
            analysis["positive_signals"].append(f"Revenue ${revenue:,.0f} — meaningful traction")

    if burn_rate is not None and runway_months is not None:
        analysis["provided_metrics"]["burn_rate"] = burn_rate
        analysis["provided_metrics"]["runway_months"] = runway_months
        if runway_months < 6:
            analysis["red_flags"].append(f"Only {runway_months} months runway — critical")
        elif runway_months < 12:
            analysis["red_flags"].append(f"{runway_months} months runway — fundraise needed soon")
        else:
            analysis["positive_signals"].append(f"{runway_months} months runway — adequate")

    # Overall recommendation
    red_count = len(analysis["red_flags"])
    pos_count = len(analysis["positive_signals"])

    if red_count == 0 and pos_count > 0:
        analysis["recommendation"] = "PROCEED — Strong financial signals"
    elif red_count > pos_count:
        analysis["recommendation"] = "CAUTION — Multiple risk flags detected"
    elif red_count > 2:
        analysis["recommendation"] = "HIGH RISK — Significant financial concerns"
    else:
        analysis["recommendation"] = "NEUTRAL — Mixed signals, needs deeper diligence"

    return analysis

if __name__ == "__main__":
    # Test financial question answering
    result = answer_financial_question(
        "What was the revenue growth rate for SaaS companies in 2024?"
    )
    print(json.dumps(result, indent=2))

    # Test startup analysis
    analysis = analyze_startup_financials(
        company_name="ExampleStartup",
        revenue=500000,
        burn_rate=80000,
        runway_months=8,
    )
    print(json.dumps(analysis, indent=2))