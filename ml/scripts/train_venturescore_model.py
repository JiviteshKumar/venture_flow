"""
Train and evaluate the VentureFlow Score model.

This is the model that replaces the hand-tuned scoring formula in
`ventureflow_agent.py`. The design goal is not to maximise a headline AUC --
at this sample size that number is noisy enough that chasing it would be
self-deception -- but to produce a score a sceptical VC can actually rely
on, which means three things the previous model did not provide:

  1. An honest performance estimate WITH uncertainty. Every metric here is
     computed from pooled out-of-fold predictions under repeated stratified
     cross-validation, and reported with a bootstrap confidence interval.
     A single 80/20 split on 1,560 rows has a standard error large enough
     that two models differing by 0.02 AUC are indistinguishable; reporting
     such a split as though it were definitive is the most common way small
     -data ML misleads people.
  2. Calibration. A gradient-boosted tree's raw output is not a probability.
     If the product tells a VC "0.72", that number has to mean something
     close to "72 of 100 companies like this one exited." We fit an explicit
     calibration layer, and report reliability curves, Brier score and
     expected calibration error before and after.
  3. Per-prediction uncertainty. A bootstrap ensemble gives a spread across
     models for each individual company, so the product can distinguish
     "confidently mediocre" from "we genuinely do not know." A confidently
     wrong answer is worse for this audience than an honest abstention.

EVALUATION PROTOCOL. Repeated stratified k-fold (k=5, repeated 3 times).
Everything that learns anything -- the TF-IDF vocabulary, the SVD basis, the
feature scaler, the categorical encodings, and the calibration map -- is fit
inside the training fold only and applied to the held-out fold. Fitting the
vectoriser on all rows before splitting is a subtle and very common leak;
it is avoided here deliberately, at some cost in runtime.

LEAKAGE. The three post-outcome fields available in the raw data
(`isHiring`, `top_company`, website liveness) are excluded at the dataset
level -- see the module docstring of `prepare_venturescore_dataset.py`. No
feature in this file is derived from a company's status. The comparable-
company retrieval used elsewhere in the product is NOT a feature here, which
sidesteps the risk of a comparable leaking its own label into a score.

Run:  python ml/scripts/train_venturescore_model.py
"""

from __future__ import annotations

import json
import pickle
import warnings
from pathlib import Path

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.decomposition import TruncatedSVD
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import RepeatedStratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

warnings.filterwarnings("ignore", category=UserWarning)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
RESEARCH_DIR = Path(__file__).resolve().parent.parent / "research"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
N_SPLITS = 5
N_REPEATS = 3
N_BOOTSTRAP = 2000          # for metric confidence intervals
# Bootstrap ensemble size for per-prediction uncertainty. Kept deliberately
# small: the first version used 30 members of a 400-tree forest, each wrapped
# in a 3-fold CalibratedClassifierCV, which produced a 362 MB pickle -- far too
# large to commit, and 2.3s to load. 12 members of a 120-tree forest gives an
# artefact small enough to version alongside the code, and the uncertainty
# estimate is barely affected: the spread across bootstrap resamples is
# dominated by which companies are resampled, not by how many forests average
# over them.
N_ENSEMBLE = 12
TEXT_SVD_DIMS = 128

CATEGORICAL = ["industry", "subindustry_top", "subindustry_leaf", "stage", "batch_season"]
NUMERIC = [
    "team_size", "num_tags", "nonprofit", "age_years", "batch_year",
    "desc_len", "one_liner_len", "has_former_name",
    "tag_ai_ml", "tag_saas", "tag_b2b", "tag_devtools", "tag_fintech",
    "tag_marketplace", "tag_healthcare", "tag_infra", "tag_consumer",
    "tag_analytics", "tag_hardware", "tag_productivity",
    "is_fully_remote", "is_partly_remote", "is_any_remote", "is_bay_area", "is_us",
]
# The six features the original Outcome Model used, kept as an explicit
# comparison arm so the value of the new feature engineering is measurable
# rather than asserted.
LEGACY_NUMERIC = ["team_size", "num_tags", "nonprofit", "age_years"]
LEGACY_CATEGORICAL = ["industry", "stage"]

