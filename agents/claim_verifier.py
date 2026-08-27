import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import json
import logging
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

import observability
from agents.evidence_filter import filter_sources
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

def build_queries(claim: str, company: str = "") -> list:
    """Search queries for one claim, scoped to the company when it is known.

    The company parameter is the fix for a measured retrieval failure. This
    function used to receive only the claim text, because `verify_claim()` had
    no company parameter to pass -- so **the company name never entered the
    search query at all**. Deck claims are written elliptically ("Seed round
    target is $8M", "ARR grew 4x last year"); stripped of the company they are
    generic strings, and a generic string retrieves generic pages.

    The worked example: ClaimFlow's "Seed round target is $8M" returned
    merriam-webster.com, youtube.com, dictionary.cambridge.org, truemfg.com and
    trueccu.com. The last two are companies with "true" in the name, retrieved
    because the template `is it true that {claim}` put the word "true" into the
    query. Nothing in that result set is about ClaimFlow.

    Two templates are gone:

    - `is it true that {claim}` -- a pure noise generator. It contributes the
      words "is/it/true/that" to every query, which is what pulled in the
      dictionary entries for "true" and the two same-named businesses. Its
      intent (find corroboration) is already served better by `fact check`.
    - `{claim} false wrong debunked` -- retained ONLY when no company is known.
      It is what finds a public claim's refutation, so removing it outright
      would risk REFUTES recall (0.952 on the current benchmark), but on a
      seed-stage startup there is no debunking literature to find and the
      adjectives simply drift the query off-topic.

    When a company IS known the strategy changes entirely: anchor every query
    on the name, since the question is never "is this statement true in
    general" but "is it true of this company".
    """
    claim = (claim or "").strip()
    company = (company or "").strip()
    if not company:
        # Unscoped fallback: near the templates that measured 0.955 accuracy on
        # ml/eval/claim_benchmark.jsonl, minus the demonstrated noise generator.
        return [
            f'"{claim}"',
            f"fact check {claim}",
            f"{claim} evidence proof",
            f"{claim} false wrong debunked",
        ]

    return [
        f'"{company}" {claim}',
        f"{company} {claim}",
        f'"{claim}"',
        f'"{company}" funding revenue customers announcement',
        f"{company} startup company news",
    ]

def collect_evidence(claim: str, company: str = "", context: str = "") -> dict:
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
    queries = build_queries(claim, company=company)
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

    # Relevance gate, before the LLM sees anything. Better queries reduce the
    # off-topic rate but do not eliminate it, and an off-topic page is not
    # neutral: it is an invitation for the judge to reason about a different
    # company that happens to share a word with this one. The gate is a cheap
    # TF-IDF similarity check plus a small blocklist, and it records what it
    # removed so the report can say so rather than just showing fewer sources.
    filter_context = " ".join(filter(None, [company, context, claim]))
    kept, dropped = filter_sources(
        all_snippets, context=filter_context, company=company,
    )
    if dropped:
        print(f"  Relevance gate dropped {len(dropped)} of {len(all_snippets)} sources")
        for item in dropped[:5]:
            print(f"    - {item.get('url', '')[:70]}  [{item.get('_drop_reason', '')}]")
    all_snippets = kept

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
        # Reported, not discarded. A reader who wonders why a claim came back
        # unverified is entitled to see what was thrown away on their behalf.
        "dropped":    [
            {"url": d.get("url", ""), "reason": d.get("_drop_reason", "")}
            for d in dropped
        ],
        "retrieved_before_filter": len(dropped) + len(all_snippets),
    }

def groq_judge(claim: str, evidence: dict, as_of: str = "") -> dict:
    """Judge one claim against retrieved evidence.

    `as_of` is the deck's vintage, and it exists because of the single most
    damaging error found in production testing. Run across seven real pitch
    decks, the verifier produced four REFUTES verdicts at 0.95-0.97 confidence,
    and **every one of them was wrong in the same way**:

      - Airbnb (2008): "630,000 users on couchsurfing.com" was refuted using
        Wikipedia's present-day figure of 12,000,000.
      - Buffer (2011): "800 Paying Users" was refuted because Buffer now has
        over 70,000.
      - Coinbase (2012): "$2 million per day in transaction volume" was refuted
        because Coinbase now does roughly $751 million per day.
      - Uber (2008): "Overall market is $4.2B annually" was refuted using
        Uber's own 2025 global revenue of $52B.

    Each claim was TRUE when written. The verifier was reading historical
    statements against present-day evidence and calling the difference a
    falsehood -- so it penalised precisely the companies whose numbers had grown
    the most. REFUTES precision on the benchmark is 1.000; on real decks it was
    0.000, because ml/eval/claim_benchmark.jsonl contains no time-dependent
    claims and therefore could not see this failure mode at all.
    """
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

    as_of_line = (
        f"This claim is taken from a pitch deck dated or published around {as_of}. "
        f"Judge it as a statement about that time."
        if as_of else
        "The date of this claim is unknown. If it looks like a point-in-time metric "
        "from a pitch deck, assume it describes the past, not today."
    )

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

