"""
Train the VentureFlow Risk/Tone Model.

Same network caveat as train_claim_model.py: needs huggingface.co, which
this build session's sandbox cannot reach (verified, not assumed — PyPI/npm/
plain GitHub work, huggingface.co and S3 return a proxy-level 403). Written
to run correctly in one command anywhere with normal internet access:

    pip install datasets scikit-learn lightgbm
    python train_risk_model.py

Method: combine Financial PhraseBank (analyst-agreement-weighted sentiment)
and TFNS (Twitter financial-news sentiment) into one negative/neutral/
positive tone classifier — TF-IDF + LightGBM, same pattern as the other two
models for consistency and the same reasoning on why TF-IDF over embeddings
at this data volume (see train_outcome_model.py).

Scope honestly: both source datasets are financial *news/analyst* text, not
startup-pitch text — a founder writing "we have no signed customers yet" is
a risk fact stated plainly, not negative-sentiment language. Use this
model's output as one tone/hedging-language signal feeding the risk score
in `agents/risk_detector.py`, not as the whole risk verdict. The keyword
dictionary already in that file stays for the things this model won't
catch (regulatory/legal terms, specific red-flag phrases).
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


def load_sentiment_rows() -> list[dict]:
    from datasets import load_dataset

    rows = []

    configs = ["sentences_allagree", "sentences_75agree"]  # higher-agreement subsets only — cleaner labels
    label_map = {0: "negative", 1: "neutral", 2: "positive"}
    for config in configs:
        ds = load_dataset("takala/financial_phrasebank", config, trust_remote_code=True)
        for item in ds["train"]:
            rows.append({"text": item["sentence"], "label": label_map[item["label"]]})

    tfns_map = {0: "negative", 1: "positive", 2: "neutral"}  # bearish/bullish/neutral -> negative/positive/neutral
    ds = load_dataset("zeroshot/twitter-financial-news-sentiment")
    for split in ["train", "validation"]:
        for item in ds[split]:
            rows.append({"text": item["text"], "label": tfns_map[item["label"]]})

    # de-dup identical text
    seen = set()
    unique = []
    for r in rows:
        if r["text"] not in seen:
            seen.add(r["text"])
            unique.append(r)
    return unique


def main() -> None:
    rows = load_sentiment_rows()
    print(f"Loaded {len(rows)} labeled sentiment examples")

    texts = [r["text"] for r in rows]
    label_enc = LabelEncoder().fit([r["label"] for r in rows])
    y = label_enc.transform([r["label"] for r in rows])

    idx = np.arange(len(rows))
    idx_train, idx_test = train_test_split(idx, test_size=0.15, random_state=SEED, stratify=y)

    tfidf = TfidfVectorizer(max_features=25000, ngram_range=(1, 2), min_df=2, stop_words="english")
    tfidf_train = tfidf.fit_transform([texts[i] for i in idx_train])
    tfidf_all = tfidf.transform(texts)
    svd = TruncatedSVD(n_components=150, random_state=SEED)
    svd.fit(tfidf_train)
    X = svd.transform(tfidf_all)

    train_set = lgb.Dataset(X[idx_train], label=y[idx_train])
    params = {
        "objective": "multiclass", "num_class": 3, "metric": "multi_logloss",
        "verbosity": -1, "seed": SEED, "num_leaves": 31, "learning_rate": 0.05,
    }
    booster = lgb.train(params, train_set, num_boost_round=300)

    y_prob = booster.predict(X[idx_test])
    y_pred = np.argmax(y_prob, axis=1)
    report = classification_report(y[idx_test], y_pred, target_names=label_enc.classes_, output_dict=True)
    print(classification_report(y[idx_test], y_pred, target_names=label_enc.classes_))

    booster.save_model(str(MODEL_DIR / "risk_tone_model.txt"))
    import pickle
    with open(MODEL_DIR / "risk_tone_model_encoders.pkl", "wb") as f:
        pickle.dump({"tfidf": tfidf, "svd": svd, "label_encoder": label_enc}, f)
    (MODEL_DIR / "risk_tone_model_report.json").write_text(json.dumps({
        "n_total": len(rows), "n_train": len(idx_train), "n_test": len(idx_test),
        "classification_report": report,
    }, indent=2))
    print("Saved model + report to", MODEL_DIR)


if __name__ == "__main__":
    main()
