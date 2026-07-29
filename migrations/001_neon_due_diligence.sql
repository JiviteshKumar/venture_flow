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