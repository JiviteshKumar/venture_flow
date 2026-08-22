"""Request rate limiting.

Local/single-instance default: an in-memory sliding-window counter, same
behavior as the original inline implementation in api.py. That's correct for
exactly one running process -- the moment this API is scaled to more than one
instance (or more than one worker process), each instance keeps its own
counter and the effective limit multiplies by the instance count.

If REDIS_URL is set, this switches to a Redis-backed fixed-minute-bucket
counter instead, so the limit is enforced correctly across every instance
sharing that Redis. The Redis path is deliberately a fixed 60s bucket rather
than a true sliding window -- it's the standard trade for a counter that's
correct across processes without a cleanup job (the key self-expires), at the
cost of being slightly more permissive right at a minute boundary. That's an
acceptable trade for an abuse guard, not a billing meter.

Falls back to in-memory (with a single logged warning, not one per request)
if REDIS_URL is set but the `redis` package isn't installed or Redis is
unreachable -- a rate limiter failing must never mean requests get blocked
entirely, so the failure mode here is "back to per-instance limiting."
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "").strip()
_redis_client = None
_redis_warned = False


def _get_redis():
    global _redis_client, _redis_warned
    if not REDIS_URL:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis  # optional dependency -- only imported if REDIS_URL is set

        client = redis.from_url(REDIS_URL, socket_timeout=1, socket_connect_timeout=1)
        client.ping()
        _redis_client = client
        return client
    except Exception as exc:
        if not _redis_warned:
            logger.warning(
                "REDIS_URL is set but Redis is unreachable (%s) -- falling back "
                "to in-memory, per-instance rate limiting.",
                exc,
            )
            _redis_warned = True
        return None


_memory_windows: dict[str, deque[float]] = defaultdict(deque)


def is_allowed(client_key: str, limit_per_minute: int) -> bool:
    """Return True if `client_key` is still under its per-minute budget,
    recording this request as counted either way this returns."""
    redis_client = _get_redis()
    if redis_client is not None:
        try:
            return _is_allowed_redis(redis_client, client_key, limit_per_minute)
        except Exception as exc:
            logger.warning(
                "Redis rate-limit check failed (%s) -- falling back to "
                "in-memory for this request.",
                exc,
            )
    return _is_allowed_memory(client_key, limit_per_minute)


def _is_allowed_redis(redis_client, client_key: str, limit_per_minute: int) -> bool:
    bucket = f"ratelimit:{client_key}:{int(time.time() // 60)}"
    count = redis_client.incr(bucket)
    if count == 1:
        redis_client.expire(bucket, 90)
    return count <= limit_per_minute


def _is_allowed_memory(client_key: str, limit_per_minute: int) -> bool:
    now = time.monotonic()
    window = _memory_windows[client_key]
    while window and now - window[0] >= 60:
        window.popleft()
    if len(window) >= limit_per_minute:
        return False
    window.append(now)
    return True