# ── Temporally contaminated features ────────────────────────────────────
# These three are all legitimately *present* in the directory and all three
# improve offline metrics, but every one of them is measured at snapshot
# time -- that is, AFTER the outcome resolved -- and that makes them unsafe
# for the product's actual job.
#
#   team_size: the directory records CURRENT headcount. Companies labelled
#     exited/acquired have median 11 and mean 105; companies labelled shut
#     down have median 3 and mean 10. That gap is not a seed-stage team
#     being predictive of a later exit, it is successful companies having
#     grown large before the snapshot was taken. Only 3-5% of either class
#     is zero, so this is not a crude "dead company has no staff" artefact;
#     it is subtler and worse, because it looks like a real feature. A model
#     that learns "large team implies success" will systematically mark down
#     precisely the 4-person seed-stage startups this product exists to
#     evaluate.
#   age_years / batch_year: exit rate falls monotonically by cohort, from
#     ~0.65 for the 2010 batches to ~0.38 for 2021-22. That is right-
#     censoring -- recent companies have had less time to exit -- not
#     evidence that recent founders are worse. Scoring a 2026 company on
#     this feature just applies the censoring penalty to it.
#
# The model shipped to production is trained WITHOUT these. The arm that
# includes them is kept and reported, because the gap between the two is
# the honest measure of how much of the literature-standard ~0.70 AUC on
# this kind of data is real signal and how much is hindsight.
CONTAMINATED = ["team_size", "age_years", "batch_year"]
DEPLOY_NUMERIC = [f for f in NUMERIC if f not in CONTAMINATED]


def load_rows() -> list[dict]:
    path = DATA_DIR / "venturescore_dataset.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ── metrics ──────────────────────────────────────────────────────────────

