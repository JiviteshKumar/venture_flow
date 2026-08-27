"""Neon persistence for completed VentureFlow due-diligence runs."""

from __future__ import annotations

import json
import logging
import os
import re
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


_pool = None


def _configure(conn: psycopg.Connection) -> None:
    """Per-connection setup, run once when the pool opens a connection rather
    than on every query."""
    try:
        from pgvector.psycopg import register_vector

        register_vector(conn)
    except Exception:
        # pgvector extension/migration not applied yet, or the optional
        # `pgvector` package isn't installed -- vector features degrade
        # gracefully (see persist_report / find_similar_reports_by_vector),
        # everything else in this module is unaffected.
        pass


def _get_pool():
    """Lazily build a connection pool.

    Every call to `connection()` used to open a brand-new psycopg connection.
    Against Neon that is not cheap: measured on this deployment, connecting
    takes ~1.57s and a trivial `SELECT 1` a further ~0.58s, while the actual
    query -- listing 20 reports -- takes 0.23s. So the dashboard's report list
    took 7.2s end-to-end, of which almost none was the database doing work.
    Every endpoint and every pipeline step paid that toll separately.

    A pool keeps connections warm, so only the first request per worker pays
    the handshake. `min_size=1` keeps one alive without holding open
    connections a free-tier Neon project would rather not spare; `max_size=8`
    covers the pipeline's concurrent steps.

    Falls back to direct connections if psycopg_pool is unavailable, so the
    module keeps working without the optional dependency.
    """
    global _pool
    if _pool is None:
        from psycopg_pool import ConnectionPool

        _pool = ConnectionPool(
            conninfo=_database_url(),
            min_size=1,
            max_size=8,
            timeout=30,
            max_idle=300,
            kwargs={"row_factory": dict_row, "connect_timeout": 10},
            configure=_configure,
            open=True,
        )
    return _pool


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    try:
        pool = _get_pool()
    except Exception:
        # psycopg_pool missing or the pool could not be built -- fall back to
        # the original one-connection-per-call behaviour rather than failing.
        logger.debug("Connection pool unavailable; using a direct connection", exc_info=True)
        with psycopg.connect(_database_url(), connect_timeout=10, row_factory=dict_row) as conn:
            _configure(conn)
            yield conn
        return

    with pool.connection() as conn:
        yield conn


def close_pool() -> None:
    """Close pooled connections on shutdown.

    Without this the pool's worker threads outlive the interpreter's attempt to
    join them and psycopg_pool prints "couldn't stop thread ... within 5.0
    seconds" on exit. Harmless, but it looks like a fault in the logs and is
    trivial to avoid.
    """
    global _pool
    if _pool is not None:
        try:
            _pool.close()
        except Exception:
            logger.debug("Error closing the connection pool", exc_info=True)
        _pool = None


def healthcheck() -> bool:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 AS ok")
        return cur.fetchone()["ok"] == 1


def ensure_schema() -> None:
    """Apply the repository's idempotent Neon schema migrations.

    Render starts the API directly, so a separate migration command is easy to
    miss.  Taking a transaction-scoped advisory lock makes startup safe when a
    service is scaled beyond one process.

    Each migration runs in its own savepoint. That is deliberate and was a
    real outage: this function used to apply every migration inside one
    transaction, so a single failing migration silently rolled back all the
    others. In practice migration 005 declared ``report_id UUID`` against a
    legacy database whose ``dd_reports.id`` is ``integer``, and that one
    DatatypeMismatch discarded migrations 004, 006 and 007 as well. The
    database then looked migrated -- the base tables were all there from an
    earlier run -- while silently missing chat_sessions, report_comments and
    the pgvector embedding column, which in turn broke report persistence at
    runtime. One bad migration must never be able to hide three good ones.
    """
    migration_dir = Path(__file__).resolve().parent / "migrations"
    migrations = sorted(
        path
        for path in migration_dir.glob("*.sql")
        if not path.name.endswith(".down.sql")
    )
    applied, failed = 0, []
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (724420221,))
        for migration in migrations:
            savepoint = f"mig_{migration.stem.split('_')[0]}"
            cur.execute(f'SAVEPOINT "{savepoint}"')
            try:
                cur.execute(migration.read_text(encoding="utf-8"))
            except Exception as exc:
                cur.execute(f'ROLLBACK TO SAVEPOINT "{savepoint}"')
                failed.append(migration.name)
                logger.error("Migration %s failed and was skipped: %s", migration.name, exc)
            else:
                cur.execute(f'RELEASE SAVEPOINT "{savepoint}"')
                applied += 1
        conn.commit()
    if failed:
        logger.warning(
            "Applied %s of %s Neon migration(s); skipped: %s",
            applied, len(migrations), ", ".join(failed),
        )
    else:
        logger.info("Applied %s Neon schema migration(s)", applied)



