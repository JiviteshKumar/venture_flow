# Deploying the VentureFlow backend to Render

Every step, in order. Roughly 30 minutes, most of it waiting for the first
build.

The frontend already deploys to Vercel. What has never been deployed is the
FastAPI backend, which is why `VITE_API_BASE_URL` still points at
`http://localhost:8000`. This connects the two.

---

## Before you start

You need three things:

| | Where it comes from |
|---|---|
| A Render account | render.com — the free plan is enough to *create* the service, but see the plan note in Step 3 |
| Your Neon connection string | Neon console → your project → Connection Details |
| Your Groq API key | console.groq.com → API Keys |

The repository is already pushed to `github.com/JiviteshKumar/venture_flow` and
contains `render.yaml`, so Render can read most of this configuration itself.

---

## Step 1 — Decide what happens to the 93 existing reports

**Do this before the service is reachable from the internet, not after.**

Every report currently in your Neon database has `owner_user_id = NULL`. That is
the marker for "written before accounts existed", and the API treats it as
*shared* — readable by any caller, signed in or not. Report ids are sequential
integers, so once the backend is public, `GET /reports/1`, `/reports/2` … walks
the entire history.

Check the count yourself:

```bash
python -c "from dotenv import load_dotenv; load_dotenv(); import db; c=db.connection().__enter__().cursor(); c.execute('SELECT count(*) AS n FROM dd_reports WHERE owner_user_id IS NULL'); print(c.fetchone())"
```

Pick one:

- **Delete them.** They are analyses of test decks and public pitch decks; none
  is a real customer's. This is what I would do.

  ```bash
  python -c "from dotenv import load_dotenv; load_dotenv(); import db; conn=db.connection().__enter__(); cur=conn.cursor(); cur.execute('DELETE FROM dd_reports WHERE owner_user_id IS NULL'); print('deleted', cur.rowcount)"
  ```

- **Assign them to your own account.** Register first, then set
  `owner_user_id` to your user id for every NULL row.

- **Gate the whole API** by setting `DEMO_ACCESS_TOKEN` in Step 4. This is a
  shared passphrase in front of everything, which is a blunt instrument but
  closes the hole in one move.

---

## Step 2 — Get the right Neon connection string

In the Neon console, open **Connection Details** and copy the **Pooled
connection** string. It looks like:

```
postgresql://USER:PASSWORD@ep-xxxx-pooler.region.aws.neon.tech/DATABASE?sslmode=require
```

Two things matter:

- Use the **pooled** endpoint (the hostname contains `-pooler`). Render restarts
  the process on every deploy and Neon's direct endpoint has a low connection
  ceiling.
- Keep `?sslmode=require`. Neon rejects unencrypted connections, and the error
  you get without it is an unhelpful timeout.

You do **not** need to run any migrations by hand. `db.py` applies them on
startup — you will see `Applied N Neon schema migration(s)` in the deploy log.

---

## Step 3 — Create the service

### Option A — Blueprint (uses `render.yaml`, fewer things to mistype)

1. Render Dashboard → **New +** → **Blueprint**.
2. Connect your GitHub account if you have not already, and pick
   **JiviteshKumar/venture_flow**.
3. Render reads `render.yaml` and shows one service, `ventureflow-api`.
4. It will prompt for the three secrets marked `sync: false`
   (`DATABASE_URL`, `GROQ_API_KEY`, `ALLOWED_ORIGINS`). You can paste
   `DATABASE_URL` and `GROQ_API_KEY` now and put a placeholder in
   `ALLOWED_ORIGINS` — you will not know the real Vercel URL until Step 7.
5. **Apply**.

### Option B — By hand

