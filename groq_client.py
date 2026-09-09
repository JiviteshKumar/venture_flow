"""Single source of truth for the Groq client and model name.

The client used to be constructed eagerly (``client = Groq(api_key=...)``) at
import time in five separate modules. Groq's SDK raises immediately if no API
key is resolvable, which meant the whole application — including unrelated
routes like ``/health`` — failed to even import without GROQ_API_KEY set.
Building the client lazily on first use means missing/bad credentials only
fail the specific analysis call that needs them, and every call site already
wraps Groq calls in try/except with a safe fallback.
"""

from __future__ import annotations

import logging
import os
import re

import threading
import time

from dotenv import load_dotenv
from groq import Groq

logger = logging.getLogger(__name__)

# Load .env HERE, in the module that owns the credential.
#
# This module called itself "the single source of truth for the Groq client"
# while depending on some *other* module having already called load_dotenv().
# api.py and ventureflow_agent.py do; a script that imports
# `agents.investment_agents` directly does not, and there is nothing in the
# import graph that makes that obvious.
#
# The failure mode is quiet and expensive. With no key the SDK builds a
# request with an empty `Authorization: Bearer ` header, httpx rejects it as an
# illegal header value, and the SDK re-raises that as APIConnectionError -- so
# a missing credential is reported as "provider unreachable". An evaluation
# harness ran 24 specialist calls against that and recorded every one as a
# provider outage; it correctly refused to score them, but the diagnosis it
# offered pointed at Groq rather than at a missing .env load.
#
# `override=False` so a real environment variable (Render, CI) always wins over
# a local .env file.
load_dotenv(override=False)

# Model choice, 22 Aug 2026: this was "llama-3.3-70b-versatile" until Groq
# decommissioned it -- the key still authenticates fine, but that model id now
# returns a 404 model_not_found, which silently killed every LLM-backed feature
# in the app (claim verification, founder verification, risk detection, all four
# specialist agents, memo synthesis, structured extraction, chat). Confirmed by
# listing the models actually available on this key: no Llama 3.3 of any size is
# offered any more. openai/gpt-oss-120b is the closest available drop-in for a
# 70B-class instruct model and is what every call site now uses. If this 404s in
# future, re-list with `Groq().models.list()` rather than guessing an id.
MODEL = "openai/gpt-oss-120b"

_client: Groq | None = None

# Groq's free tier allows 8,000 tokens per MINUTE (confirmed from the live
# x-ratelimit-limit-tokens header on this account). A single due-diligence run
# spends far more than that: five claim verifications, four specialist agents
# and a 2,500-token memo add up to roughly 30-50k tokens. Without retries the
# SDK gives up after two attempts, every call past the first few in a burst
# returns 429, and each one silently degrades to a fallback -- regex extraction
# instead of schema-validated extraction, canned specialist results with
# confidence 0, and a stub memo. The report still renders, so nothing looks
# broken; it is just empty. That was the actual cause of twenty decks all
# scoring 30/100, and it presented as a scoring bug rather than a quota one.
#
# The SDK honours the Retry-After header on 429s, so raising max_retries lets a
# run ride out the per-minute window instead of collapsing into fallbacks. This
# trades latency for actually producing a report, which is the right trade for
# a tool whose output takes minutes anyway.
MAX_RETRIES = int(os.environ.get("GROQ_MAX_RETRIES", "6"))
REQUEST_TIMEOUT_S = float(os.environ.get("GROQ_TIMEOUT_S", "90"))


def get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(
            api_key=os.environ.get("GROQ_API_KEY", ""),
            max_retries=MAX_RETRIES,
            timeout=REQUEST_TIMEOUT_S,
        )
    return _client


