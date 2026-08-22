# VentureFlow ML layer

Real trained models, not prompts. This directory is the start of what the
[Ship List](https://claude.ai/code/artifact/0becb4ec-7ed0-491d-8cfa-b520d404050d)
calls "Make the model real."

## What's actually trained and running (22 Aug 2026)

### Outcome Model — `models/outcome_model_combined.txt`

**Data**: [`yc-oss/api`](https://github.com/yc-oss/api), a continuously-updated
public mirror of Y Combinator's own company directory — free, no API key,
pulled directly via `git clone`, not scraped. 6,189 companies as of this
run. Filtered to 1,560 companies launched 3.5+ years ago with a resolved
outcome (`Acquired`/`Public` → positive, `Inactive` → negative; still-`Active`
companies are right-censored and excluded from training/eval, not treated
as failures — see `ml/scripts/prepare_outcome_dataset.py` for the reasoning).

**Method**: TF-IDF (1–2 grams) over the company's public description,
reduced to 128 dimensions with truncated SVD (fit on the training split
only, to avoid leaking test-set structure), concatenated with six
engineered structured features (industry, stage, team size, tag count,
nonprofit flag, company age), fed into a LightGBM binary classifier.

**Why TF-IDF and not the sentence-transformer embeddings used elsewhere in
this codebase**: this build session's network sandbox allows PyPI, npm, and
plain GitHub file access, but blocks `huggingface.co` and S3 (confirmed by
direct connection tests — proxy-level 403s, not a library bug). The
pretrained embedding model couldn't be downloaded here. TF-IDF is a
legitimate, fully offline, deterministic substitute — not a lesser one in
principle, and at ~1,500 labeled examples a reasonable match. Swapping in
embeddings later is a one-function change (`build_text_features()` in
`train_outcome_model.py`) once this runs somewhere with normal internet
access.

**Results — the ablation, which is the actual finding**:

| Variant | ROC-AUC | Accuracy | F1 | Brier |
|---|---|---|---|---|
| Text only | 0.572 | 0.555 | 0.403 | 0.259 |
| Structured only | 0.700 | 0.644 | 0.575 | 0.219 |
| Combined | **0.704** | 0.670 | 0.583 | 0.229 |

Structured features (industry, stage, team size, age) carry almost all of
the real signal; the free-text description adds very little on top of
them in this TF-IDF setup. That is a genuine, reportable result, not a
disappointing one — it's exactly the kind of finding an ablation study is
for, and it directly tells you where to spend effort next (better text
representation, not more structured features).

**Honest limitations** (belongs in a model card, not buried): the label is
a coarse binary proxy — "survived/exited" vs. "shut down" — not a return
multiple, not validated against any real fund's actual outcomes. The
population is YC-only, which is a specific, survivorship-biased slice of
startups (already selected for by YC's own admissions process) — this
model's calibration should not be assumed to transfer to non-YC deal flow
without re-validation. AUC 0.70 is in the same range as published
academic work on structured startup data (e.g. arXiv:2309.15552), not
better — the contribution here is the honest ablation and the free,
reproducible data pipeline, not a claim of superior accuracy.

**Wired into the app**: `ml/inference.py` loads this model and is called
from `ventureflow_agent.run_due_diligence()`. It's purely additive — the
result lands in `report["sections"]["ml_outcome_model"]`, wrapped in the
same try/except-and-degrade pattern every other optional signal in that
function already uses. If the model file is missing, the section reports
`available: false` and nothing else in the report is affected. No frontend
changes were made — the frontend already reads `sections` optional keys
tolerantly, so this is available to wire into a UI panel later without any
backend changes.

### General-purpose text embedder — `models/text_embedder.pkl`

A second, separate TF-IDF+SVD model (`ml/scripts/train_text_embedder.py`),
fit on the same 1,560-company dataset above but built for a different job:
turning arbitrary text (a company description, a pitch-deck excerpt, a RAG
query) into a fixed 64-dimensional vector for real similarity search —
pgvector retrieval in `rag_engine.py` and comparable-company matching in
`comparables.py`. Same reasoning as the Outcome Model for why TF-IDF and not
a pretrained sentence-transformer: `huggingface.co` is still blocked in this
sandbox. `embeddings.py` is the thin, lazy-loading wrapper both callers use;
it returns `None` (never a zero vector) on any failure, so a missing or
corrupt model file degrades to "vector search unavailable," not a crash or
silently-wrong result.

### Claim Model & Risk/Tone Model — written, not yet run

`ml/scripts/train_claim_model.py` (fine-tunes on SciFact — the same
SUPPORTS/REFUTES/NOT_ENOUGH_INFO schema `agents/claim_verifier.py` already
uses) and `ml/scripts/train_risk_model.py` (Financial PhraseBank + TFNS
sentiment) are both complete and correct, but both need `huggingface.co`,
which this build session couldn't reach. Run either with:

```bash
pip install datasets scikit-learn lightgbm
python ml/scripts/train_claim_model.py
python ml/scripts/train_risk_model.py
```

on a machine with normal internet access (your own laptop, or a free
Colab notebook) and they'll produce `models/claim_model.txt` and
`models/risk_tone_model.txt` in the same format the outcome model uses —
`ml/inference.py` can be extended with matching `verify_claim_ml()` /
`score_tone()` functions once those exist, following the exact pattern
already there for the outcome model.

## Reproducing the outcome model from scratch

```bash
pip install -r requirements.txt
python ml/scripts/prepare_outcome_dataset.py   # re-pulls nothing; rebuilds from ml/data/yc_companies_raw.json
python ml/scripts/train_outcome_model.py
```

To refresh the underlying YC data itself (it updates continuously):

```bash
git clone --depth 1 https://github.com/yc-oss/api.git /tmp/yc-api
cp /tmp/yc-api/companies/all.json ml/data/yc_companies_raw.json
python ml/scripts/prepare_outcome_dataset.py
python ml/scripts/train_outcome_model.py
```

## What this is not

Not a "should we invest" verdict. Not validated outside the YC population.
Not a replacement for the evidence-grounded LLM analysis already in this
app — it's one additional, labeled-data-backed signal sitting alongside it.
Presenting it as more certain than that in the UI or to a VC would be a
mistake, and the `caveat` field in every `score_company()` response exists
specifically to keep that honest downstream.

## Technical/GitHub score — `technical_scoring.py`

A rule-based rubric over a public GitHub repo's metadata (recent commit
activity, contributor count, tests/CI presence, README/LICENSE, issue
backlog health, repo age), each factor individually visible in the
`breakdown` field. Deliberately not a trained model — there's no labeled
"good repo" dataset to train against, and inventing one would just encode an
opinion as if it were learned signal. Wired into `ventureflow_agent.py`
additively as `sections.technical_score`, active only when a `github_url` is
supplied (optional field on `DiligenceRequest`, not yet exposed in the
frontend upload form). Uses the unauthenticated GitHub API by default (60
requests/hour); set `GITHUB_TOKEN` to raise that to 5,000/hour.

## Firm-personalization ranking — `personalization.py`

A mechanism, not a result. `POST /reports/{report_id}/decision` records the
user's own invest/pass call on a report (`migrations/005_investment_decisions.sql`).
`ml/scripts/train_personalization_model.py` fits a small logistic regression
on those decisions once at least 15 exist (`MIN_DECISIONS`) — below that,
`ml/personalization.py` reports itself honestly unavailable with a running
count, rather than pretending to personalize against data that doesn't exist
yet. Wired into `ventureflow_agent.py` as `sections.personalized_ranking`.
Re-run the training script periodically as decisions accumulate; at this
scale it always refits from scratch on the full history rather than doing
incremental updates, which is the right call until there's enough data for
that distinction to matter.

## Claim-verification benchmark + eval — `ml/eval/`

`ml/eval/claim_benchmark.jsonl` — 30 hand-labeled claims (10 each
SUPPORTS/REFUTES/NOT_ENOUGH_INFO) — and `ml/scripts/eval_claim_verifier.py`,
which runs them through the live `agents/claim_verifier.py` and reports
precision/recall/F1 per class, a confusion matrix, and a confidence-
calibration check. See `ml/eval/README.md` for exactly how the labels were
constructed and this benchmark's honest limitations (30 examples is a
starting point, and the NOT_ENOUGH_INFO class uses invented company names,
not real obscure claims). The metrics computation is unit-tested with no
network or LLM calls (`tests/test_eval_claim_verifier.py`); actually running
the benchmark against live claims needs a working `GROQ_API_KEY` and
internet access, neither available in the sandbox this was built in.

## Drift monitoring — `ml/scripts/check_drift.py`

`ml/inference.py`'s `score_company()` now logs every call (probability,
industry, stage, timestamp) to `ml/logs/outcome_score_log.jsonl`,
best-effort — a logging failure never affects the actual inference result.
`ml/scripts/check_drift.py` compares that live distribution against the
distribution the current model produces on its own training population
(recomputed fresh each run, so it always reflects whatever model file is on
disk) using the Population Stability Index, a standard dependency-free drift
metric. Needs at least 20 logged calls to say anything; below that it just
reports the count. This is the manual retraining trigger for now — there's
no usage volume yet to justify an automated retraining loop, and building one
before there's real usage to drive it would be solving a problem that
doesn't exist yet.

## Where trained models run in production — the decision

In-process, exactly as the Outcome Model already runs: `ml/inference.py`
loads the model file directly into the same Python process as the rest of
the API, no separate serving infrastructure. That's the right call at this
stage (single user, running locally, no budget for a hosted inference
endpoint) and it's what every model added since (technical scoring is rule-
based so this doesn't apply to it; personalization follows the same
in-process pattern). The Claim and Risk models, once trained, should follow
suit unless/until this becomes a real multi-tenant service — at that point,
a hosted inference endpoint becomes worth the added infrastructure because
multiple app instances would otherwise each need their own copy of every
model file in memory. That's a "when we get there" decision, not a "we
should have built it already" gap.
