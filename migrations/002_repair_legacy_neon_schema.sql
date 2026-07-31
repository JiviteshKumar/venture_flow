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
