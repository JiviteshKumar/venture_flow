# VentureFlow Score — methodology, results, limitations

Working paper material for the VentureFlow due-diligence system. Everything
in this directory was produced by code in `ml/scripts/` that was actually
executed; every number below can be regenerated with the commands in
"Reproducing" at the end. Where something could not be run, that is stated
rather than estimated.

Companion artefacts in this directory:

- `venturescore_experiments.json` — the full experiment log, every arm, with
  bootstrap confidence intervals and reliability curves.
- `venturescore_feature_importance.json` — SHAP rankings, reported twice
  (shipped feature set, and the contaminated set for contrast).

---

## 1. Motivation

Prior to this work the score a VC saw was produced by a hand-tuned formula:

```python
raw = 100 - (risk_score * 0.5) - claim_penalty - financial_penalty + quality_bonus
```

The constants were chosen by hand and never validated against any outcome.
The formula is not defensible to a sceptical investor and not publishable.
The goal of this pass was to replace it with a trained, calibrated model
whose failure modes are measured rather than assumed, and to demote the LLM
from *producing* the number to *explaining* it.

The contribution claimed here is deliberately not "we predict which startups
succeed." At this sample size and with this label, that claim would not
survive review. The contribution is the decomposed, evidence-grounded
architecture; an honest calibration and uncertainty story; and — the finding
we consider most useful to others working on startup-outcome prediction — a
quantification of how much of the accuracy typically reported on this kind of
data is an artefact of hindsight features.

## 2. Data

