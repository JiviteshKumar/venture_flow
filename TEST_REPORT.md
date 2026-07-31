# VentureFlow QA test report

Tested on 2026-07-31 against the checked-out `main` branch and the deployed Vercel site at `https://venture-flow-w8hf.vercel.app/`.

## Feature checklist and results

| Area | Test | Expected | Result |
| --- | --- | --- | --- |
| Navigation | Open dashboard `/` | Dashboard and empty state load | Pass |
| Navigation | Open `/upload` directly | React upload page loads | Fail (fixed in this branch) |
| Navigation | Open `/analysis` directly | React analysis page loads | Fail (fixed in this branch) |
| Dashboard | No-report empty state | Clear prompt to upload | Pass |
| API validation | Empty company name | Request rejected with validation error | Pass |
| API analysis | Valid normalized report and comparable-company result | Response includes persisted report ID | Pass (mocked deterministic test) |
| API analysis | Persistence failure | Non-sensitive 503 returned | Pass (mocked deterministic test) |
| PDF upload | File type, size, unreadable-PDF guards | 400/422 response | Code reviewed; not live-submitted to avoid transmitting a personal deck |
| Database | Existing Neon schema inspection | Tables match application queries | Fail (migration supplied; not applied) |
| RAG context | Completed report context | Retrieval stats reflect `relevant_reports` | Fail (fixed in this branch) |
| Frontend build | TypeScript and Vite production build | Build completes | Pass |

## Findings

### QA-001 — blocker — report persistence fails on legacy Neon schema

**Evidence:** screenshots 1, 2, 4, 5, 9, 10, and 11. Read-only inspection found integer-key legacy tables with no `companies.name` unique index and no `dd_reports.verdict` or `dd_reports.raw_output` columns. The API performs `ON CONFLICT (name)` and writes those columns.

**Reproduction:** run an analysis against the current schema; `persist_report` fails, returning `503 Analysis completed but could not be saved` after analysis work has finished.

**Resolution:** `migrations/002_repair_legacy_neon_schema.sql` adds the missing fields/indexes, preserves legacy report content in JSONB, and removes the incorrect one-report-per-company constraint. Its rollback companion is included.

### QA-002 — major — deep links return Vercel 404

**Evidence:** live checks of `/upload` and `/analysis` returned Vercel `NOT_FOUND`; navigation from `/` works only because the client router intercepts it.

**Reproduction:** paste `https://venture-flow-w8hf.vercel.app/upload` in a new browser tab.

**Resolution:** `frontend/vercel.json` rewrites all app routes to `index.html` for React Router.

### QA-003 — major — report-context retrieval logs a false RAG error

**Evidence:** screenshots 3, 8, and 11 show `RAG error: 'relevant_claims'`. `rag_engine.build_context()` returns `relevant_reports`, while `ventureflow_agent.py` reads removed legacy keys.

**Resolution:** map report retrieval to `reports_retrieved`.

### QA-004 — minor — production bundle is large

Vite reports a 908 kB minified JavaScript chunk (260 kB gzip). No behavior is blocked; consider route-level code splitting after the current reliability fixes deploy.

## Risks and remaining coverage

- No authentication, admin, or payment flow exists in the current route/API inventory.
- A real PDF was not uploaded to the public site during QA, so end-to-end external AI/search latency remains to be rechecked after the backend deploy and migration.
- The target Neon connection has zero rows, so the migration’s legacy-data preservation path is reviewed but not exercised with production records.
