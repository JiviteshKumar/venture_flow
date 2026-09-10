import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup

import observability
from agents.evidence_filter import filter_sources
from groq_client import MODEL, get_client, note_provider_failure, pace_for, settle_usage, describe_provider_failure

logger = logging.getLogger(__name__)

def search_web(query: str, max_results: int = 8, raise_on_error: bool = False) -> list:
    """Web search. Returns [] on failure unless `raise_on_error` is set.

    The default swallows errors because claim verification treats a failed
    search the same as an unhelpful one -- it just has less evidence either way.

    `raise_on_error=True` exists because that equivalence is false elsewhere.
    Founder research has to tell "we searched and found nothing" from "the
    search never ran", and swallowing the exception here made those two
    indistinguishable to the caller: every query could fail with the network
    down and the report would still say "searched public sources, no founder
    names could be established", which reads as a fact about the company
    instead of a fact about our connectivity.

    This is now a thin wrapper over `agents.web_search`, which tries several
    providers rather than only DuckDuckGo. The signature and both behaviours are
    unchanged, because every caller in the codebase depends on them; what
    changed is that a single throttled provider no longer takes the product's
    entire evidence-gathering ability down with it. Callers that want to know
    WHICH provider answered should use `search_web_with_provenance` below.
    """
    from agents.web_search import AllProvidersFailed, search, search_or_raise

    if raise_on_error:
        try:
            return search_or_raise(query, max_results)["results"]
        except AllProvidersFailed as exc:
            # Re-raised as-is. The caller's contract is "an exception means the
            # search did not run", and AllProvidersFailed means exactly that.
            raise RuntimeError(f"Every search provider failed: {exc}") from exc

    outcome = search(query, max_results)
    if outcome["errors"]:
        logger.warning("Search degraded: %s", "; ".join(outcome["errors"]))
    return outcome["results"]


def search_web_with_provenance(query: str, max_results: int = 8) -> dict:
    """`search_web`, plus which provider answered and what the others did.

    Evidence from an encyclopaedia and evidence from a general web index are not
    interchangeable, and a report that cites either should be able to say which
    it had.
    """
    from agents.web_search import search

    return search(query, max_results)

def fetch_page_text(url: str, max_chars: int = 3000) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, timeout=6, headers=headers)
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav",
                         "footer", "header", "aside"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)[:max_chars]
    except Exception:
        return ""

# Capitalised tokens that are never the subject of a claim. Without this the
# extractor treats "March", "Series" and "Q3" as companies and spends a search
# slot on each.
_NOT_AN_ENTITY = {
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "Series", "Seed", "Round", "Pre", "Post", "The", "A", "An", "In", "It",
    "This", "That", "They", "We", "Our", "Its", "Q1", "Q2", "Q3", "Q4",
    "ARR", "MRR", "CAC", "LTV", "IPO", "CEO", "CTO", "COO", "CFO", "US", "USA",
    "UK", "EU", "AI", "API", "SaaS", "B2B", "B2C",
}

_ENTITY = re.compile(r"\b([A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,2})\b")


