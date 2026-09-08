-- ============================================================================
-- VentureFlow — complete database setup
-- ============================================================================
--
-- Paste this whole file into the Neon SQL Editor and run it. It builds every
-- table, index, constraint and extension the platform needs, on an empty
-- database or an existing one.
--
-- IT IS SAFE TO RUN ON A DATABASE THAT ALREADY HAS DATA.
-- Every statement is idempotent: CREATE ... IF NOT EXISTS, ADD COLUMN IF NOT
-- EXISTS, and DO blocks that check before they alter. Nothing here drops a
-- table, deletes a row, or rewrites a column that already holds data. Running
-- it twice does nothing the second time.
--
-- YOU DO NOT NORMALLY NEED THIS FILE. The API applies these same migrations
-- itself on startup (`ensure_schema()` in db.py), which is how the current
-- database was built. This exists for the cases where that is inconvenient:
-- standing up a brand-new Neon project, reviewing exactly what the schema is,
-- or repairing a database whose migrations were interrupted.
--
-- WHY THE FILE LOOKS THE WAY IT DOES
--
-- Migration 002 repairs a legacy database whose `companies.id` and
-- `dd_reports.id` are integers rather than the UUIDs migration 001 declares.
-- That is the shape the live database is in, and it is fine -- migrations 005,
-- 007 and 009 resolve the type of their `report_id` column FROM `dd_reports.id`
-- at run time rather than hardcoding one, so they build correctly against
-- either. On a genuinely empty database you get UUID keys; on the existing one
-- the integer keys are kept and nothing is rewritten.
--
-- Generated from migrations/*.sql. If you change the schema, change the
-- migration and regenerate rather than editing this file, or the two will
-- drift apart.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 001_neon_due_diligence.sql
-- ----------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    domain TEXT,
    sector TEXT,
    description TEXT NOT NULL DEFAULT '',
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS companies_sector_idx ON companies (sector);
CREATE INDEX IF NOT EXISTS companies_name_trgm_idx ON companies USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS companies_domain_trgm_idx ON companies USING gin (domain gin_trgm_ops);

CREATE TABLE IF NOT EXISTS dd_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    summary TEXT NOT NULL DEFAULT '',
    verdict TEXT NOT NULL,
    raw_output JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS dd_reports_company_created_idx ON dd_reports (company_id, created_at DESC);

CREATE TABLE IF NOT EXISTS portfolio_investments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
    invested_at TIMESTAMPTZ,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS portfolio_investments_company_idx ON portfolio_investments (company_id);

-- ----------------------------------------------------------------------------
-- 002_repair_legacy_neon_schema.sql
-- ----------------------------------------------------------------------------

-- Repairs the legacy integer-key schema created before 001_neon_due_diligence.sql.
-- It intentionally supports both that schema and fresh UUID-based installs from 001.
-- This migration is transactional when executed by scripts/migrate_neon.py.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ;
UPDATE companies
SET first_seen_at = COALESCE(first_seen_at, now())
WHERE first_seen_at IS NULL;
ALTER TABLE companies
    ALTER COLUMN first_seen_at SET DEFAULT now();

-- A unique index is sufficient for INSERT ... ON CONFLICT (name) inference.
-- It is deliberately not created CONCURRENTLY because the migration runner wraps
-- all migrations in one transaction.
CREATE UNIQUE INDEX IF NOT EXISTS companies_name_unique_idx ON companies (name);
CREATE INDEX IF NOT EXISTS companies_sector_idx ON companies (sector);
CREATE INDEX IF NOT EXISTS companies_name_trgm_idx ON companies USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS companies_domain_trgm_idx ON companies USING gin (domain gin_trgm_ops);

ALTER TABLE dd_reports
    ADD COLUMN IF NOT EXISTS summary TEXT,
    ADD COLUMN IF NOT EXISTS verdict TEXT,
    ADD COLUMN IF NOT EXISTS raw_output JSONB;

-- Preserve legacy report content rather than attempting an unsafe text-to-JSON cast.
UPDATE dd_reports AS dr
SET summary = COALESCE(dr.summary, to_jsonb(dr) ->> 'report_content', '')
WHERE summary IS NULL;
UPDATE dd_reports AS dr
SET verdict = COALESCE(dr.verdict, to_jsonb(dr) ->> 'recommendation', 'NEEDS MORE DILIGENCE')
WHERE verdict IS NULL;
UPDATE dd_reports AS dr
SET raw_output = to_jsonb(dr)
WHERE raw_output IS NULL;

ALTER TABLE dd_reports
    ALTER COLUMN summary SET DEFAULT '',
    ALTER COLUMN verdict SET DEFAULT 'NEEDS MORE DILIGENCE';

-- A company can have many diligence runs.  The legacy one-report-per-company
-- constraint prevented the new persistence path from retaining history.
ALTER TABLE dd_reports
    DROP CONSTRAINT IF EXISTS dd_reports_company_id_unique;
CREATE INDEX IF NOT EXISTS dd_reports_company_created_idx
    ON dd_reports (company_id, created_at DESC);
CREATE INDEX IF NOT EXISTS portfolio_investments_company_idx
    ON portfolio_investments (company_id);

-- Down/rollback migration: migrations/002_repair_legacy_neon_schema.down.sql

-- ----------------------------------------------------------------------------
-- 003_analysis_jobs.sql
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS analysis_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'complete', 'failed')),
    request_payload JSONB NOT NULL,
    result JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS analysis_jobs_status_created_idx
    ON analysis_jobs (status, created_at DESC);

-- ----------------------------------------------------------------------------
-- 004_chat_sessions.sql
-- ----------------------------------------------------------------------------

-- Persists chatbot document/session state so an uploaded deck and its Q&A
-- history survive a server restart or redeploy instead of living only in the
-- in-process dict chatbot.py used before this migration.
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    company TEXT NOT NULL DEFAULT '',
    document_text TEXT NOT NULL DEFAULT '',
    history JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chat_sessions_updated_idx ON chat_sessions (updated_at DESC);

-- ----------------------------------------------------------------------------
-- 005_investment_decisions.sql
-- ----------------------------------------------------------------------------

-- Captures the user's own invest/pass decision on a completed report. This is
-- the feedback signal the firm-personalization ranking layer needs -- see
-- ml/personalization.py and ml/scripts/train_personalization_model.py.
--
-- report_id's type is resolved at run time from dd_reports.id rather than
-- hardcoded. The original version of this migration declared it UUID, which
-- matches the fresh schema in 001 but NOT the legacy integer-key schema that
-- 002_repair_legacy_neon_schema.sql explicitly exists to support. On a legacy
-- database this raised:
--
--   DatatypeMismatch: foreign key constraint
--   "investment_decisions_report_id_fkey" cannot be implemented
--   Key columns "report_id" and "id" are of incompatible types: uuid and integer
--
-- Because ensure_schema() applied every migration inside one transaction, that
-- single failure silently rolled back migrations 004, 006 and 007 as well --
-- which is why chat_sessions, the pgvector embedding column and report_comments
-- were all missing from a database that looked like it had migrated fine.
DO $migration$
DECLARE
    ref_type text;
BEGIN
    SELECT data_type INTO ref_type
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'dd_reports'
      AND column_name = 'id';

    IF ref_type IS NULL THEN
        RAISE EXCEPTION 'dd_reports.id not found -- run 001/002 first';
    END IF;

    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS investment_decisions ('
        '  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),'
        '  report_id %s NOT NULL REFERENCES dd_reports(id) ON DELETE CASCADE,'
        '  decision TEXT NOT NULL CHECK (decision IN (''invest'', ''pass'')),'
        '  notes TEXT NOT NULL DEFAULT '''','
        '  decided_at TIMESTAMPTZ NOT NULL DEFAULT now()'
        ')', ref_type);
END
$migration$;

CREATE UNIQUE INDEX IF NOT EXISTS investment_decisions_report_idx ON investment_decisions (report_id);

-- ----------------------------------------------------------------------------
-- 006_pgvector_retrieval.sql
-- ----------------------------------------------------------------------------

-- Enables real vector retrieval to replace the SQL LIKE "RAG" in
-- rag_engine.py (e1 on the Ship List). Embeddings are produced by
-- embeddings.py (TF-IDF+SVD -- see ml/scripts/train_text_embedder.py for
-- why not a pretrained sentence-transformer). No ANN index (ivfflat/hnsw)
-- is created here -- at single-user report volumes a sequential scan over
-- the <=> operator is both correct and fast; add one once report volume
-- actually justifies the build/maintenance cost.
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE dd_reports ADD COLUMN IF NOT EXISTS embedding vector(64);

-- ----------------------------------------------------------------------------
-- 007_report_comments.sql
-- ----------------------------------------------------------------------------

-- Team collaboration on a report (p3 on the Ship List). No auth exists yet
-- (Section 3, not started), so `author_name` is free text, not a verified
-- identity -- this is "shared commenting on one Neon database," honestly
-- short of real per-user team collaboration until accounts exist.
--
-- report_id's type is resolved from dd_reports.id at run time for the same
-- reason as 005_investment_decisions.sql: hardcoding UUID breaks on the legacy
-- integer-key schema that 002_repair_legacy_neon_schema.sql supports.
DO $migration$
DECLARE
    ref_type text;
BEGIN
    SELECT data_type INTO ref_type
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'dd_reports'
      AND column_name = 'id';

    IF ref_type IS NULL THEN
        RAISE EXCEPTION 'dd_reports.id not found -- run 001/002 first';
    END IF;

    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS report_comments ('
        '  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),'
        '  report_id %s NOT NULL REFERENCES dd_reports(id) ON DELETE CASCADE,'
        '  author_name TEXT NOT NULL DEFAULT ''Anonymous'','
        '  body TEXT NOT NULL,'
        '  created_at TIMESTAMPTZ NOT NULL DEFAULT now()'
        ')', ref_type);
END
$migration$;

CREATE INDEX IF NOT EXISTS report_comments_report_idx ON report_comments (report_id, created_at ASC);

-- ----------------------------------------------------------------------------
-- 008_analysis_job_stage.sql
-- ----------------------------------------------------------------------------

-- Real progress reporting for a running analysis.
--
-- The frontend's progress label used to advance on a fixed setTimeout ladder
-- (30s "Detecting risk signals", 60s "Retrieving database evidence", ...) that
-- had no connection to what the backend was doing. A genuinely slow-but-
-- working analysis therefore looked identical to a hung one, and a user
-- watching it sit at "Evaluating team profile" had no way to tell whether
-- anything was happening. That is the wrong failure mode for a job that
-- legitimately takes minutes.
--
-- `stage` carries the pipeline's actual current step, written as the job runs.
-- Nullable, because every job that predates this column has no stage and the
-- frontend must keep working for those.
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS stage TEXT;

-- ----------------------------------------------------------------------------
-- 009_analysed_companies.sql
-- ----------------------------------------------------------------------------

-- Analysed companies: a first-class record of every company the pipeline has
-- assessed, plus the financial state and evidence trail behind each assessment.
--
-- WHY THIS TABLE EXISTS
--
-- Everything the product knows about a company currently lives inside
-- `dd_reports.raw_output`, a JSON blob. That is fine for rendering one report
-- and useless for every question a VC actually asks across a portfolio: which
-- companies have under six months of runway, which decks had a claim refuted,
-- how a company's score moved between two decks, which analyses ran while the
-- LLM provider was down and therefore should not be trusted. Answering any of
-- those today means loading every report and re-parsing JSON in Python.
--
-- It also gives the score-distribution check (ml/scripts/check_score_distribution.py)
-- something to read directly. That check exists because 18 of 40 stored reports
-- once scored an identical 30.0, and a defect of that shape should be visible in
-- a query rather than requiring a script that reconstructs it.
--
-- TENANCY
--
-- This database has no user_id, org_id or tenant column anywhere, and every
-- report is globally readable -- `GET /reports` returns all of them to an
-- anonymous caller. Authentication is deliberately deferred, but a table added
-- now will still be here when it arrives, and retrofitting tenancy onto a
-- populated table means a backfill with no correct default.
--
-- So `owner_org_id` exists from the start and is NULLABLE, meaning
-- "pre-authentication, globally visible". When auth lands, the work is to
-- populate it and add a NOT NULL constraint plus row-level security -- not to
-- invent an owner for rows that never had one. Every index that will need to be
-- tenant-scoped already leads with the column, so the access paths do not have
-- to be rebuilt either.
--
-- The type is UUID rather than a foreign key because the organisations table
-- does not exist yet; adding the reference later is a cheap ALTER, whereas
-- guessing at a schema for a table nobody has designed is not.

DO $migration$
DECLARE
    ref_type text;
BEGIN
    -- Resolved at run time for the same reason as 005 and 007: hardcoding UUID
    -- breaks against the legacy integer-key schema that
    -- 002_repair_legacy_neon_schema.sql supports, and a DatatypeMismatch here
    -- would skip this migration on exactly the databases that already hold data.
    SELECT data_type INTO ref_type
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'dd_reports'
      AND column_name = 'id';

    IF ref_type IS NULL THEN
        RAISE EXCEPTION 'dd_reports.id not found -- run 001/002 first';
    END IF;

    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS analysed_companies ('
        '  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),'

        --  Tenancy, nullable until auth exists. See the note above.
        '  owner_org_id UUID NULL,'

        --  What was analysed.
        '  company_name TEXT NOT NULL,'
        '  company_slug TEXT NOT NULL,'
        '  sector TEXT NULL,'
        '  report_id %s NULL REFERENCES dd_reports(id) ON DELETE SET NULL,'

        --  Provenance of the input. `deck_year` is the deck vintage, and it is
        --  stored because claim verification is wrong without it: judging a
        --  2011 metric against present-day evidence produced four confidently
        --  wrong REFUTES verdicts on real decks.
        '  source_filename TEXT NULL,'
        '  source_sha256 TEXT NULL,'
        '  deck_year TEXT NULL,'
        '  extracted_chars INTEGER NULL,'
        --  "none" means the PDF had no text layer at all -- slide images. Six
        --  of thirteen well-known decks tested were exactly this, and the
        --  product could not read any of them.
        '  text_layer TEXT NULL,'

        --  The assessment.
        '  final_score NUMERIC(5,2) NULL,'
        '  model_only_score NUMERIC(5,2) NULL,'
        '  evidence_penalty NUMERIC(6,4) NULL,'
        '  recommendation TEXT NULL,'
        '  risk_level TEXT NULL,'

        --  Trustworthiness flags. These are the difference between "we assessed
        --  this company" and "our provider was down while we pretended to".
        --  They are columns rather than JSON keys precisely so that a query can
        --  exclude untrustworthy rows without parsing anything.
        '  provider_degraded BOOLEAN NOT NULL DEFAULT FALSE,'
        '  incomplete_analysis BOOLEAN NOT NULL DEFAULT FALSE,'
        '  thin_evidence BOOLEAN NOT NULL DEFAULT FALSE,'
        '  claims_checked INTEGER NOT NULL DEFAULT 0,'
        '  claims_supported INTEGER NOT NULL DEFAULT 0,'
        '  claims_refuted INTEGER NOT NULL DEFAULT 0,'

        --  Financial state, computed deterministically from the deck by
        --  agents/deck_financials. Broken out as columns because "show me every
        --  company under six months of runway" is the query a partner actually
        --  runs, and it must not require a JSON scan.
        '  annual_revenue NUMERIC(16,2) NULL,'
        '  monthly_burn NUMERIC(16,2) NULL,'
        '  cash_on_hand NUMERIC(16,2) NULL,'
        '  runway_months NUMERIC(7,2) NULL,'
        '  burn_multiple NUMERIC(9,2) NULL,'
        '  largest_customer_share NUMERIC(5,4) NULL,'
        '  growth_multiple NUMERIC(9,2) NULL,'

        --  Everything else, including the per-figure evidence spans, kept as
        --  JSONB so adding a derived metric does not require a migration.
        '  financial_evidence JSONB NOT NULL DEFAULT ''{}''::jsonb,'
        '  degraded_components JSONB NOT NULL DEFAULT ''[]''::jsonb,'
        '  evidence_components JSONB NOT NULL DEFAULT ''{}''::jsonb,'

        '  analysed_at TIMESTAMPTZ NOT NULL DEFAULT now(),'
        '  created_at TIMESTAMPTZ NOT NULL DEFAULT now()'
        ')', ref_type);
END
$migration$;

-- A company may legitimately be analysed many times -- that is the score-history
-- feature -- so the natural key is (tenant, company, when), not (tenant, company).
-- Leading with owner_org_id keeps this index usable once rows are tenant-scoped.
CREATE INDEX IF NOT EXISTS analysed_companies_org_slug_idx
    ON analysed_companies (owner_org_id, company_slug, analysed_at DESC);

CREATE INDEX IF NOT EXISTS analysed_companies_analysed_at_idx
    ON analysed_companies (analysed_at DESC);

-- The portfolio-screening query: short runway first, and only rows whose
-- analysis actually completed. Partial, because a scan over degraded rows is a
-- scan over results nobody should be screening on.
CREATE INDEX IF NOT EXISTS analysed_companies_runway_idx
    ON analysed_companies (owner_org_id, runway_months)
    WHERE runway_months IS NOT NULL
      AND provider_degraded = FALSE
      AND incomplete_analysis = FALSE;

-- Score distribution and ranking, same exclusion for the same reason.
CREATE INDEX IF NOT EXISTS analysed_companies_score_idx
    ON analysed_companies (owner_org_id, final_score DESC)
    WHERE final_score IS NOT NULL
      AND provider_degraded = FALSE
      AND incomplete_analysis = FALSE;

CREATE INDEX IF NOT EXISTS analysed_companies_report_idx
    ON analysed_companies (report_id);

-- ----------------------------------------------------------------------------
-- 010_users_and_sessions.sql
-- ----------------------------------------------------------------------------

-- Email/password accounts, and the sessions that authenticate them.
--
-- WHAT THIS REPLACES
--
-- Until now the deployed API had a single shared passphrase (DEMO_ACCESS_TOKEN).
-- That is a gate, not authentication: it establishes that a caller knows a
-- secret, never WHO they are, so every report has lived in one globally
-- readable pool. `GET /reports` returned every uploaded deck's analysis --
-- company names, scores, the full memo -- to anyone holding the passphrase.
-- For a product whose premise is confidential diligence on other people's
-- companies, that is the most severe defect in the system.
--
-- Migration 009 anticipated this and left `analysed_companies.owner_org_id`
-- nullable, documenting NULL as "pre-authentication, globally visible". This
-- migration is the other half of that plan.
--
-- WHY OPAQUE SESSION TOKENS RATHER THAN JWTs
--
-- A JWT cannot be revoked before it expires without keeping server-side state
-- anyway, which removes the only reason to prefer one. A row per session can be
-- deleted on logout, listed, and expired centrally. The cost is a database read
-- per request, which is already happening on every endpoint this protects.
--
-- Only the SHA-256 of the token is stored. A leaked database dump then yields
-- no usable session, in the same way that storing password hashes rather than
-- passwords does. The token itself exists only in the client.

CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Stored already lower-cased and trimmed by the application, so the UNIQUE
    -- constraint is the real one: "Ada@Example.com" and "ada@example.com" must
    -- not be two accounts. A CITEXT column would express this better but the
    -- extension is not guaranteed on a managed Postgres, and normalising in one
    -- place in the application is portable.
    email           TEXT NOT NULL UNIQUE,
    -- scrypt, encoded as "scrypt$n$r$p$<salt_b64>$<hash_b64>". Never a password.
    password_hash   TEXT NOT NULL,
    display_name    TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS user_sessions (
    -- SHA-256 of the bearer token, hex. The token is never stored.
    token_hash   TEXT PRIMARY KEY,
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Kept so a user can be shown where their account is signed in, and so an
    -- unexpected session is identifiable. Truncated by the application.
    user_agent   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS user_sessions_user_idx ON user_sessions (user_id);
CREATE INDEX IF NOT EXISTS user_sessions_expiry_idx ON user_sessions (expires_at);

-- Report ownership.
--
-- NULLABLE on purpose, and the meaning is the same one migration 009 gave
-- `owner_org_id`: NULL means the row predates authentication. Those rows are
-- not retro-assigned to whoever registers first, because inventing an owner for
-- a report that never had one is a worse answer than admitting it has none.
ALTER TABLE dd_reports ADD COLUMN IF NOT EXISTS owner_user_id UUID
    REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS dd_reports_owner_created_idx
    ON dd_reports (owner_user_id, created_at DESC);

-- ----------------------------------------------------------------------------
-- Verification: run this afterwards to confirm the result.
-- ----------------------------------------------------------------------------
--
-- Expect 10 rows. Anything missing means a statement above failed; scroll back
-- for the error rather than assuming it worked.

SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_type = 'BASE TABLE'
  AND table_name IN (
    'companies', 'dd_reports', 'portfolio_investments',
    'analysis_jobs', 'chat_sessions', 'investment_decisions',
    'report_comments', 'analysed_companies', 'users', 'user_sessions'
  )
ORDER BY table_name;
