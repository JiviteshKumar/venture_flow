# Quarantined: Supabase ingestion pipeline

Moved here on 22 Aug 2026, per the "decide the fate of the orphaned Supabase
pipeline" ship-list item. This is not deleted, and it is not wired into the
live app -- it's parked, with the reasoning below, so nobody mistakes it for
dead weight or for something currently running.

## What this is

Ten dataset-specific ingestion scripts (`ingest_10k.py`, `ingest_benetech.py`,
`ingest_chartqa.py`, `ingest_docvqa.py`, `ingest_ectsum.py`,
`ingest_kleister.py`, `ingest_maud.py`, `ingest_phrasebank.py`,
`ingest_scifact.py`, `ingest_tatqa.py`, `ingest_tfns.py`) plus their shared
plumbing (`base.py` -- the Supabase client, `model_singleton.py` -- a
sentence-transformer embedding singleton, `generate_embeddings.py`,
`download_docvqa.py`, `check_folders.py`, `final_check.py`,
`financial_reasoner.py`, `visual_extractor.py`), and three manual smoke-test
scripts that exercised the live Supabase connection directly
(`test_connection.py`, `test_storage.py`, `test_full_pipeline.py`).

Together they represent real, working ingestion of ten financial-NLP
datasets (10-K filings, chart QA, document QA, earnings summaries, contract
review, financial sentiment, scientific fact-checking, and more) into a
Supabase project: chunking, embedding, and storage.

## Why it's quarantined, not wired in or deleted

- **It targets a schema the live app doesn't have.** The current app persists
  to Neon Postgres (`db.py`, `migrations/`) with a `companies` /
  `dd_reports` / `portfolio_investments` schema. This pipeline expects
  Supabase tables (`ingestion_log`, `charts-raw` storage buckets, etc.) that
  were never created in Neon and aren't part of the current schema.
- **It's not free.** Supabase is a separate paid-tier-eligible service, and
  the project's current stance (see FIELD_NOTES.md) is free/low-cost data
  sources only, no new paid subscriptions, until there's revenue to justify
  it.
- **Deleting it would throw away real, reusable work.** Ten datasets' worth
  of ingestion logic is exactly the kind of evidence base the "real vector
  retrieval (pgvector)" and "founder/team verification agent" ship-list items
  will eventually want. Rewriting it from scratch later would be wasted
  effort.

## How to revive it, if/when it's worth doing

**Decided (22 Aug 2026): nothing stays on Supabase. Everything goes to Neon.**
That closes the open question this README originally posed -- there is no
"stay on Supabase" branch to consider. If this pipeline is revived, it is
ported to Neon, full stop.

1. Replace `base.py`'s Supabase client with a `psycopg` connection (same
   pattern as `db.py`), and add a migration for whatever tables the
   ingestion scripts need (chunks + embeddings, most likely a `pgvector`
   column).
2. `model_singleton.py`'s sentence-transformer embedding model needs
   `huggingface.co` access to download on first run -- confirmed blocked in
   this session's build sandbox (see `ml/README.md`'s network-constraints
   section), so run the first download somewhere with normal internet access,
   same as the still-untrained Claim/Risk models.
3. Move the revived scripts back out of `legacy/` and wire their output into
   `rag_engine.py`'s `build_context()`, which is what `chatbot.py` and
   `ventureflow_agent.py` actually call for retrieval today.

Nothing in this folder is imported by the live app. `pytest tests/` does not
touch it either.
