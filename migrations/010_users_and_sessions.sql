-- Email/password accounts, and the sessions that authenticate them.
--
-- WHAT THIS REPLACES
--
-- Until now the deployed API had a single shared passphrase (DEMO_ACCESS_TOKEN).
-- That is a gate, not authentication: it establishes that a caller knows a
-- secret, never WHO they are, so every report has lived in one globally
-- readable pool. `GET /reports` returned every uploaded deck's analysis --
-- company names, scores, the full memo -- to anyone holding the passphrase.
-- For a product whose premise is confidential diligence on other people's
-- companies, that is the most severe defect in the system.
--
-- Migration 009 anticipated this and left `analysed_companies.owner_org_id`
-- nullable, documenting NULL as "pre-authentication, globally visible". This
-- migration is the other half of that plan.
--
-- WHY OPAQUE SESSION TOKENS RATHER THAN JWTs
--
-- A JWT cannot be revoked before it expires without keeping server-side state
-- anyway, which removes the only reason to prefer one. A row per session can be
-- deleted on logout, listed, and expired centrally. The cost is a database read
-- per request, which is already happening on every endpoint this protects.
--
-- Only the SHA-256 of the token is stored. A leaked database dump then yields
-- no usable session, in the same way that storing password hashes rather than
-- passwords does. The token itself exists only in the client.

CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Stored already lower-cased and trimmed by the application, so the UNIQUE
    -- constraint is the real one: "Ada@Example.com" and "ada@example.com" must
    -- not be two accounts. A CITEXT column would express this better but the
    -- extension is not guaranteed on a managed Postgres, and normalising in one
    -- place in the application is portable.
    email           TEXT NOT NULL UNIQUE,
    -- scrypt, encoded as "scrypt$n$r$p$<salt_b64>$<hash_b64>". Never a password.
    password_hash   TEXT NOT NULL,
    display_name    TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS user_sessions (
    -- SHA-256 of the bearer token, hex. The token is never stored.
    token_hash   TEXT PRIMARY KEY,
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Kept so a user can be shown where their account is signed in, and so an
    -- unexpected session is identifiable. Truncated by the application.
    user_agent   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS user_sessions_user_idx ON user_sessions (user_id);
CREATE INDEX IF NOT EXISTS user_sessions_expiry_idx ON user_sessions (expires_at);

-- Report ownership.
--
-- NULLABLE on purpose, and the meaning is the same one migration 009 gave
-- `owner_org_id`: NULL means the row predates authentication. Those rows are
-- not retro-assigned to whoever registers first, because inventing an owner for
-- a report that never had one is a worse answer than admitting it has none.
ALTER TABLE dd_reports ADD COLUMN IF NOT EXISTS owner_user_id UUID
    REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS dd_reports_owner_created_idx
    ON dd_reports (owner_user_id, created_at DESC);
