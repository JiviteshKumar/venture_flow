-- Cached claim verdicts, so the same claim checked twice gets the same answer.
--
-- WHY
--
-- Verdicts on the same deck differed between runs. Notion's funding claim was
-- REFUTES in one benchmark run and NOT_ENOUGH_INFO in the next; "Lyft operates
-- in more countries than Uber" had the refuting fact in its evidence on one run
-- and not on the next. The cause is not the judge but retrieval: the web
-- returns a different set of pages each time, and a different set of pages can
-- support a different verdict. Two analyses of one unchanged deck an hour apart
-- could therefore disagree about the same sentence, which no reader should have
-- to reconcile.
--
-- A verdict is cached against the exact claim, company, deck vintage and search
-- mode, for a bounded period (agents/claim_cache.py, 7 days by default). A
-- re-run inside that window returns the stored verdict and says it did. It also
-- spends no Groq tokens, which on a 200,000-token daily budget is not a small
-- side effect.
--
-- Degraded verdicts are never stored -- one produced during an outage, or from
-- a thin evidence base while the general web index was rate-limited. Freezing a
-- weak answer for a week would be worse than having no cache at all.
CREATE TABLE IF NOT EXISTS claim_verdict_cache (
    key         TEXT PRIMARY KEY,
    claim       TEXT NOT NULL,
    company     TEXT NOT NULL DEFAULT '',
    result      JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS claim_verdict_cache_created_idx
    ON claim_verdict_cache (created_at);
