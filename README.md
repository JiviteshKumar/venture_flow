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
- PostgreSQL/Neon-compatible database helpers and optional Supabase integration.

## Tech stack

- Frontend: React 18, TypeScript, Vite, Tailwind CSS, Recharts, Framer Motion
- Backend: Python, FastAPI, Uvicorn
- AI: Groq
- Data: PostgreSQL/Neon and optional Supabase

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
- `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` — optional Supabase configuration.
- `VITE_API_BASE_URL` — public backend URL used by the frontend.

## API endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `POST` | `/analyze` | Run company due diligence |
| `POST` | `/upload-pdf` | Extract content from an uploaded PDF |
| `POST` | `/chat` | Ask a follow-up analysis question |
| `GET` | `/database/stats` | Retrieve database statistics |

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
