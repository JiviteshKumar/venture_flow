-- Reverses 011_claim_verdict_cache.sql. Losing the cache loses nothing but
-- speed and determinism: every claim is simply checked afresh.
DROP INDEX IF EXISTS claim_verdict_cache_created_idx;
DROP TABLE IF EXISTS claim_verdict_cache;