def named_entities(claim: str) -> list:
    """Distinct proper-noun-shaped mentions in a claim, in order of appearance.

    Deliberately a regex and not a model. This runs on every claim, it must not
    cost a language-model call, and a false positive is cheap: the worst an
    invented entity does is spend one extra concurrent search whose results are
    then dropped by the relevance gate. A false negative is what actually costs
    accuracy, so the pattern errs towards over-matching.
    """
    text = claim or ""
    seen, out = set(), []
    for match in _ENTITY.finditer(text):
        name = match.group(1).strip().rstrip(".").replace("'s", "").replace("’s", "")
        if not name or name in _NOT_AN_ENTITY:
            continue
        # A multi-word match whose every word is a stopword is not an entity.
        words = name.split()
        if all(w in _NOT_AN_ENTITY for w in words):
            continue
        # Trim leading stopwords ("The Uber IPO" -> "Uber IPO").
        while words and words[0] in _NOT_AN_ENTITY:
            words = words[1:]
        name = " ".join(words)

        # "Series C" survives the stopword trim as the single letter "C", which
        # retrieves nothing and costs a search slot. Nor is a bare number ever
        # the subject of a claim.
        if len(name) < 2 or name.replace(".", "").isdigit():
            continue

        # A single capitalised word at the very start of the claim is usually
        # the sentence's first word rather than a name, and deck claims are
        # written as fragments that begin with a verb -- "Partnered with Stripe
        # and Plaid", "Launched in 2023", "Grew ARR 4x". Treating those as
        # companies spent one of the two slots below on a search for
        # "Partnered", which displaced the real second entity (Plaid).
        #
        # Dropping it costs nothing even when it IS the subject, because the
        # whole-claim templates already anchor on whatever the claim leads
        # with. What these extra queries are for is the entity mentioned
        # second, which nothing else in the query set reaches.
        if match.start() == 0 and len(words) == 1:
            continue

        key = name.lower()
        if key not in seen:
            seen.add(key)
            out.append(name)
    return out


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
        queries = [
            f'"{claim}"',
            f"fact check {claim}",
            f"{claim} evidence proof",
            f"{claim} false wrong debunked",
        ]
        return queries + _secondary_entity_queries(claim, skip=[])

    return [
        f'"{company}" {claim}',
        f"{company} {claim}",
        f'"{claim}"',
        f'"{company}" funding revenue customers announcement',
        f"{company} startup company news",
    ] + _secondary_entity_queries(claim, skip=[company])


def _secondary_entity_queries(claim: str, skip: list) -> list:
    """One extra query per additional entity the claim talks about.

    Every template above anchors on the claim as a whole, which retrieves
    evidence about whichever entity the claim leads with. For a claim that
    compares two of them, that is only ever half the evidence -- and the judge
    is then correct, and useless, in saying so. Four of the six errors on
    ml/eval/claim_benchmark.jsonl are exactly this shape:

        "Lyft went public in March 2019, before Uber's initial public
         offering."  -> every source was about Lyft; the judge said it could
         not determine Uber's IPO date and returned NOT_ENOUGH_INFO against a
         gold label of SUPPORTS.

        "Lyft operates in more countries than Uber."  -> same, against REFUTES.

    Anchoring a query on the trailing entity is the same move that fixed
    company-scoped retrieval, applied to the entity the claim mentions second.

    Capped at two, and they cost no language-model tokens: searches run
    concurrently and the evidence handed to the judge is capped downstream at
    fifteen snippets either way. The cost of being wrong here is latency, not
    quota.
    """
    skipped = {str(x).strip().lower() for x in skip if x}
    extra = []
    for entity in named_entities(claim):
        if entity.lower() in skipped:
            continue
        skipped.add(entity.lower())
        if len(extra) >= 2:
            break
        extra.append(f'"{entity}" {claim}')
    return extra

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

    providers_used: dict = {}
    general_web_unavailable = False

    with ThreadPoolExecutor(max_workers=min(5, len(queries))) as executor:
        # Results are collected in submission order, not completion order, so
        # the evidence a claim is judged on does not silently reorder run to
        # run purely because of network timing.
        for outcome in executor.map(
            lambda q: search_web_with_provenance(q, max_results=5), queries
        ):
            answered = outcome.get("provider") or ""
            results = outcome.get("results") or []
            if answered and results:
                providers_used[answered] = providers_used.get(answered, 0) + len(results)
            # "The general web index was not reachable for this query" is the
            # condition that changes what the evidence is worth, and it is
            # invisible in the results themselves.
            for attempt in outcome.get("attempts") or []:
                if attempt.get("provider") == "duckduckgo" and \
                        attempt.get("outcome") not in ("ok",):
                    general_web_unavailable = True
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
        # Which index answered, and whether the general-web one was missing.
        # A claim about a startup metric judged entirely on encyclopaedia
        # articles is a materially weaker check than the same claim judged on
        # the open web, and the two used to be indistinguishable downstream.
        "providers": dict(providers_used),
        "general_web_unavailable": general_web_unavailable,
    }

# Completion budgets for the claim judge, tried in order.
#
# `openai/gpt-oss-120b` is a reasoning model: it spends completion tokens
# thinking before it writes the JSON. At the old 500-token ceiling, against a
# ~6,000-character evidence prompt, the thinking regularly consumed the whole
# budget and the answer arrived truncated or empty. 2,000 is in line with the
# other structured call sites; the retry exists for the genuinely long cases.
# settle_usage refunds whatever is not used, so a larger ceiling only costs
# pacing time when the model actually needs the room.
JUDGE_TOKEN_BUDGETS = (2000, 4000)

