"""Web search with more than one provider behind it.

THE PROBLEM

Every web lookup in this product -- claim verification, founder research, risk
detection -- went through one DuckDuckGo call. DuckDuckGo has no API key and no
published rate limit, which is convenient right up to the point where it starts
refusing. Under sustained use (a batch of decks, a regression run, several
analyses in a row) it rate-limits aggressively, and when it does, every search
in the pipeline fails at once.

The consequence is worse than slowness, because of what the callers do with an
empty result. Claim verification treats "no evidence found" as unverifiable.
Founder research is careful enough to distinguish a failed search from a search
that found nothing -- but only because it asked for the exception. A single
throttled provider therefore degrades the whole product's evidence-gathering
simultaneously, and mostly quietly.

WHAT THIS DOES

Tries providers in order until one returns results, and reports which one
answered. A provider that raises is recorded and skipped. A provider that
succeeds with zero results does NOT end the chain on its own: an empty page is
what DuckDuckGo returns when it soft-throttles as well as when the web really
has nothing, so `EMPTY_CONFIRMATIONS` providers must agree before the chain
reports nothing found.

    DuckDuckGo   no key   general web
    Wikipedia    no key   encyclopaedic, and the single most useful source for
                          the founder-and-company questions this product asks
    Brave        key      general web, 2,000 queries/month free
    Tavily       key      search built for retrieval, 1,000 credits/month free

The two keyless providers are the ones that matter: they make the chain work on
a fresh clone with no configuration, which is the state this repository is
usually in. Brave and Tavily are skipped entirely unless their key is set, so
they cost nothing and fail nothing when absent.

Wikipedia is not a general web index and is not a replacement for one. It is
included because it is genuinely reliable, genuinely free, imposes no practical
rate limit at this volume, and answers exactly the class of question that
matters most here -- who founded this company, what happened to it. Measured
against the query "Canva founders Melanie Perkins Cliff Obrecht", it returns the
Melanie Perkins, Cliff Obrecht and Canva articles as the top three results in
1.0 seconds.

RATE-LIMIT MEMORY

A provider that fails is put in a cooldown and skipped until it expires, rather
than being retried on every subsequent query. Without this, a rate-limited
DuckDuckGo is re-tried dozens of times during one analysis, and each attempt
costs its own timeout -- turning a degraded search into a slow one as well.

WHAT THIS DELIBERATELY DOES NOT DO

It does not merge results across providers. The first provider that answers,
answers; blending two ranked lists into one produces an order that neither
provider would endorse and that nothing downstream can reason about. The
provider that answered is reported so a caller can weigh the evidence
accordingly.
"""

from __future__ import annotations

import html
import logging
import os
import re
import time
from typing import Any, Callable

import requests

logger = logging.getLogger(__name__)

# Seconds a provider is skipped after it fails. Long enough that a rate limit
# has a chance to clear, short enough that a transient network blip does not
# sideline a provider for a whole analysis.
COOLDOWN_S = float(os.getenv("VENTUREFLOW_SEARCH_COOLDOWN", "120"))

# How many providers must independently answer "nothing" before the chain
# believes the web is actually empty.
#
# This used to be 1, on the reasoning that a provider which answers with zero
# results has genuinely answered, and that trying three more would turn "the web
# has nothing on this obscure seed-stage company" into four redundant lookups.
# The reasoning was right about obscure companies and wrong about everything
# else, because it assumed an empty answer is always a real answer.
#
# It is not. DuckDuckGo does not return an error when it soft-throttles; it
# returns an empty result page, which is byte-for-byte the same answer it gives
# for a genuinely unfindable query. On the claim benchmark that cost two
# outright errors -- "IBM acquired Red Hat in 2019 for approximately $34
# billion" and "WeWork successfully completed its initial IPO in 2019" both came
# back with zero sources and were scored NOT_ENOUGH_INFO. Neither is an obscure
# fact. Wikipedia, one line further down the chain, answers both.
#
# Two is the number that distinguishes the two cases without reintroducing the
# cost the original comment was worried about: a genuinely empty query now costs
# one extra lookup (Wikipedia, keyless, ~1s, no practical rate limit), and the
# four benchmark claims about companies that do not exist still correctly
# retrieve nothing -- confirmed twice instead of asserted once.
EMPTY_CONFIRMATIONS = int(os.getenv("VENTUREFLOW_SEARCH_EMPTY_CONFIRMATIONS", "2"))

