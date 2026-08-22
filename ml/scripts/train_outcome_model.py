"""
Train the VentureFlow Outcome Model.

Method: TF-IDF features over the company description text plus a small set
of engineered structured features, fed into a gradient-boosted tree
classifier (LightGBM).

Note on the text representation: the original plan here was sentence-
transformer embeddings (`all-mpnet-base-v2`, already used elsewhere in this
codebase). This cloud sandbox's network policy allows PyPI, npm, and plain
GitHub file access, but blocks huggingface.co and S3 — so the pretrained
embedding model can't be downloaded here. TF-IDF is a legitimate, fully
offline fallback (no external model download, deterministic, reproducible),
not a lower-quality substitute in principle — for ~1,500 labeled examples it
is a reasonable match for embeddings and in some regimes generalizes better
since it can't silently encode information the base embedding model was
never trained to represent. Swap in sentence-transformer embeddings later by
changing `build_text_features()` once this runs somewhere with full
internet access (a local machine, Colab) — everything downstream is
unaffected. A full transformer fine-tune was deliberately not attempted at
all at this data volume; that would need materially more labeled examples
to outperform a frozen representation + GBM head.

Three variants are trained (the ablation): text-only, structured-only, and
combined — to answer the actual research question, which is *which signal
categories carry real predictive weight*, not just "what's the top-line
accuracy."
"""

from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42


def load_rows() -> list[dict]:
    path = DATA_DIR / "outcome_dataset.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_structured_features(rows: list[dict], industry_enc: LabelEncoder, stage_enc: LabelEncoder) -> np.ndarray:
    industries = industry_enc.transform([r["industry"] for r in rows])
    stages = stage_enc.transform([r["stage"] for r in rows])
    feats = np.column_stack([
        industries,
        stages,
        [r["team_size"] for r in rows],
        [r["num_tags"] for r in rows],
        [int(r["nonprofit"]) for r in rows],
        [r["age_years"] for r in rows],
    ]).astype(float)
    return feats


def evaluate(y_true, y_prob, label: str) -> dict:
    y_pred = (y_prob >= 0.5).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
    metrics = {
        "variant": label,
        "n_test": int(len(y_true)),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, y_prob)), 4),
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
        "brier_score": round(float(brier_score_loss(y_true, y_prob)), 4),
        "baseline_positive_rate": round(float(np.mean(y_true)), 4),
    }
    print(f"[{label}] n={metrics['n_test']} AUC={metrics['roc_auc']} "
          f"acc={metrics['accuracy']} f1={metrics['f1']} brier={metrics['brier_score']} "
          f"(base rate={metrics['baseline_positive_rate']})")
    return metrics


def train_variant(X_train, y_train, X_test, y_test, label: str) -> tuple[dict, lgb.Booster]:
    train_set = lgb.Dataset(X_train, label=y_train)
    params = {
        "objective": "binary",
        "metric": "auc",
        "verbosity": -1,
        "seed": SEED,
        "num_leaves": 15,
        "min_data_in_leaf": 15,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
    }
    booster = lgb.train(params, train_set, num_boost_round=200)
    y_prob = booster.predict(X_test)
    metrics = evaluate(y_test, y_prob, label)
    return metrics, booster


def main() -> None:
    rows = load_rows()
    labels = [r["label"] for r in rows]

    print(f"Loaded {len(rows)} labeled companies "
          f"({sum(labels)} positive / {len(labels) - sum(labels)} negative)")

    texts = [r["text"][:2000] for r in rows]
    y = np.array(labels)
    idx = np.arange(len(rows))
    idx_train, idx_test = train_test_split(idx, test_size=0.2, random_state=SEED, stratify=y)

    # Fit TF-IDF + SVD on the training split only, to avoid leaking test-set
    # vocabulary/structure into the representation before evaluation.
    print("Vectorizing descriptions with TF-IDF + truncated SVD (fit on train only)...")
    tfidf = TfidfVectorizer(max_features=20000, ngram_range=(1, 2), min_df=2, stop_words="english")
    tfidf_train = tfidf.fit_transform([texts[i] for i in idx_train])
    tfidf_all = tfidf.transform(texts)

    svd = TruncatedSVD(n_components=128, random_state=SEED)
    svd.fit(tfidf_train)
    text_features = svd.transform(tfidf_all)
    print(f"  TF-IDF vocab size: {len(tfidf.vocabulary_)}, SVD explained variance: "
          f"{svd.explained_variance_ratio_.sum():.3f}")

    industry_enc = LabelEncoder().fit([r["industry"] for r in rows])
    stage_enc = LabelEncoder().fit([r["stage"] for r in rows])
    structured = build_structured_features(rows, industry_enc, stage_enc)
    scaler = StandardScaler().fit(structured[idx_train])
    structured_scaled = scaler.transform(structured)

    variants = {
        "text_only": text_features,
        "structured_only": structured_scaled,
        "combined": np.hstack([text_features, structured_scaled]),
    }

    all_metrics = []
    boosters = {}
    for name, X in variants.items():
        metrics, booster = train_variant(
            X[idx_train], y[idx_train], X[idx_test], y[idx_test], name
        )
        all_metrics.append(metrics)
        boosters[name] = booster

    # Save the winning (combined) model plus everything needed to run inference later.
    boosters["combined"].save_model(str(MODEL_DIR / "outcome_model_combined.txt"))
    import pickle
    with open(MODEL_DIR / "outcome_model_encoders.pkl", "wb") as f:
        pickle.dump({
            "industry_encoder": industry_enc,
            "stage_encoder": stage_enc,
            "scaler": scaler,
            "tfidf": tfidf,
            "svd": svd,
        }, f)

    # Feature importance for the ablation write-up.
    importance = boosters["combined"].feature_importance(importance_type="gain")
    feature_names = (
        [f"text_svd_{i}" for i in range(text_features.shape[1])]
        + ["industry", "stage", "team_size", "num_tags", "nonprofit", "age_years"]
    )
    structured_importance = {
        name: float(val)
        for name, val in zip(feature_names, importance)
        if not name.startswith("text_svd_")
    }
    text_importance_total = float(sum(
        val for name, val in zip(feature_names, importance) if name.startswith("text_svd_")
    ))

    report = {
        "dataset": {
            "n_total": len(rows),
            "n_train": len(idx_train),
            "n_test": len(idx_test),
            "n_positive": int(sum(labels)),
            "n_negative": len(labels) - int(sum(labels)),
            "min_age_years_filter": 3.5,
        },
        "ablation": all_metrics,
        "combined_model_structured_feature_importance_gain": structured_importance,
        "combined_model_text_feature_importance_gain_total": text_importance_total,
    }
    (MODEL_DIR / "outcome_model_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\nSaved model + report to", MODEL_DIR)
    print(json.dumps(report["ablation"], indent=2))


if __name__ == "__main__":
    main()