**Source.** [`yc-oss/api`](https://github.com/yc-oss/api), an MIT-licensed,
continuously-updated public mirror of Y Combinator's own company directory.
No API key, no scraping, no paid data. The snapshot in this repository holds
**6,189 companies**.

**Label.** A binary survived-or-exited proxy:

| Directory status | Label | Reasoning |
|---|---|---|
| `Acquired`, `Public` | 1 | Resolved positive outcome |
| `Inactive` | 0 | Resolved negative outcome |
| `Active` | *dropped* | Right-censored — outcome not yet observed |

**Filtering.** Companies launched less than 3.5 years before the snapshot are
dropped: a company that launched last year is `Active` by definition, not
because it beat the odds. Companies with fewer than 40 characters of
description are dropped as unusable.

| Step | Count |
|---|---|
| Raw companies | 6,189 |
| Dropped — younger than 3.5 years | 2,197 |
| Dropped — still `Active` (censored) | 2,229 |
| Dropped — no usable description | 203 |
| **Retained** | **1,560** |
| — positive (exited/acquired) | 726 |
| — negative (shut down) | 834 |
| Base rate | 0.465 |

Treating still-active companies as failures would have roughly tripled the
dataset and produced much better-looking numbers. It would also have been
wrong, which is why it was not done.

## 3. Feature engineering

An audit of the raw dump found several fields at 97–100% coverage that the
previous model never used. Features were chosen to be *tech-startup-specific*
wherever a generic alternative existed.

**Retained (30 features):**

- **Sector taxonomy** — `industry`, plus YC's second-level `subindustry`
  split into its top and leaf halves (`B2B -> Infrastructure` vs
  `B2B -> Marketing`). 59 distinct values, far finer than the 15-way
  top-level industry alone.
- **Technology tags** (12 binary features) — SaaS, AI/ML, developer tools,
  fintech, marketplace, healthcare, infrastructure, consumer, analytics,
  hardware, productivity, B2B. This is the most explicitly tech-specific
  block: a general startup-success model has no notion of "is this a
  developer-tools company."
- **Remote-work posture** — fully/partly/any remote, from `regions`. A real
  structural variable for software companies.
- **Geography** — `is_bay_area`, `is_us`. San Francisco alone accounts for
  2,276 of the 6,189 raw companies.
- **Rebrand signal** — `has_former_name`, after normalising away
  legal-suffix-only variants (91 raw `former_names` entries are literally
  the string `"Inc."`; counting those as pivots would be measuring
  punctuation).
- **Text shape** — description and one-liner length.

### 3.1 Excluded as target leakage

This is the most consequential design decision in the work. Each of the
following is present in the raw data and each *improves* offline metrics,
while making the model invalid for its actual purpose.

**Excluded at dataset level — observations of the outcome:**

| Field | Why it leaks |
|---|---|
| `isHiring` | A shut-down company does not post jobs. |
| `top_company` | YC's own retrospective designation of its winners — very nearly the label wearing a different hat. |
| website liveness | Resolving each domain to see if the site still loads would recover the label almost perfectly. |

**Excluded from the production model — temporally contaminated:**

| Field | Evidence of contamination |
|---|---|
| `team_size` | Exited: median 11, mean 105. Shut down: median 3, mean 10. Only 3.4% / 5.4% are zero, so this is not a crude "dead company has no staff" artefact — it is successful companies having *grown* before the snapshot. |
| `age_years`, `batch_year` | Cohort exit rate falls monotonically from ~0.65 (2010 batches) to ~0.38 (2021–22). That is right-censoring, not evidence that recent founders are worse. |

`team_size` is the single strongest feature in the data — mean |SHAP| 0.72,
more than three times the next feature. A model that keeps it learns "large
team implies success," which inverts the product's purpose: it would
systematically mark down exactly the four-person seed-stage startups a VC is
trying to evaluate. It was removed, and the cost of removing it is reported
below rather than hidden.

## 4. Evaluation protocol

- **Repeated stratified 5-fold cross-validation, 3 repeats.** A single 80/20
  split on 1,560 rows has a standard error wide enough that two models
  differing by 0.02 AUC are indistinguishable; reporting one as definitive is
  the most common way small-data ML misleads.
- **Every transformer fit inside the training fold only** — TF-IDF vocabulary,
  SVD basis, scaler, one-hot encodings, and the calibration map. Fitting a
  vectoriser on all rows before splitting is a subtle and very common leak.
- **2,000-sample percentile bootstrap** over companies for all confidence
  intervals.
- **Calibration** measured by expected calibration error (10 bins) and Brier
  score, with reliability curves recorded.
- **No comparable-company or RAG feature is used**, which structurally
  prevents a retrieved neighbour from leaking its own label into a score.

## 5. Results

All figures are pooled out-of-fold predictions, n = 4,680 (1,560 × 3 repeats).
Chance is 0.5; base rate is 0.465.

### 5.1 Model families and feature sets

| Variant | ROC-AUC | 95% CI | Brier | ECE | F1 |
|---|---|---|---|---|---|
| logreg, new structured | 0.6845 | [0.669, 0.699] | 0.2220 | 0.0436 | 0.5827 |
| lgbm, new structured | 0.7063 | [0.691, 0.721] | 0.2211 | 0.0785 | 0.6092 |
| xgb, new structured | 0.7156 | [0.700, 0.730] | 0.2142 | 0.0516 | 0.6154 |
| **rf, new structured** | **0.7243** | [0.709, 0.738] | 0.2088 | 0.0382 | 0.6060 |
| logreg, legacy 6 features | 0.6840 | [0.669, 0.699] | 0.2184 | 0.0331 | 0.5247 |
| lgbm, legacy 6 features | 0.6948 | [0.680, 0.711] | 0.2223 | 0.0687 | 0.5904 |

**Feature engineering helped, modestly and within noise.** LightGBM on the new
30-feature set reaches 0.7063 vs 0.6948 on the legacy six — a gain of 0.0115
with heavily overlapping intervals. Reported as a real but unproven
improvement, not a win.

**Random Forest beat the incumbent LightGBM on every metric.** This was not
expected — LightGBM was the existing project default — and RF wins on AUC,
Brier *and* calibration simultaneously.

### 5.2 Text ablation

| Variant | ROC-AUC | 95% CI |
|---|---|---|
| Text only (TF-IDF+SVD, 128d) | 0.5792 | [0.562, 0.596] |
| Structured only (lgbm) | 0.7063 | [0.691, 0.721] |
| Combined, 32 text dims | 0.7135 | [0.698, 0.728] |
| Combined, 128 text dims | 0.7176 | [0.702, 0.731] |

This **replicates and sharpens the earlier Outcome Model finding**. Text alone
is barely above chance. Adding 128 text dimensions to the structured set moves
AUC by +0.011 with fully overlapping intervals.

The sharper version of the finding comes from feature importances on the
earlier model: text SVD features carried total gain 11,575 against 3,003 for
all structured features combined, while contributing ~0.004 AUC. The text
features are not merely uninformative — they *absorb most of the model's
capacity to fit noise*. That is an argument for aggressive regularisation or
dropping text entirely at this data volume, not for a better text encoder.

### 5.3 The leakage ablation — the load-bearing result

Removing `team_size`, `age_years` and `batch_year`:

| Variant | ROC-AUC | 95% CI | Brier | ECE |
|---|---|---|---|---|
| logreg, deployable | 0.6649 | [0.649, 0.680] | 0.2283 | 0.0514 |
| lgbm, deployable | 0.6462 | [0.631, 0.661] | 0.2398 | 0.0924 |
| xgb, deployable | 0.6571 | [0.642, 0.672] | 0.2317 | 0.0655 |
| **rf, deployable** | **0.6759** | [0.660, 0.691] | 0.2220 | 0.0301 |
| lgbm + text, deployable | 0.6510 | [0.635, 0.667] | 0.2361 | 0.0853 |

Random Forest drops from **0.7243 → 0.6759**, a loss of 0.0484 AUC with
non-overlapping confidence intervals. Measured as signal above chance, that is
0.2243 → 0.1759: **roughly 22% of the model's apparent predictive power was
hindsight**, not foresight.

This matters beyond this project. Published work on structured startup-outcome
data commonly reports AUC in the 0.70 range, and directory-sourced features
like current headcount are an obvious thing to include. Our result suggests
that a meaningful share of such figures may not be available at the decision
point they are implicitly claimed to inform. We do not claim this generalises
to any specific published result — only that the ablation is cheap, and that
we have not seen it reported.

Note also that **LightGBM degrades furthest** under the clean feature set
(0.6462, below even logistic regression at 0.6649). The incumbent model choice
was the one most dependent on the contaminated features.

### 5.4 Calibration

Random Forest on the deployable feature set:

| Calibration | ROC-AUC | ECE | Brier |
|---|---|---|---|
| None | 0.6759 | 0.0301 | 0.2220 |
| Sigmoid (Platt) | 0.6755 | 0.0225 | 0.2225 |
| **Isotonic (shipped)** | 0.6739 | **0.0210** | 0.2226 |

Isotonic regression reduces ECE by 30% for 0.002 AUC — accepted. Reliability
of the shipped model:

| Predicted | Observed | n |
|---|---|---|
| 0.166 | 0.185 | 54 |
| 0.258 | 0.288 | 417 |
| 0.347 | 0.347 | 1,537 |
| 0.446 | 0.464 | 1,162 |
| 0.542 | 0.520 | 688 |
| 0.642 | 0.569 | 304 |
| 0.743 | 0.803 | 127 |
| 0.848 | 0.780 | 109 |
| 0.954 | 0.911 | 282 |

Well-behaved through the middle of the range, where almost all mass sits —
the 0.347 bin holds 1,537 of 4,680 predictions and is calibrated to three
decimal places. The two visible deviations are the 0.642 bin (predicted
0.642, observed 0.569) and 0.848 (predicted 0.848, observed 0.780), both of
which are *over*-confident, and both in the upper-middle range on a few
hundred samples. Calibration is weakest where the least data is, which is
worth knowing before trusting an unusually high score.

**A negative result worth recording:** calibration was first attempted on
LightGBM with the contaminated feature set, and cost 0.045 AUC (0.7063 →
0.6613) to gain 0.038 ECE. `CalibratedClassifierCV` refits each base model on
a fraction of the fold, and a model that depends on a few strong features
suffers more from that reduction. The final selection procedure therefore
rejects any calibration method costing more than 0.02 AUC — a guard added
because the naive choice was wrong, not anticipated in advance.

### 5.5 Feature importance (SHAP)

Shipped model, top features by mean |SHAP|:

| Feature | mean \|SHAP\| |
|---|---|
| subindustry_leaf=Productivity | 0.438 |
| desc_len | 0.248 |
| one_liner_len | 0.208 |
| has_former_name | 0.151 |
| is_partly_remote | 0.126 |
| industry=B2B | 0.126 |
| num_tags | 0.086 |
| is_bay_area | 0.085 |
| tag_saas | 0.079 |

Two observations we would flag to a reader rather than dress up:

1. **Description length ranks second and third.** How much a founder wrote is
   doing real work. This is plausibly a genuine diligence signal (detail
   correlates with substance) but it is also exactly the kind of feature that
   could reflect a directory-maintenance artefact — successful companies'
   entries being updated more thoroughly over time. We cannot currently
   distinguish these, and it is listed in the limitations.
2. **The tech-specific features earn their place but do not dominate.**
   `tag_saas`, `is_bay_area`, `subindustry_leaf` all appear in the top ten,
   supporting the design choice, at modest individual magnitude.

### 5.6 Uncertainty

The shipped artefact is a 12-member bootstrap ensemble. Two uncertainty
sources are reported separately because they mean different things:

- **Model uncertainty** — spread of ensemble member predictions, reported as
  `ensemble_std` and a 5th–95th percentile `score_range`.
- **Input uncertainty** — `feature_coverage`, the fraction of features
  actually observed rather than imputed. The model trains on directory
  metadata but scores pitch decks, and several features (remote posture, YC
  subindustry, rebrand history) are simply not recoverable from a deck.

Confidence degrades on *either* axis, and coverage can veto a confident
label: tight ensemble agreement computed on mostly-imputed input is agreement
about nothing. In the pipeline, a `low` confidence score is blocked from
producing a decisive INVEST or PASS recommendation.

## 6. Deployment

The score reaching the investor is:

```
venture_score = 100 × clamp(model_probability − evidence_penalty)
```

`evidence_penalty` is a bounded, transparent term derived from *this report's*
verified evidence — refuted claims, absent verifiable claims, risk-signal
score, missing financials, data quality. The model has never read the deck, so
without this term the pipeline's own verification work would not reach the
headline number at all.

It is deliberately **not** a second learned layer. Fitting one requires
labelled data linking claim-verification outcomes to company outcomes, and no
such dataset exists. Inventing the relationship and presenting it as learned
would be precisely the failure mode this project's methodology is built to
avoid. Both components are reported separately on every report
(`model_only_score`, `evidence_penalty`) so a reader can always see which one
moved the number.

The LLM receives the finished score as a fact to explain, and is instructed
never to state a different one, and to surface disagreement explicitly rather
than quietly substituting its own judgement. Ordering is enforced by a test
(`test_the_memo_prompt_receives_the_score_before_synthesis`) because the
regression is silent if it recurs.

## 7. Limitations

Written to the standard of the rest of this repository: these are real, and
a reader should weigh them before trusting anything above.

1. **Sample size.** 1,560 companies. Confidence intervals are ±0.015 AUC and
   differences smaller than that are noise. Several comparisons above are
   within noise and are labelled as such.
2. **The label is a coarse proxy.** Survived-or-exited, not a return
   multiple, not an IRR, not anything a fund would size a check with. An
   acqui-hire at a loss and a decacorn IPO are the same label.
3. **Survivorship at the population level.** Every company here was already
   selected by YC's admissions process. Calibration should not be assumed to
   transfer to non-YC deal flow without revalidation, and we have not
   revalidated it — we have no non-YC labelled data.
4. **Right-censoring.** Excluding still-active companies is the honest
   choice, but it biases toward older cohorts, where outcomes have resolved.
   The model has effectively never seen a 2024–25 company.
5. **Description length may be an artefact.** See §5.5. It ranks second and
   we cannot currently rule out directory-maintenance bias.
6. **Train/serve feature mismatch.** Trained on directory metadata, served on
   pitch decks. `feature_coverage` measures and reports this rather than
   solving it. Typical deck-derived coverage is 0.67–0.79.
7. **Tags are matched differently at train and serve time.** Training used
   YC's curated tag list; inference does keyword matching over deck text.
   This is a weaker signal, and is one reason deck-derived coverage is
   reported lower.
8. **The evidence penalty weights are a stated prior, not a fitted layer.**
   They are visible on every report and should be replaced by a fitted layer
   once enough outcome-labelled reports exist.
9. **Pipeline features remain untrainable.** Claim-verification confidence,
   founder verification, risk counts and GitHub scores are computed at
   inference time and do not exist for the 1,560 labelled companies. Training
   on them requires running the full pipeline over the training set — an LLM
   cost not yet incurred. This is the single largest missed opportunity in the
   current feature set.
10. **No external validation.** Every number is cross-validated on one
    dataset from one source. There is no held-out second population.
11. **Absolute performance is modest.** AUC 0.674 is a weak-to-moderate
    signal. It should inform a judgement, never replace one. The product
    surfaces the score with its interval and confidence for that reason.

## 8. Where a VC's judgement should override the model

Stated plainly because the audience will and should ask:

- Any company outside the YC-like population — different geography, much
  later stage, non-software.
- Anything where `feature_coverage` is low; the score is then mostly prior.
- Any case where the memo's evidence section and the score disagree. The
  evidence was computed on *this* company; the score is a population
  statistic.
- Founder quality, product insight, and market timing. The model has no
  feature for any of these, and its silence is not evidence of absence.

## 9. Related trained models in this repository

Two models that had never been run in any prior session were trained during
this pass, after `huggingface.co` turned out to be reachable in this
environment (it was blocked in every previous one). Both required rewriting
their loaders: `datasets` 5.x removed support for script-based datasets, so
both now read their source files directly.

**Claim Model** (`ml/models/claim_model.txt`) — TF-IDF+SVD → LightGBM on
SciFact, 1,109 claim/evidence pairs. **Result: not usable.**

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| NOT_ENOUGH_INFO | 0.735 | 0.602 | 0.662 | 83 |
| REFUTES | 0.063 | 0.042 | 0.050 | 48 |
| SUPPORTS | 0.393 | 0.527 | 0.451 | 91 |
| **Accuracy** | | | **0.45** | 222 |

REFUTES is essentially never detected. This is a clean negative result and it
is informative: claim–evidence entailment requires representing negation and
relation, which lexical TF-IDF overlap cannot do. **This model is deliberately
not wired into the product** — shipping it would make claim verification
worse. It stands as empirical justification for the existing LLM-based
verifier rather than as a failure.

**Risk/Tone Model** (`ml/models/risk_tone_model.txt`) — Financial PhraseBank +
TFNS, 15,376 examples, 77% accuracy, macro-F1 0.62 (negative-class recall
0.31 is the weak point). Usable, but **not wired in**: replacing or augmenting
the existing keyword-based risk detector needs its own comparative evaluation,
and doing that properly is a separate piece of work rather than something to
bundle into this pass.

## 10. Reproducing

```bash
pip install -r requirements.txt
pip install shap xgboost pandas matplotlib datasets

python ml/scripts/prepare_venturescore_dataset.py
python ml/scripts/train_venturescore_model.py
```

Runtime is a few minutes on a laptop CPU. `SEED = 42` throughout; the
cross-validation, bootstrap and ensemble resampling are all seeded, so the
numbers above reproduce exactly on the same data snapshot.

To refresh the underlying YC snapshot (it updates continuously, so numbers
will shift):

```bash
git clone --depth 1 https://github.com/yc-oss/api.git /tmp/yc-api
cp /tmp/yc-api/companies/all.json ml/data/yc_companies_raw.json
python ml/scripts/prepare_venturescore_dataset.py
python ml/scripts/train_venturescore_model.py
```

The optional models:

```bash
python ml/scripts/train_claim_model.py   # ~1 min, downloads SciFact from S3
python ml/scripts/train_risk_model.py    # ~2 min, downloads from HF Hub
```
