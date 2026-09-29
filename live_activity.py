"""What the pipeline is doing right now, as it does it.

## Why

`_stage()` reports seven labels over a run that takes five to ten minutes.
Between "Verifying claims against live web search" and the next label the
product goes quiet for minutes while it runs dozens of real searches and
fetches dozens of real pages -- and the screen showed a spinner and a word.

A reader watching that has no way to tell a slow analysis from a hung one, and
no sense that anything is being looked up at all. The work is the most
interesting thing this product does and it was the least visible.

So the searches and fetches report themselves. Every entry here is a network
call that actually happened, recorded at the moment it happened, with the URL
it went to. Nothing is generated to fill the feed: when the pipeline is
thinking rather than fetching, the feed says nothing new, which is the truth.

## How it is scoped

Keyed on `observability.current_job_id()`, the contextvar that already tags
every log line with its run. Using it rather than a second notion of "which
analysis is this" means the feed and the logs agree by construction, and a
caller polling for job A can never be shown job B's traffic.

`run_in_threadpool` propagates contextvars into the worker thread, so the
pipeline's own calls carry the id. Work handed to a bare `ThreadPoolExecutor`
-- the four specialist agents -- does not inherit it, and those calls are
simply not recorded rather than being recorded against the wrong job. A
missing entry is a smaller lie than a misattributed one.

## What keeps it cheap

In-process, bounded, and never persisted: this is a live feed, not a log.
Older entries fall off the end, finished jobs are evicted when a new one
starts, and every function here swallows its own errors. Telling someone what
is happening must never be able to stop it happening.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from typing import Any, Deque
from urllib.parse import urlparse

import observability

#: Entries kept per job. Enough to fill a panel and scroll a little; a run that
#: fetches two hundred pages does not need all two hundred on screen.
MAX_PER_JOB = 80

#: Jobs kept at once. One is the normal case; a few covers a reader still
#: polling an old job while a new one starts.
MAX_JOBS = 4

_lock = threading.Lock()
_feeds: "OrderedDict[str, Deque[dict[str, Any]]]" = OrderedDict()


def _host(url: str) -> str:
    """The part a person recognises."""
    try:
        return urlparse(url).hostname.replace("www.", "") or url[:60]
    except Exception:
        return (url or "")[:60]


def record(kind: str, detail: str, *, url: str = "", ok: bool | None = None) -> None:
    """Note one thing the pipeline just did. Never raises.

    `kind` is a short machine token the UI styles on ("search", "fetch").
    `detail` is what to show: a query, or what the fetch was for.
    """
    try:
        job_id = observability.current_job_id()
        if not job_id:
            return
        entry = {
            "at": time.time(),
            "kind": kind,
            "detail": (detail or "")[:160],
            "url": (url or "")[:400],
            "host": _host(url) if url else "",
        }
        if ok is not None:
            entry["ok"] = ok
        with _lock:
            feed = _feeds.get(job_id)
            if feed is None:
                feed = deque(maxlen=MAX_PER_JOB)
                _feeds[job_id] = feed
                while len(_feeds) > MAX_JOBS:
                    _feeds.popitem(last=False)
            _feeds.move_to_end(job_id)
            feed.append(entry)
    except Exception:
        pass


def recent(job_id: str, limit: int = 40) -> list[dict[str, Any]]:
    """The newest entries for a job, oldest first. Never raises."""
    try:
        with _lock:
            feed = _feeds.get(job_id)
            if not feed:
                return []
            items = list(feed)
        return items[-limit:]
    except Exception:
        return []


def clear(job_id: str) -> None:
    """Drop a job's feed. Never raises."""
    try:
        with _lock:
            _feeds.pop(job_id, None)
    except Exception:
        pass


def reset_for_tests() -> None:
    with _lock:
        _feeds.clear()
