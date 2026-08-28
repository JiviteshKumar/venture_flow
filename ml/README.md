# VentureFlow ML layer

> **Canonical reference:** `ml/research/METHODOLOGY.md` is the single source of
> truth for what is validated, what is void, and what must not be demonstrated.
> Where this file disagrees with it, that document is correct and this one is a bug.


Real trained models, not prompts. This directory is the start of what the
[Ship List](https://claude.ai/code/artifact/0becb4ec-7ed0-491d-8cfa-b520d404050d)
calls "Make the model real."

## VentureFlow Score — `models/venturescore_model.pkl` (PRIMARY)

**This is the model that produces the score a VC sees.** It replaced the
hand-tuned scoring formula in `ventureflow_agent.py`; the LLM now explains
the number rather than producing it. Full methodology, results with
confidence intervals, calibration analysis and limitations live in
[`ml/research/README.md`](research/README.md), with every variant tried —
including the losers — in [`ml/research/EXPERIMENT_LOG.md`](research/EXPERIMENT_LOG.md).

**Data**: **1,298 resolved-outcome Y Combinator companies, filtered to tech
startups only.** Built by `ml/scripts/prepare_venturescore_dataset.py` with
30 features — YC's second-level `subindustry` taxonomy, 12 technology tag
indicators (SaaS / AI-ML / devtools / fintech / infra / ...), remote-work
posture, Bay Area and US geography, a normalised rebrand signal, and
description/one-liner length.

**Scope filter (this product evaluates tech startups and nothing else).**
The YC directory is not tech-only — it spans food and beverage, apparel, home
goods, therapeutics, medical devices and construction. Training on all of it
was a real scope mismatch, and not a cosmetic one: sector is among the
strongest signals the model learns, so an out-of-scope population changes what
the model predicts. The cut is on **software-core, not sector label**, because
those differ: a satellite-analytics company for farms is "agritech" in the
taxonomy and a software company in reality, while a meal-kit brand is
"Consumer" and not a tech startup at all. Three tiers — software sectors
included outright (B2B verticals, fintech, edtech, govtech, health IT,
consumer software); physically/biologically manufactured products excluded
outright (food, apparel, home goods, therapeutics, drug discovery, medical
devices, diagnostics); and everything hardware-adjacent (robotics, energy,
agriculture, automotive, space, proptech, contech) admitted **only** on
positive evidence of a software core, from the company's tags or its own
description.

The description check exists because tag data is unreliable for exactly the
ambiguous cases: PlanGrid — construction *software*, acquired by Autodesk for
$875M — carries the single tag "Construction" and a tags-only filter discarded
it. Spot-checked after the fix: PlanGrid, MyVR, 42Floors and Cruise are kept;
iCracked (phone repair), 99dresses (fashion) and Grouper (dating) are dropped.

**262 companies removed, 1,560 → 1,298.** Rebuild the unfiltered version for
comparison with `VENTUREFLOW_ALL_SECTORS=1`.

**Method**: calibrated Random Forest (isotonic), served as a 12-member
bootstrap ensemble so every prediction carries an interval. Selected over
LightGBM, XGBoost and logistic regression under repeated stratified 5-fold CV
with bootstrap confidence intervals.

**Headline results** (tech-only population, pooled out-of-fold n=3,894;
base rate 0.489):

| | ROC-AUC | 95% CI | Brier | ECE |
|---|---|---|---|---|
| Shipped model (RF, isotonic, deployable features) | 0.6772 | [0.661, 0.693] | 0.2223 | **0.0219** |
| Same model *with* hindsight features | 0.7340 | [0.718, 0.749] | 0.2088 | 0.0453 |

**The scope filter cost nothing.** Restricting to tech startups removed 17% of
the data and AUC still moved slightly *up* (0.6739 → 0.6772 against the
unfiltered population), with overlapping intervals — so this is "no measurable
loss", not "an improvement". The base rate also moved from 0.465 to 0.489,
i.e. the tech-only population is closer to balanced, which makes the
calibration numbers easier to interpret.

**The most important number in this repository is the gap between those two
rows.** `team_size` (mean |SHAP| 0.72, 3x the next feature) records *current*
headcount: exited companies have median 11 / mean 105, shut-down companies
median 3 / mean 10. That is successful companies having grown before the
snapshot, not a seed-stage signal — a model keeping it learns "large team
implies success" and would mark down exactly the four-person startups this
product exists to evaluate. `age_years` and `batch_year` encode
right-censoring (cohort exit rate falls 0.65 → 0.38 from 2010 to 2021-22).
All three are excluded from the shipped model. Doing so costs 0.048 AUC —
**about 22% of the model's above-chance signal was hindsight**.

Also excluded, at dataset level, as direct observations of the outcome:
`isHiring` (shut-down companies don't post jobs), `top_company` (YC's own
retrospective winner designation), and website liveness.

**Uncertainty, reported on every prediction**: `ensemble_std` and a 5th-95th
percentile `score_range` for model uncertainty, plus `feature_coverage` for
input uncertainty — the model trains on directory metadata but scores pitch
decks, and features like remote posture aren't recoverable from a deck.
Confidence degrades on either axis, because tight ensemble agreement over
mostly-imputed input is agreement about nothing. A `low`-confidence score is
blocked from producing a decisive INVEST or PASS.

**Wired in**: `ml/venturescore.py`, called from `ventureflow_agent.py`
*before* Groq synthesis so the memo explains the score instead of inventing
one. Same degradation contract as everything else here — if the model file is
missing it returns `available: False` and the report falls back to the old
hand-tuned formula (kept as `_legacy_formula_score()`) rather than failing.

**Honest limitations** (the full list is in `ml/research/README.md` §7):
AUC 0.674 is a weak-to-moderate signal that should inform a judgement, never
replace one. YC-only population, coarse survived-or-exited label, no external
validation, and description length ranking second in SHAP may partly reflect
directory-maintenance bias rather than company quality.

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

**Leakage correction, 23 Aug 2026 — read this before quoting any number
above or below.** This model shipped for months using `team_size` and
`age_years` as features. Those are the *exact* hindsight features the
VentureFlow Score model was rebuilt to exclude, so the pipeline was running two
models under contradictory methodology with nothing anywhere saying so. Both
are recorded at snapshot time, years after the outcome being predicted:
`team_size` measures growth that already happened, and `age_years` encodes
right-censoring. In the combined model `team_size` alone carried gain 1,978
against 390 for the next-largest structured feature — the model's single
strongest signal was hindsight.

The shipped model is now the **deployable** variant, trained on industry,
stage, tag count and nonprofit status only. `ml/inference.py` still accepts
`team_size` and `age_years` as arguments and ignores them.

**Results — the ablation, which is the actual finding**:

| Variant | ROC-AUC | Accuracy | F1 | Brier |
|---|---|---|---|---|
| Text only | 0.572 | 0.555 | 0.403 | 0.259 |
| Structured only, *with* hindsight | 0.705 | 0.651 | 0.586 | 0.216 |
| Combined, *with* hindsight | 0.704 | 0.651 | 0.566 | 0.228 |
| Structured only, deployable | 0.661 | 0.625 | 0.451 | 0.225 |
| **Combined, deployable (SHIPPED)** | **0.646** | 0.638 | 0.515 | 0.235 |

Two findings, not one.

*The ablation finding, unchanged*: structured features carry almost all of the
real signal; the free-text description adds very little on top of them in this
TF-IDF setup. That is exactly the kind of result an ablation study is for, and
it says where to spend effort next — a better text representation, not more
structured features.

*The leakage finding*: **removing the two hindsight features costs 0.058
ROC-AUC.** That is the honest price of the correction, and it is close to the
0.048 the VentureFlow Score model paid for the same exclusion — two independent
models on the same population agreeing on roughly how much of their
above-chance signal was hindsight. Any comparison of this model to published
work must use 0.646, not 0.704. Full numbers in
`ml/models/outcome_model_report.json`; the pre-correction report is preserved
as `outcome_model_report_before_leakage_fix.json`.

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
a pretrained sentence-transformer: `huggingface.co` was blocked in the sandbox
this was built in (it is reachable now). `embeddings.py` is the thin,
lazy-loading wrapper both callers use; it returns `None` (never a zero vector)
on any failure, so a missing or corrupt model file degrades to "vector search
unavailable," not a crash or silently-wrong result.

**Correction (22 Aug 2026):** the pgvector half of that sentence was aspirational
until this date. The embedder was real and `comparables.py` did use it, but the
`rag_engine.py` vector path **never once executed successfully** — the SQL passed
a Python list, psycopg adapted it to `double precision[]`, and pgvector defines
no `vector <=> double precision[]` operator, so every call raised
`UndefinedFunction` and silently fell back to keyword `LIKE` search. Fixed by
adding explicit `::vector` casts in `db.find_similar_reports_by_vector`, and
verified returning real cosine-ranked neighbours against the live database.

### Claim Model & Risk/Tone Model — RUN AT LAST, results below

These were "written but never run" through every prior session because
`huggingface.co` was blocked. **In this environment it is reachable, so both
were finally executed.** Both loaders had to be rewritten first, for a
*different* reason than the historical one: `datasets` 5.x removed support
for script-based datasets ("Dataset scripts are no longer supported"), and
both corpora are script-based with no parquet conversion available. They now
read their published source files directly — SciFact from AllenAI's S3
tarball, PhraseBank/TFNS from their Hub repos — which removes the dependency
on Hub script support entirely.

**Claim Model** (`models/claim_model.txt`) — SciFact, 1,109 claim/evidence
pairs. **Trained successfully, and the result is that it is not usable:**

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| NOT_ENOUGH_INFO | 0.735 | 0.602 | 0.662 | 83 |
| REFUTES | 0.063 | 0.042 | **0.050** | 48 |
| SUPPORTS | 0.393 | 0.527 | 0.451 | 91 |
| **Accuracy** | | | **0.45** | 222 |

REFUTES — the class that actually matters for due diligence — is essentially
never detected. **Deliberately not wired into the product**, because shipping
it would make claim verification worse than the existing Groq-based verifier.
This is a clean negative result rather than a failure: claim-evidence
entailment requires representing negation and relation, which lexical TF-IDF
overlap cannot do. It is empirical justification for the LLM-based verifier
the product already uses.

**Risk/Tone Model** (`models/risk_tone_model.txt`) — Financial PhraseBank +
TFNS, 15,376 examples. 77% accuracy, macro-F1 0.62 *on its own held-out news
data*; negative-class recall (0.31) is the weak point, and negative tone is the
class a risk detector most needs.

**The head-to-head evaluation this section said was needed has now been run,
and the model lost badly** (`ml/eval/risk_benchmark_results.json`, 28
hand-labeled excerpts):

| Detector | Precision | Recall | F1 | Boilerplate FP rate | Ranking AUC |
|---|---|---|---|---|---|
| Keyword dictionary (incumbent, shipped) | 0.917 | 0.733 | **0.815** | **0.077** | 0.836 |
| Risk/Tone model | 0.0 | 0.0 | 0.0 | 0.0 | 0.333 |

The tone model predicted `neutral` on all 28 excerpts, giving going-concern
disclosures a negative-class probability of 0.014–0.071. Its ranking AUC of
0.333 is *below* chance, meaning it ordered risky text below risk-free text.
The cause is domain shift: it was trained on short financial news headlines and
applied to long filing paragraphs, and Loughran & McDonald established in 2011
that news-derived sentiment does not transfer to filing prose. **Deliberately
not wired in.** The right conclusion is not "tune the threshold" — a
below-chance ranking has nothing to threshold — it is that this corpus is the
wrong training data for this job. See `ml/research/related_work.md` §6.

```bash
python ml/scripts/train_claim_model.py   # ~1 min
python ml/scripts/train_risk_model.py    # ~2 min
```

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

## Evaluation — `ml/eval/`

**Both benchmarks have now been run. The claim harness had existed since the
third pass and had never once been executed end to end; risk detection had no
benchmark at all.** Full methodology, label provenance and limitations are in
[`ml/eval/README.md`](eval/README.md); every figure below is reloadable from a
committed artifact in that directory.

### Claim verification

`ml/eval/claim_benchmark.jsonl` — **150 hand-labeled claims**, 50 each
SUPPORTS / REFUTES / NOT_ENOUGH_INFO, scored by
`ml/scripts/eval_claim_verifier.py` against the live
`agents/claim_verifier.py`.

The NOT_ENOUGH_INFO class is deliberately split in two. Half are invented
companies, the original set's style. Half are **real but obscure Y Combinator
companies paired with publicly undocumented metrics** — Siasto, Picwing, Zumo
Labs, Roost — where a search finds the company but not the claim. That is the
judgement an early-stage diligence tool has to make on every real deck, and the
invented-company examples cannot test it, because there the answer is available
from the absence of any search result at all. The previous version of this
section flagged that gap; this closes it.

The original 30 examples are preserved as `claim_benchmark_v1_30.jsonl` with
their results, so the "before" number stays reproducible.

### Risk detection

`ml/eval/risk_benchmark.jsonl` — **28 hand-labeled excerpts, 22 of them real
SEC filing text** pulled from EDGAR full-text search by
`ml/scripts/collect_risk_excerpts.py` and traceable to the filing by URL, plus
6 pitch-deck-register paragraphs because SEC filings do not cover the product's
actual input. 15 genuine red flags, 13 deliberately hard risk-free negatives.

The headline metric is the **boilerplate false-positive rate**, not recall. A
detector that flags everything scores perfect recall and is useless on
documents that are mostly hedged legal prose; the 13 negatives are safe-harbour
paragraphs, accounting-policy notes and macro risk factors, all saturated with
the vocabulary a keyword detector keys on. That number was completely
unmeasured before this benchmark existed.

### Baselines

Two, both run against the same inputs as the systems they benchmark:

- **`ml/scripts/eval_claim_model_baseline.py`** scores the TF-IDF Claim Model
  against the claim benchmark, reusing the exact web evidence the LLM verifier
  judged (the harness persists it per row). Re-retrieving would have made the
  gap partly a measure of DuckDuckGo's minute-to-minute variance rather than of
  the two models.
- **`ml/scripts/eval_score_baseline.py`** compares the VentureFlow Score to
  `_legacy_formula_score()`, the pre-ML fallback, on real labeled YC companies
  with the evidence state held fixed. Result in
  `ml/research/score_baseline_comparison.json`: the model reaches ROC-AUC
  **0.668** — **VOID as of 28 Aug 2026**, because that 300-company sample is
  drawn from `ml/data/venturescore_dataset.jsonl`, the model's own training
  file: 300 of 300 evaluated companies are in training. The true out-of-sample
  figure is **0.6356, CI95 [0.5617, 0.7021], n=261**
  (`ml/scripts/verify_out_of_sample.py`). See `ml/research/METHODOLOGY.md`
  §3.1 and §4.

  The legacy formula's **0.500** is unaffected and stands, returning one
  identical value for
  all 300 companies — it takes no company feature as input, so it cannot rank
  two companies against each other at all. The comparison is therefore not
  "the model is somewhat better"; it is that all company-level discrimination
  in this product comes from the model. The formula does respond to evidence,
  and far more sharply than the model does (a 95-point swing across evidence
  states against the model's 32), which is the trade the two make.

The metrics computations in both harnesses are unit-tested with no network or
LLM calls (`tests/test_eval_claim_verifier.py`).

**Operational note, learned the hard way.** Groq's free-tier daily token limit
is scoped to the **organization**, not the API key — a new key in the same org
inherits the exhausted budget. When it is hit, `agents/claim_verifier.py`
degrades to `NOT_ENOUGH_INFO` at confidence 0.0, which is indistinguishable in
a results file from a real verdict. The first 150-example run recorded 14 such
rows before this was noticed. Both harnesses now wait, retry, and then refuse
to write a provider outage as a measurement.

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