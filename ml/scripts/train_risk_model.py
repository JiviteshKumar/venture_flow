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
    """Load Financial PhraseBank + TFNS from their published files directly.

    This previously used datasets.load_dataset() for both corpora. That route
    is dead for a reason unrelated to the network block recorded in earlier
    passes (huggingface.co is reachable now): `datasets` 5.x dropped support
    for script-based datasets, and takala/financial_phrasebank is script-
    based. The underlying data files are still served from the same Hub
    repos, so this fetches them directly -- same corpora, same provenance,
    same licences, one fewer moving part.

    Financial PhraseBank is distributed as a zip of latin-1 encoded text
    files, one line per sentence in "sentence@label" form.
    TFNS ships as plain CSV with integer labels.
    """
    import csv
    import zipfile

    from huggingface_hub import hf_hub_download

    rows: list[dict] = []

    # -- Financial PhraseBank: higher-agreement subsets only, cleaner labels --
    phrasebank_zip = hf_hub_download(
        "takala/financial_phrasebank", "data/FinancialPhraseBank-v1.0.zip", repo_type="dataset"
    )
    wanted = {"Sentences_AllAgree.txt", "Sentences_75Agree.txt"}
    with zipfile.ZipFile(phrasebank_zip) as archive:
        for name in archive.namelist():
            if Path(name).name not in wanted:
                continue
            # latin-1, not utf-8: the corpus predates the convention and
            # contains bytes that are invalid utf-8.
            for line in archive.read(name).decode("latin-1").splitlines():
                if "@" not in line:
                    continue
                sentence, _, label = line.rpartition("@")
                label = label.strip().lower()
                if sentence.strip() and label in ("negative", "neutral", "positive"):
                    rows.append({"text": sentence.strip(), "label": label})

    # -- TFNS: bearish/bullish/neutral -> negative/positive/neutral --
    tfns_map = {0: "negative", 1: "positive", 2: "neutral"}
    for filename in ("sent_train.csv", "sent_valid.csv"):
        path = hf_hub_download(
            "zeroshot/twitter-financial-news-sentiment", filename, repo_type="dataset"
        )
        with open(path, encoding="utf-8", newline="") as handle:
            for record in csv.DictReader(handle):
                try:
                    label = tfns_map[int(record["label"])]
                except (KeyError, ValueError):
                    continue
                text = (record.get("text") or "").strip()
                if text:
                    rows.append({"text": text, "label": label})

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