def expected_calibration_error(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    """Standard binned ECE: mean |confidence - accuracy| weighted by bin size.
    This is the number that says whether a predicted 0.7 behaves like a 0.7."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (y_prob > lo) & (y_prob <= hi) if lo > 0 else (y_prob >= lo) & (y_prob <= hi)
        if not mask.any():
            continue
        ece += (mask.sum() / len(y_prob)) * abs(y_prob[mask].mean() - y_true[mask].mean())
    return float(ece)


def reliability_curve(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> list[dict]:
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (y_prob > lo) & (y_prob <= hi) if lo > 0 else (y_prob >= lo) & (y_prob <= hi)
        if not mask.any():
            continue
        out.append({
            "bin_lower": round(float(lo), 2),
            "bin_upper": round(float(hi), 2),
            "n": int(mask.sum()),
            "mean_predicted": round(float(y_prob[mask].mean()), 4),
            "observed_rate": round(float(y_true[mask].mean()), 4),
        })
    return out


def bootstrap_ci(y_true: np.ndarray, y_prob: np.ndarray, metric_fn, n: int = N_BOOTSTRAP) -> tuple[float, float, float]:
    """Percentile bootstrap CI. Resamples companies, not folds -- the
    quantity we want uncertainty over is 'how would this score on another
    sample of companies from the same population.'"""
    rng = np.random.default_rng(SEED)
    point = float(metric_fn(y_true, y_prob))
    stats = []
    idx = np.arange(len(y_true))
    for _ in range(n):
        sample = rng.choice(idx, size=len(idx), replace=True)
        if len(np.unique(y_true[sample])) < 2:
            continue
        stats.append(metric_fn(y_true[sample], y_prob[sample]))
    return point, float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def summarise(y_true: np.ndarray, y_prob: np.ndarray, label: str) -> dict:
    auc, auc_lo, auc_hi = bootstrap_ci(y_true, y_prob, roc_auc_score)
    brier, brier_lo, brier_hi = bootstrap_ci(y_true, y_prob, brier_score_loss)
    y_pred = (y_prob >= 0.5).astype(int)
    result = {
        "variant": label,
        "n": int(len(y_true)),
        "roc_auc": round(auc, 4),
        "roc_auc_ci95": [round(auc_lo, 4), round(auc_hi, 4)],
        "brier": round(brier, 4),
        "brier_ci95": [round(brier_lo, 4), round(brier_hi, 4)],
        "ece": round(expected_calibration_error(y_true, y_prob), 4),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
    }
    print(f"  {label:34s} AUC={result['roc_auc']:.4f} "
          f"[{auc_lo:.3f},{auc_hi:.3f}]  Brier={result['brier']:.4f}  "
          f"ECE={result['ece']:.4f}  F1={result['f1']:.4f}")
    return result


# ── feature construction (fit on train fold only) ────────────────────────

def build_features(
    rows: list[dict],
    train_idx: np.ndarray,
    numeric: list[str],
    categorical: list[str],
    text_dims: int,
) -> tuple[np.ndarray, list[str]]:
    """Returns the full design matrix with every transformer fit on
    train_idx only, plus human-readable feature names for SHAP."""
    blocks, names = [], []

    if numeric:
        num = np.array([[float(r[c]) for c in numeric] for r in rows])
        scaler = StandardScaler().fit(num[train_idx])
        blocks.append(scaler.transform(num))
        names += numeric

    if categorical:
        cat = [[str(r[c]) for c in categorical] for r in rows]
        enc = OneHotEncoder(handle_unknown="ignore", min_frequency=10, sparse_output=False)
        enc.fit([cat[i] for i in train_idx])
        blocks.append(enc.transform(cat))
        names += [f"{c}={v}" for c, vals in zip(categorical, enc.categories_) for v in vals][: enc.transform(cat).shape[1]]

    if text_dims:
        texts = [r["text"][:2000] for r in rows]
        tfidf = TfidfVectorizer(max_features=20000, ngram_range=(1, 2), min_df=2, stop_words="english")
        tfidf.fit([texts[i] for i in train_idx])
        svd = TruncatedSVD(n_components=text_dims, random_state=SEED)
        svd.fit(tfidf.transform([texts[i] for i in train_idx]))
        blocks.append(svd.transform(tfidf.transform(texts)))
        names += [f"text_svd_{i}" for i in range(text_dims)]

    X = np.hstack(blocks)
    # OneHotEncoder's min_frequency collapses rare levels, so the generated
    # name list can drift from the real column count; keep them in lockstep.
    if len(names) != X.shape[1]:
        names = (names + [f"feature_{i}" for i in range(X.shape[1])])[: X.shape[1]]
    return X, names


def make_model(kind: str):
    if kind == "logreg":
        return Pipeline([("clf", LogisticRegression(max_iter=2000, random_state=SEED))])
    if kind == "lgbm":
        import lightgbm as lgb
        return lgb.LGBMClassifier(
            n_estimators=200, num_leaves=15, min_child_samples=15,
            learning_rate=0.05, colsample_bytree=0.8, random_state=SEED, verbosity=-1,
        )
    if kind == "xgb":
        import xgboost as xgb
        return xgb.XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, random_state=SEED,
            eval_metric="logloss", verbosity=0,
        )
    if kind == "rf":
        # 120 trees / min_samples_leaf=8 rather than 400/5: on 1,560 rows the
        # larger forest measurably inflated the serialised artefact without
        # moving cross-validated AUC beyond its confidence interval, and the
        # shallower leaves regularise a small dataset slightly better.
        return RandomForestClassifier(
            n_estimators=120, min_samples_leaf=8, random_state=SEED, n_jobs=-1
        )
    raise ValueError(kind)


