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

import os

from dotenv import load_dotenv
from groq import Groq

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