def record_analysed_company(
    *,
    report: dict[str, Any],
    report_id: Any | None = None,
    source_filename: str | None = None,
    source_sha256: str | None = None,
    owner_org_id: str | None = None,
) -> str | None:
    """Write one row to `analysed_companies` from a finished report.

    See migrations/009_analysed_companies.sql for why this table exists. In
    short: everything the product knows about a company lives inside a JSON blob
    today, which makes every cross-portfolio question ("which companies have
    under six months of runway", "which analyses ran while the provider was
    down") a full scan and a re-parse in Python.

    Best-effort by design. A failure to write the analytics row must never fail
    an analysis the user is waiting on -- the report itself is already persisted
    by `persist_report`, and this is a derived projection of it. Returns the new
    row id, or None if it could not be written.

    `owner_org_id` is accepted and stored but is None everywhere today, because
    no authentication exists. That is the honest state: the column means
    "pre-auth, globally visible" until accounts arrive.
    """
    sections = report.get("sections") or {}
    financial = sections.get("financial_state") or {}
    venture = sections.get("venture_score") or {}
    claims = sections.get("claims") or {}
    name = report.get("company") or report.get("company_name") or ""
    if not name:
        logger.warning("record_analysed_company called without a company name; skipping")
        return None

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    def _number(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO analysed_companies (
                    owner_org_id, company_name, company_slug, sector, report_id,
                    source_filename, source_sha256, deck_year, extracted_chars, text_layer,
                    final_score, model_only_score, evidence_penalty, recommendation, risk_level,
                    provider_degraded, incomplete_analysis, thin_evidence,
                    claims_checked, claims_supported, claims_refuted,
                    annual_revenue, monthly_burn, cash_on_hand, runway_months,
                    burn_multiple, largest_customer_share, growth_multiple,
                    financial_evidence, degraded_components, evidence_components
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s
                )
                RETURNING id::text AS id
                """,
                (
                    owner_org_id, name, slug, report.get("sector"), report_id,
                    source_filename, source_sha256, report.get("deck_year"),
                    report.get("extracted_chars"), report.get("text_layer"),
                    _number(report.get("final_score")),
                    _number(venture.get("model_only_score")),
                    _number(report.get("evidence_penalty")),
                    report.get("recommendation"), report.get("risk_level"),
                    bool(report.get("provider_degraded")),
                    bool(report.get("incomplete_analysis")),
                    bool(report.get("thin_evidence")),
                    int(claims.get("checked") or 0),
                    int(claims.get("supported") or 0),
                    int(claims.get("refuted") or 0),
                    _number(financial.get("annual_revenue")),
                    _number(financial.get("monthly_burn")),
                    _number(financial.get("cash_on_hand")),
                    _number(financial.get("runway_months")),
                    _number(financial.get("burn_multiple")),
                    _number(financial.get("largest_customer_share")),
                    _number(financial.get("growth_multiple")),
                    json.dumps(financial.get("evidence") or {}, default=str),
                    json.dumps(report.get("degraded_components") or [], default=str),
                    json.dumps(sections.get("evidence_components") or {}, default=str),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return row["id"] if row else None
    except Exception:
        logger.exception("Could not record analysed company %s", name)
        return None


def companies_with_short_runway(
    max_months: float = 6.0, owner_org_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """The portfolio question this table was added to make answerable.

    Excludes degraded and incomplete analyses on purpose: a runway figure from a
    run whose provider was down is not a finding about the company.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT company_name, runway_months, monthly_burn, cash_on_hand,
                   final_score, recommendation, analysed_at
            FROM analysed_companies
            WHERE runway_months IS NOT NULL
              AND runway_months <= %s
              AND provider_degraded = FALSE
              AND incomplete_analysis = FALSE
              AND (owner_org_id IS NOT DISTINCT FROM %s)
            ORDER BY runway_months ASC
            LIMIT %s
            """,
            (max_months, owner_org_id, limit),
        )
        return list(cur.fetchall())


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
    embedding: list[float] | None = None,
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
        summary = report.get("sections", {}).get("ai_analysis", "")
        verdict = report.get("recommendation", "NEEDS MORE DILIGENCE")
        raw = json.dumps(report, default=str)
        # SAVEPOINT, not conn.rollback(). The previous version called
        # conn.rollback() in the except branch, which undid the ENTIRE
        # transaction -- including the companies INSERT immediately above.
        # The retry below then inserted a dd_reports row pointing at a
        # company_id that no longer existed, so Postgres raised
        #
        #   ForeignKeyViolation: dd_reports_company_id_fkey
        #   Key (company_id)=(33) is not present in table "companies"
        #
        # and the API turned that into "Analysis completed but could not be
        # saved." Every report failed to persist on any database missing the
        # pgvector embedding column -- i.e. every database where migration 006
        # had not applied, which was all of them while ensure_schema() was
        # rolling migrations back (see the note there). A savepoint undoes only
        # the failed statement and leaves the company row intact.
        cur.execute("SAVEPOINT before_report_insert")
        try:
            cur.execute(
                """
                INSERT INTO dd_reports (company_id, summary, verdict, raw_output, embedding)
                VALUES (%s, %s, %s, %s::jsonb, %s)
                RETURNING id
                """,
                (company_id, summary, verdict, raw, embedding),
            )
            # Read the id BEFORE releasing the savepoint: RELEASE is itself a
            # statement and replaces the cursor's result set, so fetching after
            # it raises "the last operation didn't produce records".
            report_id = str(cur.fetchone()["id"])
            cur.execute("RELEASE SAVEPOINT before_report_insert")
        except Exception:
            # The embedding column/extension may not be present yet (migration
            # not applied), or `embedding` may be None -- persistence must
            # never fail because of the optional vector-retrieval feature.
            logger.warning("Storing report without embedding", exc_info=True)
            cur.execute("ROLLBACK TO SAVEPOINT before_report_insert")
            cur.execute(
                """
                INSERT INTO dd_reports (company_id, summary, verdict, raw_output)
                VALUES (%s, %s, %s, %s::jsonb)
                RETURNING id
                """,
                (company_id, summary, verdict, raw),
            )
            report_id = str(cur.fetchone()["id"])
        conn.commit()
        return report_id


def find_similar_reports_by_vector(embedding: list[float], top_k: int = 5) -> list[dict[str, Any]]:
    """Real vector retrieval over prior reports' embeddings (pgvector cosine
    distance), replacing the SQL LIKE keyword match in rag_engine.py's
    original build_context. Returns [] (never raises) if the embedding
    column/extension isn't available yet -- the caller falls back to keyword
    search in that case."""
    with connection() as conn, conn.cursor() as cur:
        # The ::vector casts are required, and their absence meant this
        # function had never once succeeded. A Python list parameter is adapted
        # by psycopg to double precision[], and pgvector defines no
        # `vector <=> double precision[]` operator, so every call raised:
        #
        #   psycopg.errors.UndefinedFunction: operator does not exist:
        #   vector <=> double precision[]
        #
        # rag_engine catches that and falls back to keyword search, logging at
        # INFO, so the failure was invisible in normal operation and the app
        # reported "vector retrieval" while doing LIKE matching every single
        # time. register_vector() on the connection is not sufficient on its
        # own here -- it teaches psycopg how to *read* vector columns, but the
        # bare parameter still adapts to an array without an explicit cast.
        cur.execute(
            """
            SELECT c.name, c.sector, dr.summary, dr.verdict, dr.created_at,
                   1 - (dr.embedding <=> %s::vector) AS similarity
            FROM dd_reports dr JOIN companies c ON c.id = dr.company_id
            WHERE dr.embedding IS NOT NULL
            ORDER BY dr.embedding <=> %s::vector
            LIMIT %s
            """,
            (embedding, embedding, top_k),
        )
        return list(cur.fetchall())


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



# How long a job may sit in 'running' before it is presumed dead. A real deck
# analysis measured 3-6 minutes end to end, so 25 minutes is far outside the
# normal envelope while still reclaiming quickly enough that a user is not left
# watching a spinner for an hour.
STALE_JOB_MINUTES = 25


def reclaim_orphaned_jobs(stale_minutes: int = STALE_JOB_MINUTES) -> list[dict[str, Any]]:
    """Fail jobs that can no longer be running, and return what was reclaimed.

    This closes the failure mode the async pipeline has always had and never
    handled. Analysis runs in a FastAPI BackgroundTask, which lives in the API
    process and nowhere else. When that process dies -- and on Render's free
    tier it dies routinely, from idle spin-down, deploys, and OOM kills -- every
    in-flight job dies with it, while its row sits in the database saying
    'running' forever. The frontend polls `/analyze/status/{id}`, sees 'running'
    on every poll, and shows a progress spinner that will never resolve.

    That is precisely the failure this codebase keeps finding in other guises:
    infrastructure died, and the product reported it as work in progress.

    Two distinct cases are reclaimed, and they are given different messages
    because they are different facts about what happened:

      - `running` past the stale window: the process almost certainly restarted
        mid-analysis. The user's deck was never analysed.
      - `pending` past the stale window: the job row was created but its
        BackgroundTask never started, so the crash happened between the INSERT
        and the task being scheduled.

    Called at startup (where it catches everything the previous process lost)
    and from the status endpoint (where it catches a job whose process died
    while this one stayed up, e.g. a worker thread killed by OOM).

    Deliberately NOT a retry. Re-running an analysis automatically would spend
    real Groq tokens on a request nobody is waiting for any more, and could loop
    forever if the deck itself is what crashes the pipeline. Reclaiming means
    telling the truth about the job, not attempting it again.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE analysis_jobs
               SET status = 'failed',
                   completed_at = now(),
                   error_message = CASE
                       WHEN status = 'running' THEN
                           'The analysis was interrupted before it finished -- the server '
                           'restarted while your deck was being processed. Nothing was saved. '
                           'Please upload it again.'
                       ELSE
                           'The analysis never started -- the server restarted before it was '
                           'picked up. Nothing was saved. Please upload it again.'
                   END
             WHERE status IN ('pending', 'running')
               AND COALESCE(started_at, created_at) < now() - make_interval(mins => %s)
            RETURNING id::text AS job_id, status, stage,
                      COALESCE(started_at, created_at) AS last_seen_at
            """,
            (stale_minutes,),
        )
        reclaimed = list(cur.fetchall())
        conn.commit()
    if reclaimed:
        logger.warning(
            "Reclaimed %s orphaned analysis job(s) older than %s minutes: %s",
            len(reclaimed), stale_minutes,
            ", ".join(r["job_id"] for r in reclaimed),
        )
    return reclaimed


def count_active_jobs() -> int:
    """Jobs currently pending or running. Used to shed load rather than accept
    work the process cannot finish -- see api.analyze_company."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM analysis_jobs "
            "WHERE status IN ('pending', 'running') "
            "AND COALESCE(started_at, created_at) > now() - make_interval(mins => %s)",
            (STALE_JOB_MINUTES,),
        )
        row = cur.fetchone()
        return int(row["n"]) if row else 0


