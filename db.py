"""Neon persistence for completed VentureFlow due-diligence runs."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
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
                    ELSE greatest(similarity(c.name, %(name)s), similarity(coalesce(c.domain, ''), coalesce(%(domain)s, '')))
                END AS similarity
            FROM companies c
            LEFT JOIN portfolio_investments pi ON pi.company_id = c.id
            LEFT JOIN dd_reports dr ON dr.company_id = c.id
            WHERE c.name <> %(name)s
              AND (pi.id IS NOT NULL OR dr.id IS NOT NULL)
              AND (
                    ( %(sector)s IS NOT NULL AND c.sector = %(sector)s )
                    OR similarity(c.name, %(name)s) >= 0.35
                    OR (%(domain)s IS NOT NULL AND similarity(coalesce(c.domain, ''), %(domain)s) >= 0.5)
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


def stats() -> dict[str, int]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT (SELECT count(*) FROM companies) AS companies, (SELECT count(*) FROM dd_reports) AS dd_reports, (SELECT count(*) FROM portfolio_investments) AS portfolio_investments"
        )
        return dict(cur.fetchone())