USER_AGENT = (
    "VentureFlow/1.0 (https://github.com/SageOtter2023/venture_flow; "
    "due-diligence research tool)"
)

# provider name -> monotonic time at which it may be tried again.
_cooldowns: dict[str, float] = {}


class AllProvidersFailed(RuntimeError):
    """Every enabled provider raised.

    Distinct from "no provider found anything", which is an ordinary empty
    result. Callers that must tell those apart -- founder research, which
    otherwise reports our own connectivity failure as a fact about the company
    -- catch this.
    """


def _strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def _duckduckgo(query: str, max_results: int) -> list[dict[str, str]]:
    """DuckDuckGo, with its one dangerous quirk handled.

    `ddgs` raises `DDGSException("No results found.")` for a query that simply
    has no hits. That is an answer, not a failure, but it arrives as an
    exception -- so the chain above recorded a provider failure and put
    DuckDuckGo in a 120-second cooldown.

    The consequence was out of all proportion to the cause. One analysis issues
    roughly twenty-five searches (five claims x five query templates), and deck
    claims are elliptical enough that at least one of them is always
    unfindable. The first such query sidelined the general-web provider for two
    minutes -- i.e. for the rest of the analysis -- leaving every remaining
    claim to be judged on whatever Wikipedia alone could supply. The product
    then reported thin evidence as a finding about the company.

    A genuine rate limit and a genuine timeout have their own subclasses and
    are still treated as failures, because they are.
    """
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

    try:
        with DDGS() as ddgs:
            rows = list(ddgs.text(query, max_results=max_results))
    except (RatelimitException, TimeoutException):
        raise
    except DDGSException as exc:
        if "no results" in str(exc).lower():
            return []
        raise

    return [
        {
            "title": row.get("title", ""),
            "url": row.get("href", ""),
            "snippet": row.get("body", ""),
        }
        for row in rows
    ]


def _wikipedia(query: str, max_results: int) -> list[dict[str, str]]:
    response = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query", "format": "json", "list": "search",
            "srsearch": query, "srlimit": max_results, "srprop": "snippet",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    hits = ((response.json().get("query") or {}).get("search")) or []
    return [
        {
            "title": hit.get("title", ""),
            "url": "https://en.wikipedia.org/wiki/"
                   + str(hit.get("title", "")).replace(" ", "_"),
            # The API marks matched terms with <span class="searchmatch">.
            # Left in, those tags reach the LLM prompt and the evidence filter
            # as literal markup.
            "snippet": _strip_tags(hit.get("snippet", "")),
        }
        for hit in hits
    ]