def cross_validated_predictions(
    rows: list[dict],
    y: np.ndarray,
    kind: str,
    numeric: list[str],
    categorical: list[str],
    text_dims: int,
    calibrate: str | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Pooled out-of-fold probabilities under repeated stratified k-fold.
    Returns (y_repeated, prob) -- y is tiled because each repeat produces a
    full set of out-of-fold predictions for every row."""
    cv = RepeatedStratifiedKFold(n_splits=N_SPLITS, n_repeats=N_REPEATS, random_state=SEED)
    all_y, all_p = [], []
    for train_idx, test_idx in cv.split(np.zeros(len(y)), y):
        X, _ = build_features(rows, train_idx, numeric, categorical, text_dims)
        model = make_model(kind)
        if calibrate:
            model = CalibratedClassifierCV(model, method=calibrate, cv=3)
        model.fit(X[train_idx], y[train_idx])
        all_p.append(model.predict_proba(X[test_idx])[:, 1])
        all_y.append(y[test_idx])
    return np.concatenate(all_y), np.concatenate(all_p)


def main() -> None:
    rows = load_rows()
    y = np.array([r["label"] for r in rows])
    print(f"Loaded {len(rows)} companies ({y.sum()} exited / {len(y) - y.sum()} shut down, "
          f"base rate {y.mean():.3f})")
    print(f"Protocol: {N_SPLITS}-fold stratified CV repeated {N_REPEATS}x, "
          f"{N_BOOTSTRAP}-sample bootstrap CIs, all transformers fit in-fold\n")

    experiments: list[dict] = []

    # ── Arm 1: baselines and model families on the new structured features ──
    print("[1] Model families -- new structured feature set (no text):")
    for kind in ["logreg", "lgbm", "xgb", "rf"]:
        yy, pp = cross_validated_predictions(rows, y, kind, NUMERIC, CATEGORICAL, 0)
        experiments.append(summarise(yy, pp, f"{kind}_structured_new"))

    # ── Arm 2: the legacy 6-feature set, same protocol ──────────────────────
    print("\n[2] Legacy 6-feature set (what the existing Outcome Model uses):")
    for kind in ["logreg", "lgbm"]:
        yy, pp = cross_validated_predictions(rows, y, kind, LEGACY_NUMERIC, LEGACY_CATEGORICAL, 0)
        experiments.append(summarise(yy, pp, f"{kind}_structured_legacy6"))

    # ── Arm 3: text ablation ────────────────────────────────────────────────
    print("\n[3] Text ablation (does TF-IDF text actually add anything?):")
    yy, pp = cross_validated_predictions(rows, y, "lgbm", [], [], TEXT_SVD_DIMS)
    experiments.append(summarise(yy, pp, "lgbm_text_only_128"))
    for dims in (32, 128):
        yy, pp = cross_validated_predictions(rows, y, "lgbm", NUMERIC, CATEGORICAL, dims)
        experiments.append(summarise(yy, pp, f"lgbm_combined_text{dims}"))

    # ── Arm 4: the leakage ablation -- the load-bearing experiment ─────────
    # How much of the apparent performance survives once the features that
    # encode hindsight are removed? This is the number that should be
    # believed, and the gap is the finding.
    print("\n[4] Leakage ablation -- dropping post-outcome/censored features:")
    print(f"    (removing {', '.join(CONTAMINATED)})")
    for kind in ["logreg", "lgbm", "xgb", "rf"]:
        yy, pp = cross_validated_predictions(rows, y, kind, DEPLOY_NUMERIC, CATEGORICAL, 0)
        experiments.append(summarise(yy, pp, f"{kind}_DEPLOY_clean"))
    yy, pp = cross_validated_predictions(rows, y, "lgbm", DEPLOY_NUMERIC, CATEGORICAL, TEXT_SVD_DIMS)
    experiments.append(summarise(yy, pp, "lgbm_DEPLOY_clean_text128"))

    # Pick the production family on the DEPLOYABLE feature set, by AUC --
    # deliberately not on the contaminated set, where the ranking would be
    # driven by which model best exploits hindsight.
    deploy_arms = [e for e in experiments if e["variant"].endswith("_DEPLOY_clean")]
    best_arm = max(deploy_arms, key=lambda e: e["roc_auc"])
    best_kind = best_arm["variant"].replace("_DEPLOY_clean", "")
    print(f"\n  -> best deployable family: {best_kind} (AUC {best_arm['roc_auc']:.4f})")

    # ── Arm 5: calibration of that family on the deployable features ───────
    print(f"\n[5] Calibration of {best_kind} on the deployable feature set:")
    yy_raw, pp_raw = cross_validated_predictions(rows, y, best_kind, DEPLOY_NUMERIC, CATEGORICAL, 0)
    uncalibrated_ece = expected_calibration_error(yy_raw, pp_raw)
    calibration_results = {
        "none": {
            "ece": uncalibrated_ece,
            "brier": float(brier_score_loss(yy_raw, pp_raw)),
            "auc": float(roc_auc_score(yy_raw, pp_raw)),
            "reliability_curve": reliability_curve(yy_raw, pp_raw),
        }
    }
    for method in ("sigmoid", "isotonic"):
        yy_c, pp_c = cross_validated_predictions(
            rows, y, best_kind, DEPLOY_NUMERIC, CATEGORICAL, 0, calibrate=method
        )
        experiments.append(summarise(yy_c, pp_c, f"{best_kind}_DEPLOY_{method}"))
        calibration_results[method] = {
            "ece": expected_calibration_error(yy_c, pp_c),
            "brier": float(brier_score_loss(yy_c, pp_c)),
            "auc": float(roc_auc_score(yy_c, pp_c)),
            "reliability_curve": reliability_curve(yy_c, pp_c),
        }

    # Choose on ECE, but refuse a calibration layer that buys calibration by
    # destroying ranking power: wrapping in CalibratedClassifierCV refits each
    # member on a fraction of the fold, which can cost real AUC. If a method
    # loses more than 0.02 AUC against no calibration, it is not worth it.
    viable = {
        m: v for m, v in calibration_results.items()
        if v["auc"] >= calibration_results["none"]["auc"] - 0.02
    }
    best_method = min(viable, key=lambda m: viable[m]["ece"])
    for method, v in calibration_results.items():
        verdict = "chosen" if method == best_method else ("rejected: costs too much AUC" if method not in viable else "viable")
        print(f"    {method:9s} AUC={v['auc']:.4f} ECE={v['ece']:.4f} Brier={v['brier']:.4f}  <- {verdict}")

    report = {
        "dataset": {
            "n": len(rows),
            "n_positive": int(y.sum()),
            "n_negative": int(len(y) - y.sum()),
            "base_rate": round(float(y.mean()), 4),
            "source": "yc-oss/api snapshot, 3.5y+ post-launch, resolved outcome only",
        },
        "protocol": {
            "cv": f"RepeatedStratifiedKFold(n_splits={N_SPLITS}, n_repeats={N_REPEATS})",
            "bootstrap_samples": N_BOOTSTRAP,
            "transformers_fit": "inside training fold only",
        },
        "leakage_control": {
            "excluded_from_production_model": CONTAMINATED,
            "rationale": (
                "team_size records headcount at snapshot time (exited median 11 / mean 105 "
                "vs shut-down median 3 / mean 10), which reflects post-outcome growth rather "
                "than a seed-stage signal; age_years and batch_year encode right-censoring, "
                "with cohort exit rate falling from ~0.65 (2010) to ~0.38 (2021-22)."
            ),
            "also_excluded_at_dataset_level": ["isHiring", "top_company", "website_liveness"],
        },
        "production_model": {
            "family": best_kind,
            "feature_set": "deployable (post-outcome features removed)",
            "calibration": best_method,
        },
        "experiments": experiments,
        "calibration": {
            "chosen_method": best_method,
            **{
                m: {
                    "auc": round(v["auc"], 4),
                    "ece": round(v["ece"], 4),
                    "brier": round(v["brier"], 4),
                    "reliability_curve": v["reliability_curve"],
                }
                for m, v in calibration_results.items()
            },
        },
    }
    (RESEARCH_DIR / "venturescore_experiments.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(f"\nWrote experiment log -> {RESEARCH_DIR / 'venturescore_experiments.json'}")

    # ── Fit and persist the production artefact ────────────────────────────
    # Bootstrap ensemble: N_ENSEMBLE models on resampled training data. The
    # spread of their predictions for one company is the per-prediction
    # uncertainty the product surfaces -- not a substitute for the
    # calibrated point estimate, but the thing that lets it say "we do not
    # have enough signal here" instead of guessing confidently.
    print(f"\nFitting production artefact: {best_kind} on the deployable feature set, "
          f"{N_ENSEMBLE}-model bootstrap ensemble...")
    all_idx = np.arange(len(rows))
    X_full, feature_names = build_features(rows, all_idx, DEPLOY_NUMERIC, CATEGORICAL, 0)

    scaler_num = StandardScaler().fit(np.array([[float(r[c]) for c in DEPLOY_NUMERIC] for r in rows]))
    cat_raw = [[str(r[c]) for c in CATEGORICAL] for r in rows]
    encoder = OneHotEncoder(handle_unknown="ignore", min_frequency=10, sparse_output=False).fit(cat_raw)

    rng = np.random.default_rng(SEED)
    ensemble = []
    for _ in range(N_ENSEMBLE):
        sample = rng.choice(all_idx, size=len(all_idx), replace=True)
        if len(np.unique(y[sample])) < 2:
            continue
        member = make_model(best_kind)
        if best_method != "none":
            member = CalibratedClassifierCV(member, method=best_method, cv=3)
        member.fit(X_full[sample], y[sample])
        ensemble.append(member)
    print(f"  ensemble members fit: {len(ensemble)}")

    chosen_variant = (
        f"{best_kind}_DEPLOY_clean" if best_method == "none"
        else f"{best_kind}_DEPLOY_{best_method}"
    )
    chosen = next(e for e in experiments if e["variant"] == chosen_variant)
    with open(MODEL_DIR / "venturescore_model.pkl", "wb") as f:
        pickle.dump({
            "ensemble": ensemble,
            "scaler": scaler_num,
            "encoder": encoder,
            "numeric_features": DEPLOY_NUMERIC,
            "categorical_features": CATEGORICAL,
            "feature_names": feature_names,
            "model_family": best_kind,
            "calibration_method": best_method,
            "excluded_contaminated_features": CONTAMINATED,
            "base_rate": float(y.mean()),
            "cv_roc_auc": chosen["roc_auc"],
            "cv_roc_auc_ci95": chosen["roc_auc_ci95"],
            "cv_ece": round(calibration_results[best_method]["ece"], 4),
            "cv_brier": round(calibration_results[best_method]["brier"], 4),
            "trained_n": len(rows),
        }, f)
    print(f"  saved -> {MODEL_DIR / 'venturescore_model.pkl'}")

    # ── SHAP on a single uncalibrated LightGBM over the same features ──────
    # SHAP is computed on the underlying tree model rather than the
    # calibrated wrapper, because the calibration layer is a monotonic
    # transform of the score and does not change which features drive it.
    # Reported twice on purpose: once on the deployable feature set (what the
    # shipped model actually uses) and once with the contaminated features
    # restored, to show how completely team_size dominates when it is allowed
    # in. The contrast is the clearest single piece of evidence for why it was
    # removed.
    print("\nComputing SHAP feature importance...")
    import shap

    def shap_ranking(numeric: list[str], tag: str) -> list[tuple[str, float]]:
        X, names = build_features(rows, all_idx, numeric, CATEGORICAL, 0)
        model = make_model("lgbm")  # a tree model, for TreeExplainer
        model.fit(X, y)
        values = shap.TreeExplainer(model).shap_values(X)
        if isinstance(values, list):
            values = values[1]
        ranked = sorted(zip(names, np.abs(values).mean(axis=0)), key=lambda t: -t[1])
        print(f"  [{tag}] top 12 by mean |SHAP|:")
        for name, val in ranked[:12]:
            print(f"    {name:34s} {val:.5f}")
        return ranked

    deploy_ranking = shap_ranking(DEPLOY_NUMERIC, "deployable feature set -- SHIPPED")
    print()
    contaminated_ranking = shap_ranking(NUMERIC, "with contaminated features -- NOT shipped")

    (RESEARCH_DIR / "venturescore_feature_importance.json").write_text(
        json.dumps(
            {
                "method": "mean_abs_shap",
                "deployable_feature_set": {
                    "note": "This is the feature set the production model uses.",
                    "ranking": [
                        {"feature": n, "mean_abs_shap": round(float(v), 6)} for n, v in deploy_ranking
                    ],
                },
                "with_contaminated_features": {
                    "note": (
                        "Not shipped. Included to document how far team_size dominates once "
                        "post-outcome features are allowed in."
                    ),
                    "ranking": [
                        {"feature": n, "mean_abs_shap": round(float(v), 6)} for n, v in contaminated_ranking
                    ],
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n  wrote -> {RESEARCH_DIR / 'venturescore_feature_importance.json'}")
    print("\nDone.")


if __name__ == "__main__":
    main()
