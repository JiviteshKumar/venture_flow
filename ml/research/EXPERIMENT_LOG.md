# Experiment log — VentureFlow Score

Chronological, including the variants that lost and the two design decisions
that were wrong on the first attempt. Machine-readable numbers for every arm
are in `venturescore_experiments.json`; this file records what was tried, in
what order, and what each result changed about the next step.

All arms use the same protocol: repeated stratified 5-fold CV (3 repeats,
n = 4,680 pooled out-of-fold predictions), 2,000-sample bootstrap CIs, all
transformers fit inside the training fold.

---

## E1 — Model families on the new 30-feature structured set

| # | Model | ROC-AUC | 95% CI | Brier | ECE | F1 |
|---|---|---|---|---|---|---|
| E1.1 | Logistic regression (baseline) | 0.6845 | [0.669, 0.699] | 0.2220 | 0.0436 | 0.5827 |
| E1.2 | LightGBM | 0.7063 | [0.691, 0.721] | 0.2211 | 0.0785 | 0.6092 |
| E1.3 | XGBoost | 0.7156 | [0.700, 0.730] | 0.2142 | 0.0516 | 0.6154 |
| E1.4 | Random Forest | **0.7243** | [0.709, 0.738] | 0.2088 | 0.0382 | 0.6060 |

**Outcome:** Random Forest wins on AUC, Brier *and* ECE simultaneously.
Unexpected — LightGBM was the project's incumbent default from the earlier
Outcome Model. Note logistic regression is only 0.04 behind the best tree
model, which is a reminder of how little headroom exists at this sample size.

## E2 — Does the new feature engineering beat the legacy six features?

| # | Model | Feature set | ROC-AUC | 95% CI |
|---|---|---|---|---|
| E2.1 | Logistic regression | legacy 6 | 0.6840 | [0.669, 0.699] |
| E2.2 | LightGBM | legacy 6 | 0.6948 | [0.680, 0.711] |
| E1.2 | LightGBM | new 30 | 0.7063 | [0.691, 0.721] |

**Outcome:** +0.0115 AUC for LightGBM from 24 additional features, with
heavily overlapping intervals. Honestly: a real but unproven improvement.
Notably logistic regression gains *nothing* (0.6840 → 0.6845), suggesting the
new features contribute mainly through interactions a linear model cannot use.

## E3 — Text ablation

| # | Feature set | ROC-AUC | 95% CI |
|---|---|---|---|
| E3.1 | Text only (TF-IDF+SVD 128d) | 0.5792 | [0.562, 0.596] |
| E3.2 | Structured + 32 text dims | 0.7135 | [0.698, 0.728] |
| E3.3 | Structured + 128 text dims | 0.7176 | [0.702, 0.731] |
| E1.2 | Structured only | 0.7063 | [0.691, 0.721] |

**Outcome:** replicates the earlier Outcome Model finding on a different
feature set and a stricter protocol. Text alone is barely above chance;
adding it to structured features moves AUC within noise. Combined with the
earlier gain analysis (text SVD features carried ~4x the split gain of all
structured features while adding ~0.004 AUC), the interpretation is that the
text block mostly provides capacity to fit noise. **Text is excluded from the
production model.**

## E4 — Leakage ablation (the decisive experiment)

Triggered by an observation during E1: `team_size` had mean |SHAP| 0.72, more
than 3x the next feature. Checking its distribution against the label:

| Class | n | median | mean | zero |
|---|---|---|---|---|
| Exited/acquired | 726 | 11 | 105.3 | 3.4% |
| Shut down | 834 | 3 | 10.3 | 5.4% |

The directory records *current* headcount. Since ~95% of both classes are
non-zero, this is not a crude "dead company has no staff" artefact — it is
successful companies having grown before the snapshot. Cohort exit rate also
falls 0.65 → 0.38 from the 2010 to the 2021–22 batches, which is censoring
rather than founder quality, implicating `age_years` and `batch_year`.

Removing all three:

| # | Model | ROC-AUC | 95% CI | Δ vs contaminated |
|---|---|---|---|---|
| E4.1 | Logistic regression | 0.6649 | [0.649, 0.680] | −0.0196 |
| E4.2 | LightGBM | 0.6462 | [0.631, 0.661] | −0.0601 |
| E4.3 | XGBoost | 0.6571 | [0.642, 0.672] | −0.0585 |
| E4.4 | Random Forest | 0.6759 | [0.660, 0.691] | −0.0484 |
| E4.5 | LightGBM + text 128d | 0.6510 | [0.635, 0.667] | −0.0666 |

