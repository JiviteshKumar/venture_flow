-- Everything that happens during a session, kept.
--
-- WHAT THIS RECORDS AND WHY IT DID NOT EXIST
--
-- The pipeline already reports its own work: every web search it issues and
-- every page it opens is recorded at the moment it happens, with the URL, by
-- `live_activity.record`. That feed is in-process and bounded -- eighty
-- entries per job, four jobs -- so it exists to drive the progress display and
-- then it is gone. Restart the service and the record of what the product
-- actually looked at is lost.
--
-- That is the wrong place for it to live. Which sources a run opened is not
-- decoration: it is the evidence trail behind a report that claims to show its
-- working, and the first thing anyone asks when a verdict looks wrong is what
-- the run actually read. This table keeps it.
--
-- It also keeps what the person did: signing in, uploading a deck, opening a
-- report, exporting one. One table rather than two, because the question that
-- gets asked is "what happened in this session", and that question does not
-- care whether a given step was taken by a human or by the pipeline on their
-- behalf.
--
-- WHAT IT DELIBERATELY DOES NOT RECORD
--
-- No passwords, in any form. `users.password_hash` holds an scrypt hash and
-- nothing else should ever hold more; a log line is not a place a credential
-- can be made safe.
--
-- No request bodies and no deck text. The deck is already stored, once, where
-- it belongs. Copying its contents into an event stream would scatter the
-- thing most worth protecting across a table nobody thinks of as sensitive.
--
-- RETENTION
--
-- Ninety days, enforced by `db.purge_expired_activity`. The column is indexed
-- for exactly that sweep. Deleting a user takes their events with them, which
-- is why `user_id` cascades rather than nulling: an account erased should not
-- leave a readable trail of what it did.

CREATE TABLE IF NOT EXISTS activity_events (
    id            BIGSERIAL PRIMARY KEY,
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Who. NULL before sign-in and for pipeline work on an unowned report.
    user_id       UUID REFERENCES users(id) ON DELETE CASCADE,

    -- Which session. Deliberately NOT a foreign key: sessions expire and are
    -- swept, and an audit trail that erases itself when a cookie lapses is not
    -- an audit trail. It is the same SHA-256 hex that keys `user_sessions`,
    -- so the two can still be joined while the session exists.
    session_token_hash TEXT,

    -- Which analysis run, when the event came from one. Matches the contextvar
    -- in `observability.current_job_id`, so events, logs and the live feed all
    -- name a run the same way.
    job_id        TEXT,

    -- A short machine token the UI and queries group on: 'search', 'fetch',
    -- 'signin', 'signout', 'register', 'upload', 'analyse', 'report_open',
    -- 'export'. Kept open rather than an enum so adding one is a code change
    -- and not a migration.
    kind          TEXT NOT NULL,

    -- Human-readable: the query that was searched, the file that was uploaded.
    detail        TEXT NOT NULL DEFAULT '',

    -- The page opened, for 'search' and 'fetch'. Empty for the rest.
    url           TEXT NOT NULL DEFAULT '',

    -- Whether the step succeeded, where that is meaningful. NULL where it is
    -- not: "we did not record this" and "this failed" are different findings
    -- and a boolean default would collapse them.
    ok            BOOLEAN,

    -- Anything structured a specific kind wants to add, without a migration.
    meta          JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- The retention sweep reads this and nothing else.
CREATE INDEX IF NOT EXISTS activity_events_occurred_idx
    ON activity_events (occurred_at);

-- "What did this person do", newest first.
CREATE INDEX IF NOT EXISTS activity_events_user_idx
    ON activity_events (user_id, occurred_at DESC);

-- "What did this run look at", in order.
CREATE INDEX IF NOT EXISTS activity_events_job_idx
    ON activity_events (job_id, occurred_at);

-- "What did this session do", newest first.
CREATE INDEX IF NOT EXISTS activity_events_session_idx
    ON activity_events (session_token_hash, occurred_at DESC);
