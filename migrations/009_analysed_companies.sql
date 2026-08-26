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
