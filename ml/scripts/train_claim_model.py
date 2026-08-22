"""
Train the VentureFlow Claim Model.

Requires internet access to huggingface.co (to pull the SciFact dataset).
This cloud build session's network policy blocks that host (PyPI, npm, and
plain github.com file access are allowed; huggingface.co and S3 are not) —
confirmed by direct connection tests, not assumed. This script could not be
run to completion in that session. It's written to be correct and complete
so it runs in one command the moment it's executed somewhere with normal
internet access — your own machine, or a free Colab notebook.

    pip install datasets scikit-learn lightgbm
    python train_claim_model.py

Method: SciFact gives (claim, cited evidence abstract, label) triples where
label is SUPPORT / CONTRADICT / NOT ENOUGH INFO — the exact three-way
schema `agents/claim_verifier.py` already uses (SUPPORTS / REFUTES /
NOT_ENOUGH_INFO). TF-IDF over [claim text ++ evidence text] (see the note in
train_outcome_model.py on why TF-IDF over sentence-transformer embeddings
for this data volume) feeds a multiclass LightGBM classifier. SciFact's
claims are scientific, not startup-pitch claims — expect a real domain gap.
Report accuracy honestly and treat this as a fast first-pass filter ahead
of the existing Groq-based verifier, not a replacement for it: route
low-confidence predictions to Groq, use the trained model directly only
where it's confident. That hybrid is cheaper and just as evidence-grounded,
since Groq stays in the loop for the hard cases.
"""

from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
SEED = 42


def load_scifact_pairs() -> list[dict]:
    from datasets import load_dataset

    claims_ds = load_dataset("allenai/scifact", "claims")
    corpus_ds = load_dataset("allenai/scifact", "corpus")
    corpus_by_id = {str(item["doc_id"]): " ".join(item.get("abstract", [])) for item in corpus_ds["train"]}

    label_map = {"SUPPORT": "SUPPORTS", "CONTRADICT": "REFUTES"}
    rows = []
    for split_name in ["train", "validation"]:
        for item in claims_ds[split_name]:
            label = label_map.get(item.get("label", ""), "NOT_ENOUGH_INFO")
            cited = item.get("cited_doc_ids", []) or []
            evidence_text = " ".join(corpus_by_id.get(str(doc_id), "") for doc_id in cited)
            rows.append({
                "claim": item["claim"],
                "evidence": evidence_text,
                "label": label,
                "split": "dev" if split_name == "validation" else "train",
            })
    return rows


def main() -> None:
    rows = load_scifact_pairs()
    print(f"Loaded {len(rows)} claim/evidence pairs")

    texts = [f"CLAIM: {r['claim']}  EVIDENCE: {r['evidence'][:1500]}" for r in rows]
    label_enc = LabelEncoder().fit([r["label"] for r in rows])
    y = label_enc.transform([r["label"] for r in rows])

    idx = np.arange(len(rows))
    idx_train, idx_test = train_test_split(idx, test_size=0.2, random_state=SEED, stratify=y)

    tfidf = TfidfVectorizer(max_features=30000, ngram_range=(1, 2), min_df=2, stop_words="english")
    tfidf_train = tfidf.fit_transform([texts[i] for i in idx_train])
    tfidf_all = tfidf.transform(texts)
    svd = TruncatedSVD(n_components=200, random_state=SEED)
    svd.fit(tfidf_train)
    X = svd.transform(tfidf_all)

    train_set = lgb.Dataset(X[idx_train], label=y[idx_train])
    params = {
        "objective": "multiclass",
        "num_class": len(label_enc.classes_),
        "metric": "multi_logloss",
        "verbosity": -1,
        "seed": SEED,
        "num_leaves": 31,
        "learning_rate": 0.05,
    }
    booster = lgb.train(params, train_set, num_boost_round=300)

    y_prob = booster.predict(X[idx_test])
    y_pred = np.argmax(y_prob, axis=1)
    report = classification_report(y[idx_test], y_pred, target_names=label_enc.classes_, output_dict=True)
    print(classification_report(y[idx_test], y_pred, target_names=label_enc.classes_))

    booster.save_model(str(MODEL_DIR / "claim_model.txt"))
    import pickle
    with open(MODEL_DIR / "claim_model_encoders.pkl", "wb") as f:
        pickle.dump({"tfidf": tfidf, "svd": svd, "label_encoder": label_enc}, f)
    (MODEL_DIR / "claim_model_report.json").write_text(json.dumps({
        "n_total": len(rows), "n_train": len(idx_train), "n_test": len(idx_test),
        "classification_report": report,
    }, indent=2))
    print("Saved model + report to", MODEL_DIR)


if __name__ == "__main__":
    main()