TIME — read this before deciding REFUTES:
{as_of_line}
A pitch deck states metrics as of the date it was written. Today's value of a
metric does NOT contradict a past value of the same metric. A company that had
800 paying users then and 70,000 now is a company that GREW; it is not a company
that lied.

So, for any claim that is a point-in-time quantity (users, revenue, run rate,
transaction volume, headcount, market size, growth):
- If the evidence describes a DIFFERENT period than the claim, you MUST answer
  NOT_ENOUGH_INFO. Say in the reasoning that the evidence is from a different
  period.
- Answer REFUTES only if the evidence contradicts the claim FOR THE PERIOD THE
  CLAIM IS ABOUT.
- A larger present-day figure is evidence of growth, never evidence of falsehood.

Also: if the only evidence is a copy of the pitch deck itself, or an article
reproducing the deck, that is the claim restating itself. Answer
NOT_ENOUGH_INFO — a document cannot corroborate itself.

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

    except Exception as exc:
        logger.exception("Groq claim-verification request failed")
        observability.track_degradation(
            "claim_verification_failed", component="claim_verifier",
            reason=f"{type(exc).__name__}: {exc}"[:200],
        )
        return {
            "verdict":      "NOT_ENOUGH_INFO",
            "confidence":   0.0,
            "reasoning":    "Claim verification is temporarily unavailable.",
            "key_evidence": "",
            # Explicit marker, not prose. Downstream used to detect this by
            # string-comparing the reasoning text, which silently failed the
            # moment a second fallback site worded it "was" instead of "is" --
            # see the note in ventureflow_agent's degradation block.
            "_degraded":        True,
            "_degraded_reason": "claim verifier provider call failed",
        }

def _evidence_text(evidence: dict) -> str:
    """Flatten retrieved evidence to the text the judge actually reasoned over.

    Only the evaluation harness asks for this (`include_evidence=True`), and
    it exists so a baseline model can be scored on the *same* evidence rather
    than a separately-retrieved set -- two models fed different search results
    are not a comparison of the models. Kept out of the default return value
    because it is several kilobytes per claim and every production caller
    persists its result into a report.
    """
    parts = [f"{s['title']} {s['snippet']}" for s in evidence.get("snippets", [])]
    parts += [ft["text"] for ft in evidence.get("full_texts", [])]
    return "\n".join(p for p in parts if p)


def verify_claim(
    claim_text: str,
    verbose: bool = True,
    include_evidence: bool = False,
    company: str = "",
    context: str = "",
    as_of: str = "",
) -> dict:
    """Verify one claim against live web search.

    `company` and `context` are optional and default to the previous behaviour,
    because two callers verify bare claims with no company attached: the
    interactive REPL at the bottom of this file, and
    ml/scripts/eval_claim_verifier.py, whose benchmark rows carry no company
    field. The product path (ventureflow_agent) always passes them, and that is
    the path where the missing company name was doing the damage.
    """
    if verbose:
        print(f"\n{'='*60}")
        print(f"Verifying: {claim_text}")
        if company:
            print(f"Company:   {company}")
        print(f"{'='*60}")

    evidence = collect_evidence(claim_text, company=company, context=context)

    # A model must never be allowed to infer a verdict without retrieved evidence.
    if not evidence["snippets"] and not evidence["full_texts"]:
        # "The web had nothing" and "the gate removed everything the web had"
        # are different facts about a company, and only one of them is about
        # the company at all.
        observability.track_degradation(
            "no_evidence_retrieved", component="claim_verifier",
            reason=("all sources dropped by the relevance gate"
                    if evidence.get("dropped") else "search returned nothing"),
            sources_dropped=len(evidence.get("dropped", [])),
        )
        empty = {
            "claim": claim_text,
            "verdict": "NOT_ENOUGH_INFO",
            "confidence": 0.0,
            "reasoning": "No external evidence could be retrieved for this claim.",
            "key_evidence": "",
            "sources": [],
            "total_sources": 0,
            "full_pages_read": 0,
            "sources_dropped": len(evidence.get("dropped", [])),
            "dropped_sources": evidence.get("dropped", []),
        }
        if include_evidence:
            empty["evidence_text"] = ""
        return empty

    print(f"  Groq AI analyzing {len(evidence['snippets'])} sources "
          f"+ {len(evidence['full_texts'])} full pages...")

    judgment = groq_judge(claim_text, evidence, as_of=as_of)

    result = {
        "claim":           claim_text,
        "verdict":         judgment.get("verdict", "NOT_ENOUGH_INFO"),
        "confidence":      judgment.get("confidence", 0.0),
        "reasoning":       judgment.get("reasoning", ""),
        "key_evidence":    judgment.get("key_evidence", ""),
        "sources":         evidence["sources"][:5],
        "total_sources":   len(evidence["snippets"]),
        "full_pages_read": len(evidence["full_texts"]),
        # Surfaced so a reader can distinguish "the web had nothing" from "the
        # relevance gate removed everything the web had", which are very
        # different statements about a company.
        "sources_dropped": len(evidence.get("dropped", [])),
        "dropped_sources": evidence.get("dropped", []),
    }
    if include_evidence:
        result["evidence_text"] = _evidence_text(evidence)

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
