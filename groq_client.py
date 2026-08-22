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

MODEL = "llama-3.3-70b-versatile"

_client: Groq | None = None


def get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
    return _client
