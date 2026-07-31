-- Roll back only objects introduced by 002.  Existing legacy data is preserved.
DROP INDEX IF EXISTS portfolio_investments_company_idx;
DROP INDEX IF EXISTS dd_reports_company_created_idx;
DROP INDEX IF EXISTS companies_domain_trgm_idx;
DROP INDEX IF EXISTS companies_name_trgm_idx;
DROP INDEX IF EXISTS companies_sector_idx;
DROP INDEX IF EXISTS companies_name_unique_idx;

ALTER TABLE dd_reports
    DROP COLUMN IF EXISTS raw_output,
    DROP COLUMN IF EXISTS verdict;
ALTER TABLE companies
    DROP COLUMN IF EXISTS first_seen_at;
