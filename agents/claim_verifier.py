import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import json, logging, time
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

from groq_client import MODEL, get_client
logger = logging.getLogger(__name__)

def search_web(query: str, max_results: int = 8) -> list:
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title":   r.get("title", ""),
                    "url":     r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
    except Exception as e:
        print(f"  Search error: {e}")
    return results

def fetch_page_text(url: str, max_chars: int = 3000) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, timeout=6, headers=headers)
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav",
                         "footer", "header", "aside"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)[:max_chars]
    except:
        return ""

def build_queries(claim: str) -> list:
    return [
        f'"{claim}"',
        f"fact check {claim}",
        f"is it true that {claim}",
        f"{claim} evidence proof",
        f"{claim} false wrong debunked",
    ]

def collect_evidence(claim: str) -> dict:
    """Gather web evidence for one claim.

    The searches and page fetches run concurrently. They used to run one after
    another, and measurement showed that was the single largest cost in the
    whole pipeline: five sequential DuckDuckGo queries averaged 16.8s per
    claim, and five sequential page fetches (each followed by a hardcoded
    0.3s sleep) added ~7s more. At five claims per deck that is roughly two
    minutes of a four-minute analysis spent waiting on I/O that has no
    ordering requirement between items.

    Concurrency is capped at 5 rather than unbounded: these are calls to a
    free public search endpoint, and the point is to overlap latency, not to
    burst traffic at someone else's service. Both helpers already swallow
    their own exceptions and return empty results, so one failed query or
    unreachable page degrades that item rather than the claim.
    """
    queries = build_queries(claim)
    print(f"  Running {len(queries)} searches concurrently...")
    all_snippets = []
    seen_urls    = set()

    with ThreadPoolExecutor(max_workers=min(5, len(queries))) as executor:
        # Results are collected in submission order, not completion order, so
        # the evidence a claim is judged on does not silently reorder run to
        # run purely because of network timing.
        for results in executor.map(lambda q: search_web(q, max_results=5), queries):
            for r in results:
                if r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    all_snippets.append(r)

    print(f"  Found {len(all_snippets)} unique sources")

    top = all_snippets[:5]
    print(f"  Reading full content from top {len(top)} pages concurrently...")
    full_texts = []
    if top:
        with ThreadPoolExecutor(max_workers=min(5, len(top))) as executor:
            for item, text in zip(top, executor.map(lambda i: fetch_page_text(i["url"]), top)):
                if text:
                    full_texts.append({
                        "url":   item["url"],
                        "title": item["title"],
                        "text":  text,
                    })

    return {
        "snippets":   all_snippets[:15],
        "full_texts": full_texts,
        "sources":    [r["url"] for r in all_snippets[:10]],
    }

