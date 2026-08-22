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

from groq import Groq

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


def get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
    return _client
