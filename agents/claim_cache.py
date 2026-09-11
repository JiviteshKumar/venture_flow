"""Remember claim verdicts, so re-checking an unchanged claim gives the same answer.

Verdicts on the same deck differed between runs because retrieval does: the web
returns a different set of pages each time, and a different set of pages can
support a different verdict. See migrations/011_claim_verdict_cache.sql.

The cache is deliberately conservative:

  * It is keyed on everything that changes what the answer should be -- the
    claim text, the company, the deck vintage the claim is judged against, the
    search mode, and a version string bumped whenever the verifier's behaviour
    changes, so a verdict from older logic is never served.
  * It never stores a degraded verdict -- a provider outage, an unreadable
    judge reply, or evidence gathered while the general web index was
    rate-limited. Freezing a weak answer would be worse than no cache.
  * It is best-effort. A database that is unreachable means a cache miss, never
    a failed claim check.

Every cached result says so (`cached: true`, `cached_at`), so a reader can tell
a fresh check from a remembered one.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

ENABLED = os.getenv("VENTUREFLOW_CLAIM_CACHE", "on").strip().lower() not in {"off", "0", "false", "no"}
TTL_DAYS = float(os.getenv("VENTUREFLOW_CLAIM_CACHE_DAYS", "7"))

# Bump when the verifier's retrieval or judging changes, so verdicts produced by
# older logic stop being served the moment the new logic ships.
VERSION = "2026-09-12.routing-v1"

# Fields that are this run's working state rather than part of the verdict.
_NOT_STORED = {"evidence_text"}


def _normalise(text: str) -> str:
    return " ".join((text or "").split()).lower()


def cache_key(claim: str, company: str, as_of: str, search: str) -> str:
    payload = json.dumps([VERSION, _normalise(claim), _normalise(company),
                          (as_of or "").strip(), search or "company"])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cacheable(result: dict[str, Any]) -> bool:
    return bool(result) and not (
        result.get("_degraded") or result.get("evidence_degraded")
    )


def get(claim: str, company: str, as_of: str, search: str) -> dict[str, Any] | None:
    """The stored verdict for this exact check, if it is recent enough."""
    if not ENABLED:
        return None
    try:
        from db import connection

        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT result, created_at FROM claim_verdict_cache "
                "WHERE key = %s AND created_at > now() - make_interval(secs => %s)",
                (cache_key(claim, company, as_of, search), TTL_DAYS * 86400),
            )
            row = cur.fetchone()
    except Exception:
        logger.warning("Claim cache read failed; checking afresh", exc_info=True)
        return None
    if not row:
        return None
    result = dict(row["result"])
    created = row["created_at"]
    result["cached"] = True
    result["cached_at"] = created.isoformat() if hasattr(created, "isoformat") else str(created)
    return result


def put(claim: str, company: str, as_of: str, search: str, result: dict[str, Any]) -> bool:
    """Store a verdict. Returns whether it was stored."""
    if not ENABLED or not _cacheable(result):
        return False
    stored = {k: v for k, v in result.items()
              if k not in _NOT_STORED and k not in ("cached", "cached_at")}
    try:
        from db import connection

        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO claim_verdict_cache (key, claim, company, result, created_at)
                VALUES (%s, %s, %s, %s::jsonb, now())
                ON CONFLICT (key) DO UPDATE
                    SET result = EXCLUDED.result, created_at = now()
                """,
                (cache_key(claim, company, as_of, search), claim[:2000],
                 (company or "")[:200], json.dumps(stored, default=str)),
            )
            conn.commit()
        return True
    except Exception:
        logger.warning("Claim cache write failed; verdict not remembered", exc_info=True)
        return False


def checked_at_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