# ── Per-minute token pacing ───────────────────────────────────────────────
#
# The free tier allows 8,000 tokens per MINUTE. A full deck analysis costs
# roughly 24,000 tokens across ~12 calls -- claim verification (up to 5),
# risk (1), four specialists, memo synthesis, structured extraction. The
# arithmetic is unforgiving: a deck needs at least three minutes of budget, so
# no amount of batching or prompt trimming brings it under the ceiling.
#
# What the pipeline did instead was spend it all at once. Claim verification
# fires concurrently, specialists run two at a time, and the burst blew the
# window within seconds. Every call after that returned 429, each component
# degraded to its fallback, and the report came back "provider_degraded" with
# most of its analysis missing -- measured on six of six real deck runs, even
# at GROQ_AGENT_CONCURRENCY=1.
#
# So the fix is not to spend less, it is to spend at the rate the tier allows.
# This pacer makes a deck take three to four minutes and COMPLETE, instead of
# taking forty seconds and arriving hollow. Slower and correct beats fast and
# degraded for an analysis a user waits on anyway.
#
# Deliberately process-local and approximate. It is not a distributed limiter
# and does not need to be: the constraint is one process against one free-tier
# key. Disable with GROQ_PACING=off if you move to a paid tier with real
# headroom.
class TokenPacer:
    """Blocks until an estimated request fits inside the per-minute budget."""

    def __init__(self, tokens_per_minute: int, safety: float = 0.85) -> None:
        self.budget = max(1, int(tokens_per_minute * safety))
        self._lock = threading.Lock()
        self._window_start = time.monotonic()
        self._spent = 0

    def reserve(self, estimated_tokens: int) -> float:
        """Wait if needed, then record the spend. Returns seconds waited."""
        waited = 0.0
        with self._lock:
            now = time.monotonic()
            if now - self._window_start >= 60.0:
                self._window_start, self._spent = now, 0
            if self._spent + estimated_tokens > self.budget:
                waited = max(0.0, 60.0 - (now - self._window_start)) + 0.5
        if waited:
            logger.info("Pacing %.0fs to stay inside the per-minute token budget", waited)
            time.sleep(waited)
            with self._lock:
                self._window_start, self._spent = time.monotonic(), 0
        with self._lock:
            self._spent += max(0, int(estimated_tokens))
        return waited

    def settle(self, reserved_tokens: int, actual_tokens: int) -> int:
        """Give back the part of a reservation the call did not use.

        Returns the number of tokens refunded, for logging and tests.

        Only ever refunds DOWN to zero spend, and never refunds more than was
        reserved, so a wrong `actual` cannot manufacture budget. If the window
        rolled over between the reservation and the response there is nothing
        meaningful to refund -- the spend being corrected belongs to a window
        that has already closed -- so the refund is skipped.
        """
        refund = max(0, int(reserved_tokens) - max(0, int(actual_tokens)))
        if not refund:
            return 0
        with self._lock:
            if time.monotonic() - self._window_start >= 60.0:
                return 0
            refund = min(refund, self._spent)
            self._spent -= refund
        return refund


TOKENS_PER_MINUTE = int(os.getenv("GROQ_TOKENS_PER_MINUTE", "8000"))
PACING_ENABLED = os.getenv("GROQ_PACING", "on").strip().lower() not in {"off", "0", "false"}
_pacer = TokenPacer(TOKENS_PER_MINUTE)


# ── Daily-quota circuit breaker ───────────────────────────────────────────
#
# There are two kinds of 429 on this tier and they need opposite responses.
#
# A tokens-per-MINUTE 429 clears in seconds. The SDK retries it, honours
# Retry-After, and the call usually succeeds -- that is what MAX_RETRIES is for.
#
# A tokens-per-DAY 429 does not clear for hours:
#
#   Rate limit reached ... on tokens per day (TPD): Limit 200000, Used 199553,
#   Requested 3416. Please try again in 21m22.608s
#
# Retrying that is pure waste, and the waste compounds: an analysis makes about
# a dozen LLM calls, and without this every one of them spends six retries and
# up to 90 seconds of timeout discovering the same exhausted quota. The run
# takes many minutes and produces a report with nothing in it.
#
# So the first TPD refusal trips a breaker and every later call fails
# immediately with the same, accurate reason. The components still degrade --
# that path is well-tested -- but they degrade in milliseconds and say WHY,
# instead of timing out one after another.
#
# The TPD ceiling is worth stating plainly because it is easy to miss: it is
# 200,000 tokens/day, it appears in NO response header (only TPM and RPD do),
# and the only way to discover it is to hit it.
class DailyQuotaExhausted(RuntimeError):
    """The daily token allowance is spent. Retrying will not help today."""


