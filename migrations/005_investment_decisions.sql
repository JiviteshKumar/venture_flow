-- Captures the user's own invest/pass decision on a completed report. This is
-- the feedback signal the firm-personalization ranking layer needs -- see
-- ml/personalization.py and ml/scripts/train_personalization_model.py.
CREATE TABLE IF NOT EXISTS investment_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id UUID NOT NULL REFERENCES dd_reports(id) ON DELETE CASCADE,
    decision TEXT NOT NULL CHECK (decision IN ('invest', 'pass')),
    notes TEXT NOT NULL DEFAULT '',
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS investment_decisions_report_idx ON investment_decisions (report_id);
