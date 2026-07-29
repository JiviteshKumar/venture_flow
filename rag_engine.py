"""Read-only Neon report context for the synthesis and chat paths."""

from __future__ import annotations

import logging
from typing import Any

from db import connection

logger = logging.getLogger(__name__)


def build_context(query: str, top_k: int = 5) -> dict[str, Any]:
    """Retrieve prior diligence reports by simple, dependency-free text matching.

    The current Neon schema intentionally avoids an embedding service. Search failure is
    non-fatal: synthesis must be able to finish from supplied evidence alone.
    """
    terms = [term for term in query.lower().split() if len(term) >= 4][:5]
    if not terms:
        return {"query": query, "relevant_reports": []}
    try:
        with connection() as conn, conn.cursor() as cur:
            predicates = " OR ".join(
                "lower(c.name || ' ' || c.description) LIKE %s" for _ in terms
            )
            cur.execute(
                f"""
                SELECT c.name, c.sector, dr.summary, dr.verdict, dr.created_at
                FROM dd_reports dr JOIN companies c ON c.id = dr.company_id
                WHERE {predicates}
                ORDER BY dr.created_at DESC
                LIMIT %s
                """,
                [f"%{term}%" for term in terms] + [top_k],
            )
            return {"query": query, "relevant_reports": list(cur.fetchall())}
    except Exception:
        logger.warning("Neon context retrieval unavailable", exc_info=True)
        return {"query": query, "relevant_reports": []}


def format_context_for_llm(context: dict[str, Any]) -> str:
    reports = context.get("relevant_reports", [])
    if not reports:
        return "No prior diligence reports matched this query."
    lines = [
        "PRIOR DILIGENCE REPORTS (context only; do not treat as independent verification):"
    ]
    for report in reports:
        lines.append(
            f"- {report['name']} ({report.get('sector') or 'unclassified'}): {report['verdict']}. {report['summary'][:500]}"
        )
    return "\n".join(lines)
