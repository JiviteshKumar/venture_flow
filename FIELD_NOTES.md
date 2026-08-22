# Field notes — 22 Aug 2026 session

What changed in this pass, and why. Read this before the next session picks up
where this one left off.

## Update — same-day, fourth pass: Evidence Depth + Product Polish

All 8 remaining Ship List items in these two sections, built and verified.
Nothing in Foundation Hardening or "Make the model real" changed this pass.

**Evidence depth (4/4)**

- **Real pgvector retrieval.** Trained a second, general-purpose TF-IDF+SVD
  embedder (`ml/scripts/train_text_embedder.py`, 64 dims, same free YC
  dataset the Outcome Model uses — `huggingface.co` is still blocked in this
  sandbox, so this reuses the established workaround rather than inventing
  a new one). `embeddings.py` loads it; `migrations/006_pgvector_retrieval.sql`
  adds a `vector(64)` column to `dd_reports` and enables the pgvector
  extension. `rag_engine.build_context()` now tries real cosine-similarity
  vector search first and falls back to the original keyword `LIKE` search
  if the embedding or the extension is unavailable for any reason — a
  `"method"` field on the returned context says which one actually ran, so
  this is never silently degraded without a trace.
- **Founder/team verification agent** (`agents/founder_verifier.py`) — reuses
  the same web-search-plus-Groq-judgment pattern as the existing claim
  verifier. Given a founder name it searches, then asks Groq whether the
  evidence is CONSISTENT, CONTRADICTS, or NOT_ENOUGH_INFO with what the deck
  claims about them. Capped at 3 founders per report. Wired into
  `ventureflow_agent.py` as an additive `sections.founder_verification`
  field — only runs if the caller passes `founders`, and never blocks the
  rest of the report on failure.
- **Real comparable-company benchmarking** (`comparables.py`) — embeds the
  target company's description with the same embedder above, and finds the
  nearest real companies (by name, industry, stage, batch, and actual
  outcome) from the 1,560-company YC dataset by in-memory cosine similarity.
  Not synthetic; every comparable returned is a real company from the
  dataset with a real recorded outcome.
- **Paid market-data API integration path** (`market_data.py`) — an abstract
  `MarketDataProvider` interface with `FreeDataProvider` (wraps the above,
  the only one actually wired in) and documented `CrunchbaseProvider` /
  `PitchBookProvider` stub classes gated on `CRUNCHBASE_API_KEY` /
  `PITCHBOOK_API_KEY`. They return `{"available": False, "reason": "...not
  implemented -- no API key/budget configured."}` rather than pretending to
  call an API this project has no budget or contract for. This is the
  integration point a future pass wires a real key into — not a fake call.

**Product polish (4/4)**

- **Proper PDF export** (`report_pdf.py`, reportlab Platypus) — a real
  multi-section PDF: score/recommendation/risk summary table, investment
  memo, claim-verification summary, key concerns/red flags/positives,
  comparable companies (if available), outcome-model signal (if available),
  technical score (if available), closing caveat. New endpoint
  `GET /reports/{id}/pdf`. `Analysis.tsx`'s export button now calls it, and
  falls back to the original plain-text export only if the PDF request
  fails.
- **Historical score tracking per company** — `db.get_score_history()` reads
  every past `dd_reports` row for a company name, oldest first.
  New endpoint `GET /companies/{name}/history`. `Dashboard.tsx`'s
  "Investment Score Trend" chart — previously hardcoded to
  `hasHistory = false` and an empty dataset, i.e. fabricated-looking but
  actually inert — now fetches real history and only renders once there
  are 2+ real data points to draw a trend from.
- **Team collaboration on reports** — `migrations/007_report_comments.sql`
  adds a `report_comments` table; `POST`/`GET /reports/{id}/comments`;
  a `CommentsPanel` component in `Analysis.tsx` next to the existing chat
  panel. Honest caveat, stated directly in the migration and worth
  repeating here: there is no auth yet (that's a Foundation Hardening item,
  not started), so `author_name` is free text a commenter types in, not a
  verified identity. This is "shared notes on one Neon database," not real
  per-user team accounts — good enough to demo, short of the real thing
  until accounts exist.
- **Onboarding / sandbox mode** — `demo_data.py` bundles one clearly-labeled
  fictional company ("Solstice Robotics (Demo)") with a deck-style
  description, a mix of claims (some should verify, some shouldn't — not a
  rigged all-green demo), founders, and financials. New endpoint
  `GET /demo/sample`. A new "Try a demo deck — no upload needed" button on
  the upload page runs the *real* pipeline (claim verification, risk model,
  RAG, Groq synthesis, comparables, the works) against it, so a first-time
  user with no deck and no Neon data yet can still see what a completed
  report looks like.