def get_analysis_job(job_id: str) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id::text AS job_id, status, result, error_message, stage "
            "FROM analysis_jobs WHERE id::text = %s",
            (job_id,),
        )
        return cur.fetchone()


def set_analysis_job_stage(job_id: str, stage: str) -> None:
    """Record which pipeline step a running job is on, for real progress
    reporting. Best-effort by design: this is telemetry for a progress bar,
    and a failure to write it must never interfere with the analysis that is
    actually running."""
    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE analysis_jobs SET stage = %s WHERE id::text = %s",
                (stage, job_id),
            )
            conn.commit()
    except Exception:
        logger.debug("Could not record stage for job %s", job_id, exc_info=True)


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


def add_comment(report_id: str, author_name: str, body: str) -> dict[str, Any]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO report_comments (report_id, author_name, body)
            VALUES (%s, %s, %s)
            RETURNING id::text, author_name, body, created_at
            """,
            (report_id, author_name or "Anonymous", body),
        )
        row = cur.fetchone()
        conn.commit()
        return row


def list_comments(report_id: str) -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id::text, author_name, body, created_at
            FROM report_comments WHERE report_id = %s ORDER BY created_at ASC
            """,
            (report_id,),
        )
        return list(cur.fetchall())


def get_score_history(company_name: str, limit: int = 20) -> list[dict[str, Any]]:
    """Every persisted report's score/verdict/date for one company, oldest
    first -- the real data behind the "historical score tracking per
    company" ship-list item. Empty (not raised) if the company/DB isn't
    reachable, so a caller can treat that the same as "no history yet"."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT dr.created_at,
                   COALESCE((dr.raw_output ->> 'final_score')::float, 0) AS final_score,
                   COALESCE(dr.verdict, 'NEEDS MORE DILIGENCE') AS recommendation
            FROM dd_reports dr JOIN companies c ON c.id = dr.company_id
            WHERE lower(c.name) = lower(%s)
            ORDER BY dr.created_at ASC
            LIMIT %s
            """,
            (company_name, limit),
        )
        return list(cur.fetchall())


def stats() -> dict[str, int]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT (SELECT count(*) FROM companies) AS companies, (SELECT count(*) FROM dd_reports) AS dd_reports, (SELECT count(*) FROM portfolio_investments) AS portfolio_investments"
        )
        return dict(cur.fetchone())