def _brave(query: str, max_results: int) -> list[dict[str, str]]:
    key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    response = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": min(max_results, 20)},
        headers={"X-Subscription-Token": key, "Accept": "application/json",
                 "User-Agent": USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    hits = ((response.json().get("web") or {}).get("results")) or []
    return [
        {
            "title": _strip_tags(hit.get("title", "")),
            "url": hit.get("url", ""),
            "snippet": _strip_tags(hit.get("description", "")),
        }
        for hit in hits
    ]


def _tavily(query: str, max_results: int) -> list[dict[str, str]]:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    response = requests.post(
        "https://api.tavily.com/search",
        json={"api_key": key, "query": query, "max_results": max_results,
              "search_depth": "basic"},
        headers={"User-Agent": USER_AGENT},
        timeout=25,
    )
    response.raise_for_status()
    return [
        {
            "title": hit.get("title", ""),
            "url": hit.get("url", ""),
            "snippet": hit.get("content", ""),
        }
        for hit in response.json().get("results") or []
    ]


# (name, callable, is_configured). Order is the failover order: the keyless
# general-web index first, then the keyless encyclopaedia, then the keyed
# providers -- which are last only because they are usually absent, not because
# they are worse.
PROVIDERS: list[tuple[str, Callable[[str, int], list[dict[str, str]]], Callable[[], bool]]] = [
    ("duckduckgo", _duckduckgo, lambda: True),
    ("wikipedia", _wikipedia, lambda: True),
    ("brave", _brave, lambda: bool(os.getenv("BRAVE_SEARCH_API_KEY", "").strip())),
    ("tavily", _tavily, lambda: bool(os.getenv("TAVILY_API_KEY", "").strip())),
]


def available_providers() -> list[str]:
    """Providers that are configured, in failover order. Used by /health and
    config_check so an operator can see what the chain will actually try."""
    return [name for name, _fn, configured in PROVIDERS if configured()]


def reset_cooldowns() -> None:
    """Forget every recorded failure. For tests and for a manual retry."""
    _cooldowns.clear()


def search(query: str, max_results: int = 8) -> dict[str, Any]:
    """Search, with failover. Never raises.

    Returns {results, provider, attempts, errors}. `provider` is the one that
    answered, or "" when none did. `attempts` records every provider tried and
    what happened, so a caller -- or a person reading a report -- can tell an
    empty web from an unreachable one.
    """
    attempts: list[dict[str, Any]] = []
    errors: list[str] = []
    answered_empty: list[str] = []
    now = time.monotonic()

    for name, fn, configured in PROVIDERS:
        if not configured():
            attempts.append({"provider": name, "outcome": "not configured"})
            continue
        if _cooldowns.get(name, 0) > now:
            attempts.append({
                "provider": name,
                "outcome": f"cooling down for another "
                           f"{_cooldowns[name] - now:.0f}s after an earlier failure",
            })
            continue

        started = time.monotonic()
        try:
            results = fn(query, max_results)
        except Exception as exc:
            _cooldowns[name] = time.monotonic() + COOLDOWN_S
            message = f"{type(exc).__name__}: {exc}"
            errors.append(f"{name}: {message}")
            attempts.append({"provider": name, "outcome": "failed", "error": message})
            logger.warning("Search provider %s failed (%s); cooling down %.0fs",
                           name, message, COOLDOWN_S)
            continue

        attempts.append({
            "provider": name,
            "outcome": "ok",
            "n": len(results),
            "seconds": round(time.monotonic() - started, 2),
        })
        if results:
            return {"results": results, "provider": name, "attempts": attempts,
                    "errors": errors, "empty_confirmed_by": []}

        # An empty answer is not yet an answer. See EMPTY_CONFIRMATIONS.
        answered_empty.append(name)
        if len(answered_empty) >= EMPTY_CONFIRMATIONS:
            return {"results": [], "provider": name, "attempts": attempts,
                    "errors": errors, "empty_confirmed_by": list(answered_empty)}

    return {"results": [], "provider": answered_empty[-1] if answered_empty else "",
            "attempts": attempts, "errors": errors,
            "empty_confirmed_by": list(answered_empty)}


def search_or_raise(query: str, max_results: int = 8) -> dict[str, Any]:
    """As `search`, but raises AllProvidersFailed when nothing could be reached.

    For callers that must not report our own outage as a finding about the
    company -- see agents/founder_research.py.
    """
    outcome = search(query, max_results)
    if not outcome["provider"] and outcome["errors"]:
        raise AllProvidersFailed("; ".join(outcome["errors"]))
    if not outcome["provider"]:
        raise AllProvidersFailed(
            "No search provider is configured or available: "
            + "; ".join(a["outcome"] for a in outcome["attempts"])
        )
    return outcome
