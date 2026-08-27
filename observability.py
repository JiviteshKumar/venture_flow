"""Structured logging and error tracking.

WHY THIS EXISTS

Every bug found in the last three sessions was found by a human reading stdout.
The constant-30 score, the claim verifier judging 2011 metrics against 2026
evidence, the degradation flag that string-matched prose and missed half its own
cases, the corpus collector that recorded fetch failures as "no risk language" --
all of them were visible in logs nobody was aggregating, and all of them ran in
production for days or weeks.

The common shape is worth naming: **none of these were crashes.** They were
typed fallbacks. The code caught an exception, degraded politely, logged a line,
and carried on returning a plausible answer. An error tracker that only reports
unhandled exceptions would have reported zero of them.

So this module tracks two different things:

  - **Exceptions**, via Sentry when it is configured.
  - **Degradation events** -- a Groq 429, an extraction failure, a specialist
    agent falling back, a relevance gate dropping every source. Individually
    routine; in aggregate the single most useful signal this product has, because
    "how often is the analysis actually degraded in practice" is a question
    nobody has ever been able to answer.

DESIGN

Sentry is optional and env-gated, following the pattern `rate_limiter.py` uses
for Redis: if `SENTRY_DSN` is unset, or `sentry-sdk` is not installed, this
degrades to structured logs and says so once. It never becomes a hard
dependency, because a monitoring tool that can break the thing it monitors is a
bad trade -- and because a fresh clone has no DSN.

Logs are JSON lines, which are queryable by Render's log search, `jq`, or
anything else, with no dashboard to build. The in-process counters are exposed
at `/observability` for the same reason: the goal is answerable questions, not
visualization.

`job_id` propagates through a contextvar, so every log line emitted anywhere
inside an analysis carries it without every call site having to pass it down.
That is the specific thing that made past debugging sessions painful: log lines
from four concurrent agents interleaved with no way to tell which analysis each
belonged to.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import threading
import time
from collections import Counter
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
LOG_FORMAT = os.getenv("LOG_FORMAT", "json").strip().lower()

# Ambient context, so a log line from deep inside an agent still says which
# analysis it belongs to.
_job_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("job_id", default=None)
_company: contextvars.ContextVar[str | None] = contextvars.ContextVar("company", default=None)

_sentry = None
_sentry_state = "not initialised"

# In-process aggregates. Deliberately simple: a Counter and a lock, reset on
# restart. This is not a metrics backend and does not pretend to be one -- it
# answers "what has degraded since this process started", which is the question
# that currently has no answer at all.
_counter_lock = threading.Lock()
_event_counts: Counter[str] = Counter()
_recent_events: list[dict[str, Any]] = []
MAX_RECENT_EVENTS = 200
_started_at = time.time()


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with ambient job context attached."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        job = _job_id.get()
        if job:
            payload["job_id"] = job
        company = _company.get()
        if company:
            payload["company"] = company
        # Anything passed via `extra=` on the logging call.
        for key, value in getattr(record, "__dict__", {}).items():
            if key.startswith("vf_"):
                payload[key[3:]] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        try:
            return json.dumps(payload, default=str)
        except Exception:
            # Logging must never raise. A log line that cannot be serialised is
            # still worth emitting in a degraded form.
            return json.dumps({"ts": payload["ts"], "level": payload["level"],
                               "message": str(record.getMessage())[:2000]})


def configure_logging(level: str | None = None) -> None:
    """Install the JSON formatter on the root logger.

    Replaces handlers rather than adding one, because `logging.basicConfig` has
    usually already installed a plain-text handler by the time this runs and two
    handlers means every line is emitted twice.
    """
    root = logging.getLogger()
    root.setLevel(level or os.getenv("LOG_LEVEL", "INFO"))
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter() if LOG_FORMAT == "json"
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)


def init_sentry() -> str:
    """Initialise Sentry if configured. Returns a human-readable state string.

    Never raises. A monitoring tool that can break the application it monitors
    is a bad trade, and this one runs at import time on a cold start.
    """
    global _sentry, _sentry_state
    if not SENTRY_DSN:
        _sentry_state = "disabled (SENTRY_DSN not set)"
        return _sentry_state
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        _sentry_state = "unavailable (sentry-sdk not installed; pip install sentry-sdk)"
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed")
        return _sentry_state
    try:
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            environment=ENVIRONMENT,
            # Errors are the point; traces are not, and a free tier is small.
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
            integrations=[
                FastApiIntegration(),
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
            # Deck text is a founder's confidential material. Never ship it.
            send_default_pii=False,
            max_request_body_size="never",
        )
        _sentry = sentry_sdk
        _sentry_state = f"active ({ENVIRONMENT})"
    except Exception as exc:
        _sentry_state = f"failed to initialise ({type(exc).__name__})"
        logger.exception("Sentry initialisation failed")
    return _sentry_state


def sentry_state() -> str:
    return _sentry_state


@contextmanager
def job_context(job_id: str | None = None, company: str | None = None):
    """Attach job identity to every log line emitted inside this block."""
    job_token = _job_id.set(job_id)
    company_token = _company.set(company)
    if _sentry is not None:
        try:
            scope = _sentry.get_current_scope()
            if job_id:
                scope.set_tag("job_id", job_id)
            if company:
                scope.set_tag("company", company)
        except Exception:
            pass
    try:
        yield
    finally:
        _job_id.reset(job_token)
        _company.reset(company_token)


def track_degradation(
    event: str,
    *,
    component: str,
    reason: str = "",
    **details: Any,
) -> None:
    """Record a typed, non-crashing failure.

    This is the function that would have surfaced every bug listed in this
    module's docstring. `event` is a stable slug so events aggregate across runs
    -- "groq_rate_limited", "extraction_empty", "specialist_fallback" -- and
    `component` says where.

    Never raises. Tracking a problem must not be able to cause one.
    """
    try:
        key = f"{event}:{component}"
        record = {
            "event": event,
            "component": component,
            "reason": reason,
            "job_id": _job_id.get(),
            "company": _company.get(),
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **details,
        }
        with _counter_lock:
            _event_counts[key] += 1
            _recent_events.append(record)
            if len(_recent_events) > MAX_RECENT_EVENTS:
                del _recent_events[: len(_recent_events) - MAX_RECENT_EVENTS]

        logger.warning(
            "degradation: %s in %s (%s)", event, component, reason or "no reason given",
            extra={"vf_event": event, "vf_component": component,
                   "vf_reason": reason, "vf_kind": "degradation"},
        )

        if _sentry is not None:
            # A breadcrumb, not an exception: these are expected-but-notable
            # events, and reporting each as an error would drown the real ones.
            _sentry.add_breadcrumb(
                category="degradation", level="warning",
                message=f"{event} in {component}", data=record,
            )
    except Exception:
        pass


def snapshot() -> dict[str, Any]:
    """Aggregate counts since process start, for the /observability endpoint."""
    with _counter_lock:
        counts = dict(_event_counts)
        recent = list(_recent_events[-25:])
    return {
        "uptime_seconds": round(time.time() - _started_at, 1),
        "sentry": _sentry_state,
        "log_format": LOG_FORMAT,
        "degradation_counts": counts,
        "total_degradation_events": sum(counts.values()),
        "recent_events": recent,
        "note": (
            "Counts are in-process and reset on restart. They answer 'what has "
            "degraded since this process started', which is a question that "
            "previously had no answer. They are not a metrics backend."
        ),
    }


def reset_for_tests() -> None:
    with _counter_lock:
        _event_counts.clear()
        _recent_events.clear()
