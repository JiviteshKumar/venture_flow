"""Neon persistence for completed VentureFlow due-diligence runs."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()
logger = logging.getLogger(__name__)


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return (
        url
        if "sslmode=" in url
        else f"{url}{'&' if '?' in url else '?'}sslmode=require"
    )


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        _database_url(), connect_timeout=10, row_factory=dict_row
    ) as conn:
        yield conn


def healthcheck() -> bool:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 AS ok")
        return cur.fetchone()["ok"] == 1


def ensure_schema() -> None:
    """Apply the repository's idempotent Neon schema migrations.

    Render starts the API directly, so a separate migration command is easy to
    miss.  Taking a transaction-scoped advisory lock makes startup safe when a
    service is scaled beyond one process.
    """
    migration_dir = Path(__file__).resolve().parent / "migrations"
    migrations = sorted(
        path
        for path in migration_dir.glob("*.sql")
        if not path.name.endswith(".down.sql")
    )
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (724420221,))
        for migration in migrations:
            cur.execute(migration.read_text(encoding="utf-8"))
        conn.commit()
    logger.info("Applied %s Neon schema migration(s)", len(migrations))


def find_similar_companies(
    name: str, domain: str | None, sector: str | None
) -> list[dict[str, Any]]:
    """Return investment/report matches using sector and PostgreSQL fuzzy matching."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT c.id, c.name, c.domain, c.sector,
                CASE
                    WHEN lower(c.name) = lower(%(name)s) THEN 1.0
                    ELSE greatest(similarity(c.name, %(name)s), similarity(coalesce(c.domain, ''), coalesce(%(domain)s::text, '')))
                END AS similarity
            FROM companies c
            LEFT JOIN portfolio_investments pi ON pi.company_id = c.id
            LEFT JOIN dd_reports dr ON dr.company_id = c.id
            WHERE c.name <> %(name)s
              AND (pi.id IS NOT NULL OR dr.id IS NOT NULL)
              AND (
                    ( %(sector)s::text IS NOT NULL AND c.sector = %(sector)s::text )
                    OR similarity(c.name, %(name)s) >= 0.35
                    OR (%(domain)s::text IS NOT NULL AND similarity(coalesce(c.domain, ''), %(domain)s::text) >= 0.5)
              )
            ORDER BY similarity DESC, c.name
            LIMIT 5
            """,
            {"name": name, "domain": domain, "sector": sector},
        )
        return list(cur.fetchall())


def persist_report(
    *,
    name: str,
    description: str,
    sector: str | None,
    domain: str | None,
    report: dict[str, Any],
) -> str:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO companies (name, domain, sector, description)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET
                domain = COALESCE(EXCLUDED.domain, companies.domain),
                sector = COALESCE(EXCLUDED.sector, companies.sector),
                description = COALESCE(NULLIF(EXCLUDED.description, ''), companies.description)
            RETURNING id
            """,
            (name, domain, sector, description),
        )
        company_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO dd_reports (company_id, summary, verdict, raw_output)
            VALUES (%s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            (
                company_id,
                report.get("sections", {}).get("ai_analysis", ""),
                report.get("recommendation", "NEEDS MORE DILIGENCE"),
                json.dumps(report, default=str),
            ),
        )
        report_id = str(cur.fetchone()["id"])
        conn.commit()
        return report_id


def list_reports(limit: int = 20) -> list[dict[str, Any]]:
    """Return compact saved-report metadata for the history view."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT dr.id::text AS report_id, c.name AS company,
                   COALESCE((dr.raw_output ->> 'final_score')::float, 0) AS final_score,
                   COALESCE(dr.verdict, 'NEEDS MORE DILIGENCE') AS recommendation,
                   dr.created_at
            FROM dd_reports dr JOIN companies c ON c.id = dr.company_id
            ORDER BY dr.created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return list(cur.fetchall())


def get_report(report_id: str) -> dict[str, Any] | None:
    """Load the persisted raw report by its externally supplied identifier."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT dr.id::text AS report_id, c.name AS company, dr.raw_output
            FROM dd_reports dr JOIN companies c ON c.id = dr.company_id
            WHERE dr.id::text = %s
            """,
            (report_id,),
        )
        return cur.fetchone()


def create_analysis_job(payload: dict[str, Any]) -> str:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO analysis_jobs (request_payload) VALUES (%s::jsonb) RETURNING id::text",
            (json.dumps(payload, default=str),),
        )
        job_id = cur.fetchone()["id"]
        conn.commit()
        return job_id


def update_analysis_job(job_id: str, status: str, result: dict[str, Any] | None = None, error_message: str | None = None) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE analysis_jobs SET status = %s,
                result = COALESCE(%s::jsonb, result), error_message = %s,
                started_at = CASE WHEN %s = 'running' THEN now() ELSE started_at END,
                completed_at = CASE WHEN %s IN ('complete', 'failed') THEN now() ELSE completed_at END
            WHERE id::text = %s
            """,
            (status, json.dumps(result, default=str) if result is not None else None, error_message, status, status, job_id),
        )
        conn.commit()


def get_analysis_job(job_id: str) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id::text AS job_id, status, result, error_message FROM analysis_jobs WHERE id::text = %s", (job_id,))
        return cur.fetchone()


def upsert_chat_session(
    session_id: str, company: str, document_text: str, history: list[dict[str, Any]]
) -> None:
    """Persist (or refresh) a chat session's document text and Q&A history."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chat_sessions (session_id, company, document_text, history, updated_at)
            VALUES (%s, %s, %s, %s::jsonb, now())
            ON CONFLICT (session_id) DO UPDATE SET
                company = EXCLUDED.company,
                document_text = EXCLUDED.document_text,
                history = EXCLUDED.history,
                updated_at = now()
            """,
            (session_id, company, document_text, json.dumps(history, default=str)),
        )
        conn.commit()


def get_chat_session(session_id: str) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT session_id, company, document_text, history FROM chat_sessions WHERE session_id = %s",
            (session_id,),
        )
        return cur.fetchone()


def delete_chat_session(session_id: str) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM chat_sessions WHERE session_id = %s", (session_id,))
        conn.commit()


def record_decision(report_id: str, decision: str, notes: str = "") -> None:
    """Record (or update) the user's own invest/pass call on a report -- the
    feedback signal ml/personalization.py trains against."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO investment_decisions (report_id, decision, notes)
            VALUES (%s, %s, %s)
            ON CONFLICT (report_id) DO UPDATE SET
                decision = EXCLUDED.decision, notes = EXCLUDED.notes, decided_at = now()
            """,
            (report_id, decision, notes),
        )
        conn.commit()


def list_decisions_with_reports() -> list[dict[str, Any]]:
    """Return every recorded decision joined to its report's raw_output, for
    training the personalization model."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.decision, dr.raw_output
            FROM investment_decisions d
            JOIN dd_reports dr ON dr.id = d.report_id
            ORDER BY d.decided_at
            """
        )
        return list(cur.fetchall())


def count_decisions() -> int:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM investment_decisions")
        return cur.fetchone()["n"]


def stats() -> dict[str, int]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT (SELECT count(*) FROM companies) AS companies, (SELECT count(*) FROM dd_reports) AS dd_reports, (SELECT count(*) FROM portfolio_investments) AS portfolio_investments"
        )
        return dict(cur.fetchone())