_VERDICTS = ("SUPPORTS", "REFUTES", "NOT_ENOUGH_INFO")


def _judge_once(prompt: str, max_tokens: int) -> tuple[str, str | None]:
    """One call to the judge. Returns (content, finish_reason)."""
    pace_for(len(prompt), max_tokens)
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
        max_tokens=max_tokens,
        # Every other structured call site already constrains the reply to a
        # JSON object; the judge was the one that did not.
        response_format={"type": "json_object"},
    )
    # Return the completion budget this call reserved but did not use.
    # Bookkeeping only -- it cannot change what the model said, and it stops
    # the next call waiting on tokens nobody spent.
    settle_usage(response, len(prompt), max_tokens)
    choice = response.choices[0]
    content = (getattr(choice.message, "content", None) or "").strip()
    return content, getattr(choice, "finish_reason", None)


def parse_judgment(raw: str) -> dict | None:
    """The judge's reply as a validated dict, or None if there is no usable one.

    None is the important return. The previous fallback turned an unparseable
    reply into a verdict by searching the text for "REFUTES" and then
    "SUPPORTS" -- so "this evidence does not refute the claim" scored as
    REFUTES -- and attached a confidence of 0.5 that the model never gave.
    Returning None lets the caller retry or report the failure honestly.
    """
    text = (raw or "").strip()
    if not text:
        return None
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break
    start, end = text.find("{"), text.rfind("}") + 1
    if start == -1 or end <= start:
        return None
    try:
        result = json.loads(text[start:end])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(result, dict):
        return None

    verdict = str(result.get("verdict", "")).strip().upper()
    if verdict not in _VERDICTS:
        # A reply with no recognisable verdict has not judged the claim.
        return None
    result["verdict"] = verdict
    try:
        confidence = float(result.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    result["confidence"] = min(1.0, max(0.0, confidence))
    result.setdefault("reasoning", "")
    result.setdefault("key_evidence", "")
    return result


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
        "The date of this claim is UNKNOWN, and that changes what you may "
        "conclude.\n"
        "This claim comes from a pitch deck, so a metric in it describes the "
        "company AT THE TIME THE DECK WAS WRITTEN, which may be many years ago.\n"
        "Evidence you retrieve is from today. A company that grew will therefore "
        "show today's figures as far LARGER than the claim.\n"
        "A larger present-day number does NOT contradict a smaller past number -- "
        "it is what growth looks like. Reporting that as a refutation is the "
        "single worst error you can make here.\n"
        "Therefore: if the claim is a point-in-time metric (users, revenue, "
        "volume, headcount, growth rate) and the evidence you have is from a "
        "clearly later period, you MUST answer NOT_ENOUGH_INFO. Reserve REFUTES "
        "for evidence that contradicts the claim AS A STATEMENT ABOUT ITS OWN "
        "TIME -- for example a source saying the company did not exist then, or "
        "explicitly correcting the figure for that period."
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
        # Stay inside the free tier's 8,000 tokens/minute. Without this the
        # pipeline bursts its whole budget in seconds and every later call
        # 429s, which is how six of six real deck runs came back degraded.
        attempts = []
        for budget in JUDGE_TOKEN_BUDGETS:
            raw, finish_reason = _judge_once(prompt, budget)
            parsed = parse_judgment(raw)
            if parsed is not None:
                return parsed
            attempts.append(f"{budget} tokens -> finish_reason={finish_reason}, "
                            f"{len(raw)} chars")
            logger.warning(
                "Claim judge reply unusable at max_tokens=%d (finish_reason=%s, "
                "%d chars); %s", budget, finish_reason, len(raw),
                "retrying with a larger budget" if budget != JUDGE_TOKEN_BUDGETS[-1]
                else "giving up on this claim",
            )

        # Both attempts produced nothing parseable. Say so, and keep it out of
        # the score: this is a failure to judge, not a judgment. The old
        # fallback sniffed the raw text for "REFUTES"/"SUPPORTS" and stamped a
        # made-up confidence of 0.5 on the result, which is how a truncated
        # reply was scored as a verdict.
        observability.track_degradation(
            "claim_judgment_unparseable", component="claim_verifier",
            reason="; ".join(attempts)[:200],
        )
        return {
            "verdict":      "NOT_ENOUGH_INFO",
            "confidence":   0.0,
            "reasoning":    "This claim was not judged: the fact-checking model's "
                            "reply was truncated or unreadable on two attempts. "
                            "Nothing was established either way.",
            "key_evidence": "",
            "_degraded":        True,
            "_degraded_kind":   "unparseable",
            "_degraded_reason": "claim verifier: the judge's reply was truncated "
                                "or unparseable twice",
        }

    except Exception as exc:
        logger.exception("Groq claim-verification request failed")
        # Tell the breaker. A daily-quota refusal means every remaining claim,
        # specialist and the memo will fail the same way, and without this each
        # of them spends six retries and up to 90 seconds finding that out.
        note_provider_failure(exc)
        observability.track_degradation(
            "claim_verification_failed", component="claim_verifier",
            reason=f"{type(exc).__name__}: {exc}"[:200],
        )
        # The reason a reader sees says WHICH failure it was. "Temporarily
        # unavailable" is true of a network blip and of an exhausted daily
        # quota, and only one of those is worth waiting out.
        detail = describe_provider_failure(exc)
        return {
            "verdict":      "NOT_ENOUGH_INFO",
            "confidence":   0.0,
            "reasoning":    f"Claim verification did not run: {detail}. "
                            f"This is a fact about this deployment, not about the claim.",
            "key_evidence": "",
            # Explicit marker, not prose. Downstream used to detect this by
            # string-comparing the reasoning text, which silently failed the
            # moment a second fallback site worded it "was" instead of "is" --
            # see the note in ventureflow_agent's degradation block.
            "_degraded":        True,
            "_degraded_kind":   "provider",
            "_degraded_reason": f"claim verifier: {detail}",
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
            "evidence_providers": evidence.get("providers", {}),
        }
        # This early return is where provenance matters MOST and where it was
        # missing: "no external evidence could be retrieved" reads as a fact
        # about how little the world has written about this company, when the
        # actual event may have been that the general web index was
        # unreachable and only the fallback was asked.
        if evidence.get("general_web_unavailable"):
            empty["evidence_degraded"] = True
            empty["evidence_degraded_reason"] = (
                "No evidence was retrieved, but the general web index "
                "(DuckDuckGo) was rate-limited during this search, so the open "
                "web was never actually consulted for this claim. Absence of "
                "evidence here is not evidence of absence."
            )
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

    # Carry the provider-failure marker through.
    #
    # THIS DICT IS BUILT FIELD BY FIELD, and `_degraded` was not one of the
    # fields, so the flag `groq_judge` sets on a provider failure died here --
    # two lines after it was raised. Everything downstream that depends on it
    # was therefore unreachable in production:
    #
    #   * ventureflow_agent's degraded-components block scans claim results for
    #     `_degraded` and never found one, so `provider_degraded` stayed False
    #     on reports whose every claim had failed to a 429.
    #   * ml/evidence_fusion counted each of those NOT_ENOUGH_INFO verdicts as
    #     an unresolved claim, which is what drives the evidence penalty.
    #
    # The visible result: with the Groq daily token quota exhausted, Uber's
    # 2008 deck scored 35/100 -- a model prior of 50 minus a 15-point evidence
    # penalty for claims that were never actually checked. The company was
    # marked down for our outage, which is the precise failure the comment in
    # ventureflow_agent describes and believed it had fixed.
    for marker in ("_degraded", "_degraded_kind", "_degraded_reason"):
        if marker in judgment:
            result[marker] = judgment[marker]

    # Provenance of the evidence itself, distinct from the judgement above.
    result["evidence_providers"] = evidence.get("providers", {})
    if evidence.get("general_web_unavailable"):
        result["evidence_degraded"] = True
        result["evidence_degraded_reason"] = (
            "The general web index (DuckDuckGo) was rate-limited, so this "
            "claim was checked against the fallback providers only. On real "
            "deck claims the share of on-topic sources runs about 94% with "
            "that index and about 32% without it, so this is a weaker check, "
            "not a stronger finding."
        )
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
