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
