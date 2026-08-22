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
