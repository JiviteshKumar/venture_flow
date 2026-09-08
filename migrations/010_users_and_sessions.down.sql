-- Reverses 010_users_and_sessions.sql.
--
-- Dropping `users` would cascade-delete every session and NULL every report's
-- owner, which is the correct behaviour for a rollback and is destructive. The
-- reports themselves survive: ownership is a column on them, not their identity.
DROP INDEX IF EXISTS dd_reports_owner_created_idx;
ALTER TABLE dd_reports DROP COLUMN IF EXISTS owner_user_id;

DROP INDEX IF EXISTS user_sessions_expiry_idx;
DROP INDEX IF EXISTS user_sessions_user_idx;
DROP TABLE IF EXISTS user_sessions;
DROP TABLE IF EXISTS users;