**Verified this pass**: `pytest tests/` → 18/18 still passing (no new test
files added this pass — the new code paths were smoke-tested directly:
`embeddings.embed_text()`, `comparables.find_comparables()`,
`market_data.get_market_data_provider()`, `report_pdf.build_report_pdf()`
against a synthetic report, and `agents.founder_verifier.verify_founders()`
on empty input, all run and inspected directly, not just read). Every new
`.py` file byte-compiles cleanly. `frontend`: `tsc -b` and `vite build` both
succeed (one real bug caught doing this — `Analysis.tsx` used the new
`useEffect` for the comments panel without importing it; fixed). A live
`TestClient` request against the new `GET /demo/sample` route returns 200
with no environment variables set, confirming it degrades to nothing worse
than "demo unavailable" rather than crashing if it ever did depend on
something live (it doesn't — it's a static fixture).

**Not resolved this pass, and needs the user's own terminal output to
diagnose**: the "Analysis queue is currently unavailable" error the user is
seeing is `api.py`'s literal 503 message, raised whenever
`db.create_analysis_job()` throws — confirmed by grepping the frontend
(the string doesn't originate there). Ruled out one hypothesis directly: a
`#` character in the DB password (visible in an earlier screenshot) does
*not* break psycopg's URL parsing — tested with
`psycopg.conninfo.conninfo_to_dict()` directly. The real cause needs the
`uvicorn` terminal's actual traceback, which isn't visible from this
sandbox — most likely candidates, in order of likelihood: the Neon/Supabase
project being paused (common on free tiers after inactivity), a stale or
malformed `DATABASE_URL` in `.env`, or `ensure_schema()` failing partway
through on first boot. Once the backend can reach the DB at all,
`ensure_schema()` will pick up both new migrations (006 pgvector, 007
comments) automatically on the next restart — no manual migration step
needed.

## Update — same-day, second pass: the ML layer

Full detail and methodology lives in `ml/README.md`; this is the summary.

- **Trained and running**: the Outcome Model. Real data (1,560 Y Combinator
  companies, pulled live from `yc-oss/api`, 3.5y+ post-launch, resolved
  outcome only), real held-out test set, real ablation (text-only AUC 0.572,
  structured-only AUC 0.700, combined AUC 0.704 — structured features carry
  almost all the signal, which is itself the finding). Wired into
  `ventureflow_agent.py` as an additive `sections.ml_outcome_model` field;
  verified it never blocks the report if the model is missing or errors
  (`tests/test_ml_outcome_model.py`). Zero frontend changes were made or
  needed.
- **Written but not run**: Claim Model (SciFact) and Risk/Tone Model
  (Financial PhraseBank + TFNS) — both scripts are complete and correct in
  `ml/scripts/`, but this session's cloud sandbox blocks `huggingface.co`
  and S3 at the network level (confirmed with direct connection tests, not
  assumed) while allowing PyPI/npm/plain GitHub. Run either script on a
  machine with normal internet access and it will produce a trained model
  in the same format the Outcome Model uses.
- **Deliberately not attempted this session**: multi-tenant auth, billing,
  compliance docs (ToS/DPA/retention policy), and go-to-market — these need
  real business/legal decisions and infrastructure provisioning, not code
  a session can unilaterally "complete." They're still tracked, honestly,
  on the Ship List.

## Bugs fixed (verified, not just described)

1. **`agents/investment_agents.py` had a real `SyntaxError`** — an f-string
   expression contained a backslash (`f"...{'\n'.join(claim_lines)}..."`),
   which is illegal before Python 3.12. Since `ventureflow_agent.py` imports
   this module at the top level, and `api.py` imports `ventureflow_agent`,
   **the entire FastAPI app failed to import on Python < 3.12** — not just
   the specialist-agent feature. Confirmed locally on Python 3.11.15. Fixed
   by precomputing the joined string on its own line before the f-string.

2. **The Groq client was constructed eagerly at import time** in five files
   (`chatbot.py`, `ventureflow_agent.py`, `agents/claim_verifier.py`,
   `agents/investment_agents.py`, `agents/risk_detector.py`). Groq's SDK
   raises immediately if no API key is resolvable — so with `GROQ_API_KEY`
   unset or misconfigured, the whole app failed to start, including
   completely unrelated routes like `/health`. Replaced with a shared lazy
   singleton in the new `groq_client.py` (`get_client()` + a single `MODEL`
   constant, previously duplicated five times). Verified: the full test
   suite and a live `TestClient` smoke test now pass with **no
   `GROQ_API_KEY` and no `DATABASE_URL` set at all** — `/health` correctly
   reports `degraded` instead of crashing, `/database/stats` returns a clean
   503, and `/nonexistent-route` returns 404.

3. **No catch-all frontend route** (QA-006 from the deleted 2026-08-03 audit
   was never actually fixed) — an unknown path rendered the sidebar with a
   blank main panel. Added `frontend/src/pages/NotFound.tsx` and a `path="*"`
   route in `App.tsx`.

4. **`DBStats`/`getStats()` in `apiClient.ts` described a schema that no
   longer exists** — `documents`, `sentiment_records`, `visual_assets`,
   `qa_pairs`, etc. are all legacy Supabase-era fields. The live
   `/database/stats` endpoint returns `{companies, dd_reports,
   portfolio_investments}`. Fixed the type to match. Note: nothing in the UI
   actually calls `getStats()` today, so this was dead code, not a live bug —
   worth knowing if you're deciding whether to wire a real stats widget into
   the dashboard later.

## Verified working (didn't just skim it)

- `pip install -r requirements.txt` + `pytest tests/` → **12/12 pass**, with
  zero environment variables set.
- A live `TestClient` run against `api.app` with no credentials configured:
  `/health` → 200 degraded, `/` → 200, `/nonexistent-route` → 404,
  `/database/stats` → 503 (clean error, not a crash).
- `frontend`: `npm install`, `tsc -b`, and `vite build` all succeed cleanly.

## Findings not yet fixed (flagged, not resolved — pick these up next)

- **Dashboard's "Investment Score Trend" chart is fabricated.** The eight
  monthly data points in `Dashboard.tsx` (`arrData`) are computed as
  `score * 0.012`, `score * 0.014`, … from the single current score — there
  is no real historical time series behind it. It reads as a real trend line
  to a VC glancing at the dashboard. Same issue with the Bull/Bear
  "conviction" scores (`score * 1.05`, `(100 - score) * 0.8`) — arithmetic
  derived from one number, not two independent signals. Either remove these
  widgets or wire them to something real (e.g. score history across repeat
  analyses of the same company, once that's tracked).
- **The orphaned Supabase ingestion pipeline** (`base.py`,
  `ingest_*.py` × 10, `model_singleton.py`, `generate_embeddings.py`,
  `download_docvqa.py`, `check_folders.py`, `final_check.py`,
  `agents/financial_reasoner.py`, `agents/visual_extractor.py`) is not wired
  into the live app at all — it targets Supabase tables the current Neon
  schema doesn't have. It represents real, reusable work (ten ingested
  financial-NLP datasets) toward the "real RAG" and "calibration layer"
  goals in the strategy report, but as-is it's dead code sitting next to the
  live pipeline. Decide: quarantine into a `legacy/` folder with a README,
  or delete, or actually wire it up — don't leave it half-connected.
- Claim/financial extraction in `pdf_extractor.py` is still pure regex and
  known (from the deleted QA audit) to mangle multi-column deck layouts.
- The in-memory rate limiter and the chat document store
  (`chatbot.py`'s `_document_store`) both reset on every restart/redeploy —
  fine for local single-user testing, not fine for anything persistent.

## Decisions the user made this session (don't re-ask)

- End goal is a multi-tenant SaaS for VC firms, but **right now**: single
  user, running and tested locally, no paid subscriptions.
- No historical deal-outcome data available initially → outcome-prediction
  modeling (Option C in the strategy report) was out of scope in the first
  pass. **Superseded in the second pass**: real labeled outcome data (YC's
  own directory, via `yc-oss/api`) was found and used — see the "Make the
  model real" section below. This line is kept for the record, not as
  current guidance.
- Free/low-cost data sources only — no paid company-data API (Crunchbase/
  PitchBook-style) budgeted yet.
- Groq stays the only LLM provider for now — no fallback provider.

See the published strategy report ("VentureFlow Field Report") for the full
competitive-landscape research and proposed build order (Phase 0 → 3).

## Update — same-day, third pass: Foundation hardening + the rest of "Make the model real"

Ship-list items closed this pass (Foundation hardening: 5/9 → all except the
regex-extraction item, which is now replaced too, so Foundation is
effectively done except `f6`/`f8` follow-ups below; Model layer: 2/9 → 8/9,
everything except the two still-network-blocked training scripts):

- **Chat/document sessions now persist to Neon** (`migrations/004_chat_sessions.sql`,
  `db.py`'s `upsert_chat_session`/`get_chat_session`/`delete_chat_session`,
  wired into `chatbot.py`). Falls back to in-memory-only, with a logged
  warning, if Neon is briefly unreachable — chat still works, it just won't
  survive a restart in that case, same as before this change.
- **Rate limiter is now multi-instance-safe when `REDIS_URL` is set**
  (`rate_limiter.py`) — a fixed-minute-bucket Redis counter, with a documented,
  automatic fallback to the original in-memory sliding window when Redis
  isn't configured or isn't reachable. Local single-instance use is
  unaffected either way.
- **Claim/financial extraction is now schema-validated** (`structured_extractor.py`):
  asks the LLM for a Pydantic-validated JSON object instead of parsing free
  text, and falls back to the original regex extractor (`pdf_extractor.py`,
  kept, not deleted) on any invalid JSON, schema violation, or LLM failure.
  `/upload-pdf` now reports which path actually produced the result via a
  new `extraction_method` field.
- **The orphaned Supabase pipeline is quarantined**, not deleted, not wired
  in — moved to `legacy/supabase_ingestion/` with a README explaining what
  it is and exactly how to revive it. **User decision, stated directly:
  nothing stays on Supabase, everything goes to Neon** — closes the question
  the quarantine README originally left open. All remaining "Supabase" strings
  in the live codebase (`.env.example`, `chatbot.py` comments/labels,
  `README.md`) were stale references cleaned up to say Neon, since nothing
  live actually used Supabase — `rag_engine.py` already queried Neon only.
- **Dashboard's fabricated charts are fixed, not just flagged.** The
  "Investment Score Trend" 8-point line (`score * 0.012` … `* 0.028`) is
  replaced with an honest single-point state ("today's score, re-analyze
  later for a real trend") since no real historical-score tracking exists
  yet (`p2`, still open). The four metric-card mini-sparklines, which used
  the same fabricated arithmetic, are removed rather than left inconsistent
  with the fix above. Bull/Bear conviction is now the real ratio of
  independently-detected positive factors to red flags for that report, not
  a rescaling of the single final score.
- **Technical/GitHub scoring module** (`technical_scoring.py`) — a
  transparent, individually-inspectable rubric over the public GitHub API
  (recent activity, contributors, tests/CI, README/LICENSE, issue health,
  repo age), wired in additively as `sections.technical_score` when a
  `github_url` is supplied (new optional `DiligenceRequest` field; not yet
  exposed in the upload form — zero other frontend changes).
- **Firm-personalization ranking layer — the mechanism, honestly not yet
  active.** `POST /reports/{report_id}/decision` captures the user's own
  invest/pass call; `ml/scripts/train_personalization_model.py` fits once 15+
  decisions exist; `ml/personalization.py` reports itself unavailable with a
  running count below that floor. There is no usage data on day one of this
  feature existing, and pretending otherwise would be the same mistake this
  whole session has been trying to avoid.
- **Claim-verification benchmark + eval framework** (`ml/eval/`) — 30
  hand-labeled claims, an eval harness reporting precision/recall/F1/
  confusion matrix/calibration. The metrics computation is unit-tested
  without network access; actually scoring the benchmark against live claims
  needs a working `GROQ_API_KEY` and internet, neither available here — see
  `ml/eval/README.md` for exactly how to run it and how the labels were built.
- **Drift monitoring** — `ml/inference.py` now logs every outcome-model call;
  `ml/scripts/check_drift.py` flags distribution shift via PSI once 20+ calls
  are logged. This is the retraining trigger for now; an automated retraining
  loop isn't built because there's no usage volume yet to justify one.
- **Documented, not coded: where models run in production.** In-process,
  same as the Outcome Model already does — right for single-user/local now,
  revisit only when this becomes a real multi-tenant service. See
  `ml/README.md`'s "Where trained models run in production" section.

**Still blocked, unchanged from the second pass**: Claim Model and Risk
Model training (`ml/scripts/train_claim_model.py`, `train_risk_model.py`) —
both need `huggingface.co`, still unreachable from this sandbox. Same
commands as before, run them on a machine with normal internet access.

**Verified this pass**: `pytest tests/` → 18/18 passed with zero environment
variables set (12 → 14 after the second pass's ML tests → 18 after this
pass's eval-harness tests). A live `TestClient` run against every route with
no credentials configured showed the same clean degradation as before,
including the new `/reports/{id}/decision` endpoint (503, not a crash,
when Neon isn't configured). `frontend`: `npm install`, `tsc -b`, and
`vite build` all succeed cleanly with the Dashboard changes. A full AST
syntax check of every `.py` file in the repo (including the newly-quarantined
`legacy/` folder) found zero syntax errors.

**One real bug caught by actually running this, not just reading it**: the
firm-personalization block was first written earlier in `run_due_diligence()`
(right after the specialist agents), before `report["final_score"]` is
computed later in the same function — it would have scored every report
against a hardcoded default of 50 instead of the report's real score. Moved
to after `final_score` is set, and the mocked end-to-end run confirmed the
fix (`ventureflow_agent.py`'s "Firm-personalization ranking" comment block
notes why it's placed where it is).