def groq_judge(claim: str, evidence: dict) -> dict:
    evidence_block = "=== SEARCH SNIPPETS ===\n"
    for i, s in enumerate(evidence["snippets"][:10], 1):
        evidence_block += f"\n[{i}] {s['title']}\n"
        evidence_block += f"URL: {s['url']}\n"
        evidence_block += f"Content: {s['snippet']}\n"

    if evidence["full_texts"]:
        evidence_block += "\n=== FULL PAGE CONTENT ===\n"
        for ft in evidence["full_texts"][:3]:
            evidence_block += f"\n[From: {ft['url']}]\n"
            evidence_block += ft["text"][:1500] + "\n"

    prompt = f"""You are a strict professional fact-checker.

CLAIM: "{claim}"

EVIDENCE:
{evidence_block}

RULES:
- If evidence directly CONFIRMS the claim → SUPPORTS
- If evidence directly CONTRADICTS the claim → REFUTES
- If evidence is unclear or insufficient → NOT_ENOUGH_INFO
- Base verdict ONLY on evidence above
- Topic similarity does NOT mean the claim is supported
- Look for direct factual confirmation or contradiction

Respond with ONLY valid JSON, no other text:
{{
  "verdict": "SUPPORTS",
  "confidence": 0.95,
  "reasoning": "2 sentence explanation citing specific evidence",
  "key_evidence": "most important sentence from evidence"
}}"""

    try:
        response = get_client().chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional fact-checker. "
                               "Always respond with valid JSON only."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=500,
        )

        raw = response.choices[0].message.content.strip()

        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    raw = part
                    break

        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]

        result = json.loads(raw)

        if result.get("verdict") not in [
            "SUPPORTS", "REFUTES", "NOT_ENOUGH_INFO"
        ]:
            result["verdict"] = "NOT_ENOUGH_INFO"

        return result

    except json.JSONDecodeError:
        raw_upper = raw.upper()
        verdict = (
            "REFUTES"          if "REFUTES"  in raw_upper else
            "SUPPORTS"         if "SUPPORTS" in raw_upper else
            "NOT_ENOUGH_INFO"
        )
        return {
            "verdict":      verdict,
            "confidence":   0.5,
            "reasoning":    raw[:300],
            "key_evidence": "",
        }

    except Exception:
        logger.exception("Groq claim-verification request failed")
        return {
            "verdict":      "NOT_ENOUGH_INFO",
            "confidence":   0.0,
            "reasoning":    "Claim verification is temporarily unavailable.",
            "key_evidence": "",
        }

def verify_claim(claim_text: str, verbose: bool = True) -> dict:
    if verbose:
        print(f"\n{'='*60}")
        print(f"Verifying: {claim_text}")
        print(f"{'='*60}")

    evidence = collect_evidence(claim_text)

    # A model must never be allowed to infer a verdict without retrieved evidence.
    if not evidence["snippets"] and not evidence["full_texts"]:
        return {
            "claim": claim_text,
            "verdict": "NOT_ENOUGH_INFO",
            "confidence": 0.0,
            "reasoning": "No external evidence could be retrieved for this claim.",
            "key_evidence": "",
            "sources": [],
            "total_sources": 0,
            "full_pages_read": 0,
        }

    print(f"  Groq AI analyzing {len(evidence['snippets'])} sources "
          f"+ {len(evidence['full_texts'])} full pages...")

    judgment = groq_judge(claim_text, evidence)

    result = {
        "claim":           claim_text,
        "verdict":         judgment.get("verdict", "NOT_ENOUGH_INFO"),
        "confidence":      judgment.get("confidence", 0.0),
        "reasoning":       judgment.get("reasoning", ""),
        "key_evidence":    judgment.get("key_evidence", ""),
        "sources":         evidence["sources"][:5],
        "total_sources":   len(evidence["snippets"]),
        "full_pages_read": len(evidence["full_texts"]),
    }

    if verbose:
        print(f"\n  VERDICT:      {result['verdict']}")
        print(f"  CONFIDENCE:   {result['confidence']:.0%}")
        print(f"  REASONING:    {result['reasoning']}")
        print(f"  KEY EVIDENCE: {result['key_evidence'][:200]}")
        print(f"  Sources:      {result['total_sources']} snippets, "
              f"{result['full_pages_read']} full pages")

    return result

if __name__ == "__main__":
    print("Claim Verifier — Groq + DuckDuckGo")
    print("Type 'exit' to quit\n")

    while True:
        claim_input = input("Enter a claim: ").strip()
        if claim_input.lower() in ["exit", "quit"]:
            break
        if not claim_input:
            continue

        result = verify_claim(claim_input)
        print(f"\n{'='*60}")
        print(f"VERDICT:      {result['verdict']}")
        print(f"CONFIDENCE:   {result['confidence']:.0%}")
        print(f"REASONING:    {result['reasoning']}")
        print(f"KEY EVIDENCE: {result['key_evidence'][:300]}")
        print(f"SOURCES READ: {result['total_sources']} + "
              f"{result['full_pages_read']} full pages")
        print(f"{'='*60}\n")
