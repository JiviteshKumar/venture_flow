# Venture Flow

Venture Flow is an AI-assisted due-diligence workspace for reviewing companies, analyzing uploaded pitch materials, identifying risks, and exploring investment questions through a web dashboard.

**Live demo:** [venture-flow-w8hf.vercel.app](https://venture-flow-w8hf.vercel.app/)

The repository contains two deployable parts:

- `frontend/` — React, TypeScript, Vite, and Tailwind web application.
- Root Python files — FastAPI backend, analysis agents, data-ingestion utilities, and database helpers.

## Features

- Company due-diligence analysis with structured risk and confidence assessment.
- PDF upload and extraction for pitch-deck review.
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
copy .env.example .env  # Windows
# cp .env.example .env  # macOS/Linux
npm run dev
```

For local development, set `VITE_API_BASE_URL=http://localhost:8000` in `frontend/.env`. The frontend runs at `http://localhost:5173` by default.

## Environment variables

See `.env.example` and `frontend/.env.example` for the complete template.

- `DATABASE_URL` — PostgreSQL/Neon connection URL.
- `GROQ_API_KEY` — Groq API key for AI-powered analysis.
- `ALLOWED_ORIGINS` — Comma-separated URLs allowed to call the API.
- `RATE_LIMIT_PER_MINUTE` — API rate limit, default `30`.
- `REDIS_URL` — optional; enables the multi-instance-safe rate limiter (see `rate_limiter.py`). Without it, rate limiting is in-memory and per-process, which is correct for local single-instance use.
- `GITHUB_TOKEN` — optional; raises the GitHub API rate limit for the technical/repo scoring rubric (`technical_scoring.py`) from 60/hour to 5,000/hour.
- `VITE_API_BASE_URL` — public backend URL used by the frontend.

## API endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Health check (reports Neon connectivity) |
| `POST` | `/upload-pdf` | Extract text, claims and financials from a PDF |
| `POST` | `/analyze` | Queue a due-diligence run; returns `202` with a `job_id` |
| `GET` | `/analyze/status/{job_id}` | Poll a run — status, current pipeline `stage`, and the report when complete |
| `GET` | `/reports` | Saved report history |
| `GET` | `/reports/{id}` | Load one saved report |
| `GET` | `/reports/{id}/pdf` | Export a report as PDF |
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
