-- Reverses 012_activity_events.sql.
--
-- The indexes go with the table, so dropping it is the whole undo. Kept
-- explicit anyway, because a down migration that silently relies on a cascade
-- is one someone has to read the catalog to trust.

DROP INDEX IF EXISTS activity_events_session_idx;
DROP INDEX IF EXISTS activity_events_job_idx;
DROP INDEX IF EXISTS activity_events_user_idx;
DROP INDEX IF EXISTS activity_events_occurred_idx;
DROP TABLE IF EXISTS activity_events;