_daily_quota_blocked_until: float = 0.0
_daily_quota_reason: str = ""


def _parse_retry_seconds(message: str) -> float:
    """Seconds from a "try again in 21m22.608s" message. 0 when absent."""
    match = re.search(r"try again in\s+(?:(\d+)m)?\s*([\d.]+)s", message, re.IGNORECASE)
    if not match:
        return 0.0
    minutes = float(match.group(1) or 0)
    seconds = float(match.group(2) or 0)
    return minutes * 60 + seconds


def is_daily_quota_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "429" in text and ("tokens per day" in text or "tpd" in text)


def note_provider_failure(exc: BaseException) -> None:
    """Record a failure so later calls can skip a hopeless retry.

    Only a daily-quota refusal trips the breaker; a per-minute 429 is retryable
    and must not stop the run.
    """
    global _daily_quota_blocked_until, _daily_quota_reason
    if not is_daily_quota_error(exc):
        return
    wait = _parse_retry_seconds(str(exc)) or 900.0
    _daily_quota_blocked_until = time.monotonic() + wait
    _daily_quota_reason = (
        f"Groq daily token quota (200,000/day) is exhausted. It resets in "
        f"about {max(1, round(wait / 60))} minute(s); retrying before then "
        f"fails the same way."
    )
    logger.error("Daily Groq quota exhausted; pausing LLM calls for %.0fs", wait)


def daily_quota_status() -> dict[str, object]:
    """For /health and the report's degradation block."""
    remaining = _daily_quota_blocked_until - time.monotonic()
    return {
        "exhausted": remaining > 0,
        "seconds_until_reset": max(0, round(remaining)),
        "reason": _daily_quota_reason if remaining > 0 else "",
    }


def reset_quota_breaker() -> None:
    """For tests, and for an operator who has upgraded the tier."""
    global _daily_quota_blocked_until, _daily_quota_reason
    _daily_quota_blocked_until = 0.0
    _daily_quota_reason = ""


def estimate_tokens(prompt_chars: int, max_tokens: int) -> int:
    """The reservation `pace_for` makes for a call of this shape.

    Exposed so a caller can hand the same number back to `settle_usage` without
    having to know the formula.
    """
    return prompt_chars // 4 + max_tokens


def settle_usage(response: object, prompt_chars: int, max_tokens: int) -> int:
    """Reconcile a completed call against what it actually cost.

    Call this immediately after a successful `chat.completions.create`. The
    pacer reserved `max_tokens` of completion budget; this returns whatever the
    model did not use to the current minute's window, so the next call is not
    made to wait for tokens nobody spent.

    Never raises. This runs on the success path of a call that has already
    worked, and a failure to do bookkeeping must not turn a good response into
    an exception -- so a response object without usage, or with a shape this
    does not recognise, simply refunds nothing and leaves the pacer exactly as
    it is today.
    """
    if not PACING_ENABLED:
        return 0
    try:
        usage = getattr(response, "usage", None)
        actual = int(getattr(usage, "total_tokens", 0) or 0)
        if actual <= 0:
            return 0
        refunded = _pacer.settle(estimate_tokens(prompt_chars, max_tokens), actual)
        if refunded:
            logger.debug("Returned %d unused tokens to the pacing window", refunded)
        return refunded
    except Exception:  # pragma: no cover - bookkeeping must never fail a call
        logger.debug("Could not settle token usage", exc_info=True)
        return 0


def pace_for(prompt_chars: int, max_tokens: int = 1000) -> float:
    """Reserve budget for a call of roughly this size.

    Four characters per token is the usual rough conversion and is close enough:
    the pacer only needs to be approximately right to keep a burst from
    exceeding the window.

    Raises `DailyQuotaExhausted` when the daily allowance is known to be spent.
    Every LLM call site in this codebase calls this first, which makes it the
    one place a breaker can cover all of them; each already wraps its call in a
    try/except that degrades honestly, so the exception surfaces as a stated
    degradation rather than a crash.
    """
    if _daily_quota_blocked_until > time.monotonic():
        raise DailyQuotaExhausted(_daily_quota_reason)
    if not PACING_ENABLED:
        return 0.0
    return _pacer.reserve(prompt_chars // 4 + max_tokens)
