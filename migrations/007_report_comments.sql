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
