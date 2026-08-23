# Venture Flow

Venture Flow is an AI-assisted due-diligence workspace for reviewing companies, analyzing uploaded pitch materials, identifying risks, and exploring investment questions through a web dashboard.

**Live demo:** [venture-flow-w8hf.vercel.app](https://venture-flow-w8hf.vercel.app/)

The repository contains two deployable parts:

- `frontend/` — React, TypeScript, Vite, and Tailwind web application.
- Root Python files — FastAPI backend, analysis agents, data-ingestion utilities, and database helpers.

## Features

- Company due-diligence analysis with structured risk and confidence assessment.
- Pitch-deck upload and extraction in PDF, PowerPoint (.pptx), Word (.docx),
  plain text and Markdown. Multi-column slide layouts are reconstructed into
  reading order rather than read raster-first (see `pdf_extractor.py`).
- Founder names are read from the deck's team slide and shown back on the
  upload form for correction before each one is checked against public web
  evidence.
- Report export as PDF, Word or Markdown, all rendered from one shared
  content model (`report_document.py`).
- Conversational analysis endpoint for follow-up questions.
- Dashboard views for risks, team, market, and competitor information.
- PostgreSQL/Neon database helpers -- all persistence is Neon. (A legacy
  Supabase ingestion pipeline is quarantined in
  `legacy/supabase_ingestion/README.md` and not wired into the live app.)

## Tech stack

- Frontend: React 18, TypeScript, Vite, Tailwind CSS, Recharts, Framer Motion
- Backend: Python, FastAPI, Uvicorn
- AI: Groq
- Data: PostgreSQL/Neon only

## Local setup

**Prerequisites.** Python **3.11+** (developed and tested on 3.13; the codebase
uses PEP 604 `X | None` annotations that Pydantic resolves at runtime, so 3.9
will not work) and Node **20.19+ or 22.12+** (required by Vite 7 — an older
Node fails inside the bundler with an error that never mentions Node). A
`DATABASE_URL` for a Neon/PostgreSQL instance and a `GROQ_API_KEY` are both
required; `/health` reports which of them is missing.

Two terminals, roughly five minutes.

### 1. Clone and configure the backend

```bash
git clone https://github.com/JiviteshKumar/venture_flow.git
cd venture_flow
python -m venv .venv
```

Activate the environment:

```bash
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate
```

Install dependencies and configure local variables:

```bash
pip install -r requirements.txt
copy .env.example .env  # Windows
# cp .env.example .env  # macOS/Linux
```

Update `.env` with your own credentials. Never commit this file.

Run the API:

```bash
uvicorn api:app --reload --port 8000
```

The API will be available at `http://localhost:8000`; interactive documentation is at `http://localhost:8000/docs`.

### 2. Run the frontend

In a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

**Do not copy `frontend/.env.example` to `frontend/.env`.** There is no
frontend environment file to create for local development, and creating one
from that template is the fastest way to break the app: the template holds a
deployment placeholder (`https://your-backend.example.com`) and every API call
then fails with an opaque network error. With no `.env`, the frontend calls
`/api`, which `vite.config.ts` proxies to `http://localhost:8000`. That is the
supported local path and it needs no configuration.

The frontend runs at `http://localhost:5173`.

### 3. Confirm it is actually up

```bash
curl http://localhost:8000/health
```

Expected: `{"status":"healthy","database":"connected"}`. A `degraded` status
means `DATABASE_URL` is unset or unreachable — the API still serves, but
nothing persists.

Then open `http://localhost:5173` and upload a deck. Either `localhost` or
`127.0.0.1` works: both are in the default `ALLOWED_ORIGINS`, because a
browser treats them as different origins and allowing only one produces a page
that loads and then silently never populates.

## Environment variables

See `.env.example` and `frontend/.env.example` for the complete template.

- `DATABASE_URL` — PostgreSQL/Neon connection URL.
- `GROQ_API_KEY` — Groq API key for AI-powered analysis.
- `ALLOWED_ORIGINS` — Comma-separated origins allowed to call the API.
  Defaults to `http://localhost:5173,http://127.0.0.1:5173`; include both
  spellings of any dev host, since a browser treats them as distinct origins.
- `RATE_LIMIT_PER_MINUTE` — API rate limit, default `30`.
- `REDIS_URL` — optional; enables the multi-instance-safe rate limiter (see `rate_limiter.py`). Without it, rate limiting is in-memory and per-process, which is correct for local single-instance use.
- `GITHUB_TOKEN` — optional; raises the GitHub API rate limit for the technical/repo scoring rubric (`technical_scoring.py`) from 60/hour to 5,000/hour.
- `VITE_API_BASE_URL` — **deployment only.** Read by a built frontend (e.g. on
  Vercel). Ignored by `npm run dev`, which uses the `/api` proxy in
  `vite.config.ts`. The copy in the root `.env` is not read by anything local.

## API endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Health check (reports Neon connectivity) |
| `POST` | `/upload-pdf` | Extract text, claims, financials and founders from a deck (any supported format; kept at this path for compatibility) |
| `POST` | `/upload-document` | Same handler, under a format-neutral name |
| `POST` | `/analyze` | Queue a due-diligence run; returns `202` with a `job_id` |
| `GET` | `/analyze/status/{job_id}` | Poll a run — status, current pipeline `stage`, and the report when complete |
| `GET` | `/reports` | Saved report history |
| `GET` | `/reports/{id}` | Load one saved report |
| `GET` | `/reports/{id}/pdf` | Export a report as PDF |
| `GET` | `/reports/{id}/export/{fmt}` | Export a report as `pdf`, `docx` or `md` |
| `POST` `GET` | `/reports/{id}/comments` | Team notes on a report |
| `POST` | `/reports/{id}/decision` | Record an invest/pass decision |
| `GET` | `/companies/{name}/history` | Score history across repeat analyses |
| `POST` | `/chat` | Ask a follow-up question about an analysed deck |
| `GET` | `/database/stats` | Row counts for companies, reports and investments |

Analysis runs as a background job because a full pass takes roughly 2–4
minutes; `/analyze` returns immediately and the frontend polls
`/analyze/status/{job_id}`, which reports the pipeline's real current stage.

## Deploy the frontend with Vercel

1. Import this GitHub repository in Vercel.
2. Set **Root Directory** to `frontend`.
3. Use the default Vite build command: `npm run build`.
4. Add `VITE_API_BASE_URL` as an environment variable, set to your public backend URL without a trailing slash.
5. Deploy.

The FastAPI backend must be deployed separately to a Python-capable host. Add the Vercel domain to the backend's `ALLOWED_ORIGINS` environment variable.

## Repository hygiene

Local datasets, caches, virtual environments, `node_modules`, build output, and `.env` files are intentionally excluded from Git. They are not needed for a Vercel frontend deployment and must not be uploaded to GitHub.

## License

No license has been specified yet. Add one before redistributing or accepting external contributions.