**Outcome and the paper's headline finding.** Random Forest loses 0.0484 AUC
with non-overlapping intervals. Measured as signal above chance:
0.2243 → 0.1759, i.e. **~22% of apparent predictive power was hindsight**.

Two secondary observations:
- **LightGBM degrades furthest** (−0.0601), falling below plain logistic
  regression. The incumbent model choice was the one most dependent on the
  contaminated features — a good argument for running this ablation before
  selecting a model family, not after.
- Logistic regression degrades least (−0.0196), being least able to exploit
  the feature in the first place.

Production model selection was moved to the *deployable* arm after this
result. Selecting on the contaminated arm would have chosen whichever model
best exploited hindsight.

## E5 — Calibration

### E5a — First attempt (wrong, kept for the record)

Calibration was initially applied to LightGBM on the **contaminated** feature
set, before E4 existed:

| Method | ROC-AUC | ECE |
|---|---|---|
| None | 0.7063 | 0.0785 |
| Sigmoid | 0.6613 | 0.0402 |
| Isotonic | 0.6583 | 0.0435 |

**A 0.045 AUC loss to gain 0.038 ECE.** `CalibratedClassifierCV` refits each
base model on a fraction of the fold, and a model leaning on a few strong
features suffers badly from that reduction. This was a genuinely bad trade
that the first version of the selection code would have accepted silently,
because it selected on ECE alone.

Two changes resulted: calibration moved onto the model family and feature set
actually being shipped, and the selector now **rejects any calibration method
that costs more than 0.02 AUC**.

### E5b — Final (Random Forest, deployable features)

| Method | ROC-AUC | ECE | Brier | Verdict |
|---|---|---|---|---|
| None | 0.6759 | 0.0301 | 0.2220 | viable |
| Sigmoid | 0.6755 | 0.0225 | 0.2225 | viable |
| **Isotonic** | 0.6739 | **0.0210** | 0.2226 | **chosen** |

**Outcome:** 30% ECE reduction for 0.002 AUC. Random Forest was already the
best-calibrated family before any calibration layer (ECE 0.0382 in E1.4 vs
0.0785 for LightGBM), which is part of why the trade is cheap here and was
expensive in E5a.

## E6 — Artefact size (engineering, not statistics)

First production fit: 30 ensemble members × 400-tree forests × 3-fold
calibration ≈ **362 MB pickle**, 2.25s to load. Too large to version
alongside the code.

| Config | Members | Trees | min_samples_leaf | Size | AUC | ECE |
|---|---|---|---|---|---|---|
| v1 | 30 | 400 | 5 | 362 MB | 0.6694 | 0.0162 |
| **v2 (shipped)** | 12 | 120 | 8 | **26 MB** | 0.6739 | 0.0210 |

**Outcome:** 14x smaller, and AUC did not degrade (it moved +0.0045, within
noise; ECE moved −0.005, also within noise). The bootstrap spread is dominated
by *which companies* get resampled, not by how many forests average over them,
so shrinking the ensemble costs little.

## Cross-cutting notes

- **Every arm was run with the same seed (42)** and the same protocol, so the
  comparisons above are like-for-like.
- **No hyperparameter search was performed.** Defaults were lightly adjusted
  for dataset size and left alone. With CIs of ±0.015, a search would mostly
  fit the cross-validation noise; it is not obviously worth doing before the
  dataset grows.
- **What was not tried, and should be:** pipeline-derived features (claim
  confidence, risk counts, GitHub rubric) — blocked because they do not exist
  for the labelled companies without running the full LLM pipeline over all
  1,560. This is the largest known gap.

## Adjacent models trained this pass

| Model | Data | Result | Shipped? |
|---|---|---|---|
| Claim Model | SciFact, 1,109 pairs | 45% accuracy, REFUTES F1 **0.05** | **No** — would degrade the existing LLM verifier |
| Risk/Tone Model | PhraseBank + TFNS, 15,376 | 77% accuracy, macro-F1 0.62 | **No** — usable, but needs its own comparison against the incumbent keyword detector first |

Both had never been run in any prior session. Both loaders had to be rewritten
(`datasets` 5.x dropped script-based datasets) to read source files directly.
The Claim Model's failure is a clean negative result: lexical overlap cannot
represent negation or entailment, which is exactly why the product's
LLM-based claim verifier exists.