1. Render Dashboard → **New +** → **Web Service** → connect the repo.
2. Fill in exactly:

   | Field | Value |
   |---|---|
   | Name | `ventureflow-api` |
   | Language | `Python 3` |
   | Branch | `main` |
   | Root Directory | *(leave blank)* |
   | Build Command | `pip install --upgrade pip && pip install -r requirements.txt` |
   | Start Command | `uvicorn api:app --host 0.0.0.0 --port $PORT --workers 1` |
   | Health Check Path | `/health` |

3. Instance type: **Standard**, not Free. See below.

### About the plan — this one is not optional

The service loads a 23 MB scikit-learn pickle (`venturescore_model.pkl`), a
LightGBM booster, a text embedder, and — whenever an uploaded deck turns out to
be image-only — onnxruntime and opencv for OCR. Unpickled and resident that does
not fit in the 512 MB the Free and Starter instances provide.

The failure mode is the reason to care. It is not a clean startup crash; the
process gets OOM-killed part-way through somebody's four-minute analysis, the
job row is left marked running, and the user watches a spinner that never
resolves.

Free also spins down after 15 minutes of inactivity, and a cold start takes
around 50 seconds — during which the frontend's first request times out.

Start on **Standard** (2 GB). Watch the memory graph for a week and step down if
it genuinely fits.

---

## Step 4 — Set the environment variables

Render Dashboard → your service → **Environment**. Add each of these.

### Required

| Key | Value |
|---|---|
| `DATABASE_URL` | the pooled Neon string from Step 2 |
| `GROQ_API_KEY` | your Groq key |
| `PYTHON_VERSION` | `3.13.2` |
| `TRUST_PROXY_HEADERS` | `true` |

`TRUST_PROXY_HEADERS` matters more than it looks. Render terminates TLS at a
load balancer, so without it every request appears to come from the same proxy
IP and the rate limiter treats all of your users as one client — the 31st
request in a minute, from anyone, gets a 429.

### Strongly recommended

| Key | Value | Why |
|---|---|---|
| `DEMO_ACCESS_TOKEN` | a long random passphrase | The outer gate from Step 1. Leave unset only if you deleted or assigned the unowned reports. |
| `ALLOWED_ORIGINS` | your Vercel URL (Step 7) | Without it, the browser blocks every response. |

### Defaults that are already correct

`RATE_LIMIT_PER_MINUTE=30`, `MAX_CONCURRENT_ANALYSES=3`,
`GROQ_TOKENS_PER_MINUTE=8000`. `render.yaml` sets these; if you built the
service by hand you can leave them unset and the code defaults match.

Do **not** raise `MAX_CONCURRENT_ANALYSES` or add workers to buy throughput. The
Groq free tier is 200,000 tokens per day — four to eight analyses in total, per
day, across everyone — and the per-minute pacer is process-local, so a second
worker would double the request rate against a limit it cannot see.

---

## Step 5 — Deploy, and read the log

Render builds automatically. Open **Logs** and look for, in order:

1. `Installing dependencies` — two to four minutes. `lightgbm`,
   `scikit-learn` and `rapidocr-onnxruntime` are the slow ones.
2. `Applied N Neon schema migration(s)` — the database is reachable and the
   schema is current. **If you do not see this, stop and fix `DATABASE_URL`;
   everything after it will fail in confusing ways.**
3. `Uvicorn running on http://0.0.0.0:10000`
4. `Your service is live 🎉`

Note the URL: `https://ventureflow-api.onrender.com` (Render may append a
suffix).

---

## Step 6 — Verify the backend on its own

```bash
curl https://ventureflow-api.onrender.com/health
```

Expect HTTP 200. Then:

```bash
curl https://ventureflow-api.onrender.com/
```

If you set `DEMO_ACCESS_TOKEN`, the gate now covers everything except a small
public set — `/`, `/health`, `/docs`, `/openapi.json`, `/redoc` and the
`/auth/*` routes (they have to stay open or nobody could sign in). Note that
`/docs` staying public means your API surface is browsable; that is deliberate,
but worth knowing.

Check the gate actually bites on a real data route:

```bash
curl -i https://ventureflow-api.onrender.com/reports
```

A 401 here is the gate working. A 200 means the variable did not take effect;
re-check the spelling and redeploy.

---

## Step 7 — Point the frontend at the backend

**This is the step with the trap.** `VITE_API_BASE_URL` is inlined by Vite at
**build** time, not read at runtime. Setting it in Vercel does nothing to the
build that is already deployed — you have to redeploy afterwards.
`frontend/src/services/apiClient.ts` says so at the top of the file, and warns
in the console in production if the variable is missing.

1. Vercel → your project → **Settings** → **Environment Variables**.
2. Add `VITE_API_BASE_URL` = `https://ventureflow-api.onrender.com`
   (no trailing slash), scoped to **Production**.
3. **Deployments** → most recent → **⋯** → **Redeploy**. Uncheck "use existing
   build cache".
4. Copy your production URL, e.g. `https://venture-flow.vercel.app`.

---

## Step 8 — Close the CORS loop

Back in Render → **Environment**:

| Key | Value |
|---|---|
| `ALLOWED_ORIGINS` | `https://venture-flow.vercel.app` |

If you also want Vercel preview deployments to work, add an **anchored** regex:

| Key | Value |
|---|---|
| `ALLOWED_ORIGIN_REGEX` | `^https://venture-flow-[a-z0-9-]+\.vercel\.app$` |

Keep the `^` and `$`. A bare `.*vercel\.app` would let any site hosted on Vercel
call your API and spend your Groq quota.

Save — Render redeploys automatically.

---

## Step 9 — Verify end to end

1. Open your Vercel URL.
2. If you set `DEMO_ACCESS_TOKEN`, enter the passphrase.
3. Register an account.
4. Upload a deck — `ml/eval/decks/Uber.pdf` from this repo is a good first test.
5. Watch the progress; the stages come from the backend's real job row.
6. When it finishes, check three things specifically:
   - the score is present and not the legacy 50.0 fallback,
   - the Bull and Bear panels have signals,
   - **Download PDF works** — that path was broken until recently and is the
     easiest regression to reintroduce.

Open your browser's Network tab during the upload. Requests should go to
`ventureflow-api.onrender.com`, not `localhost:8000`. If they go to localhost,
Step 7's redeploy did not happen.

---

## When it goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| Browser shows "Network Error", Render logs show 200 | CORS — the origin is not allowed | Step 8. The server answered; the browser discarded it. |
| Requests still go to `localhost:8000` | Vite inlines at build time | Redeploy Vercel *after* setting the variable (Step 7.3) |
| 502 shortly after a request starts | OOM — the model files did not fit | Move to Standard (Step 3) |
| First request of the day takes ~50 s | Free instance spun down | Move off Free, or accept it |
| `Applied N migrations` never appears | `DATABASE_URL` wrong, unpooled, or missing `sslmode=require` | Step 2 |
| Everything returns 401 | `DEMO_ACCESS_TOKEN` is set | Expected. Send the passphrase, or unset it. |
| Analyses return "insufficient evidence" everywhere | Groq daily quota spent | 200,000 tokens/day is 4–8 analyses. `python scripts/verify_when_quota_returns.py --check-only` shows the remaining budget. |
| Every user shares one rate limit | `TRUST_PROXY_HEADERS` unset | Step 4 |

---

## What this does not give you

Stated plainly, because they are the next things to fix and none is a Render
setting:

- **No password reset and no email verification.** There is no email provider
  wired in, so a user who forgets their password is locked out permanently, and
  anyone can register under any address.
- **The Groq free tier is the real capacity ceiling.** 200,000 tokens per day is
  four to eight analyses for the whole deployment. The second user of a busy day
  gets a degraded report — an honest one that says so, but degraded.
- **One instance, no horizontal scaling.** The token pacer is process-local, so
  a second instance would exceed the per-minute limit without either instance
  noticing.
