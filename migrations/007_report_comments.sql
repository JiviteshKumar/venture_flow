-- Team collaboration on a report (p3 on the Ship List). No auth exists yet
-- (Section 3, not started), so `author_name` is free text, not a verified
-- identity -- this is "shared commenting on one Neon database," honestly
-- short of real per-user team collaboration until accounts exist.
CREATE TABLE IF NOT EXISTS report_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id UUID NOT NULL REFERENCES dd_reports(id) ON DELETE CASCADE,
    author_name TEXT NOT NULL DEFAULT 'Anonymous',
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS report_comments_report_idx ON report_comments (report_id, created_at ASC);
