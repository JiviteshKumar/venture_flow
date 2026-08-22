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


SCIFACT_URL = "https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_scifact_pairs() -> list[dict]:
    """Load SciFact directly from AllenAI's published tarball.

    This used to call datasets.load_dataset("allenai/scifact", ...). Two
    separate things have since broken that route, and both were found by
    running it rather than assuming:

      1. The historical blocker recorded in earlier passes -- huggingface.co
         unreachable from the build sandbox -- no longer applies. The Hub is
         reachable now.
      2. A new one took its place: `datasets` 5.x removed support for
         script-based datasets ("Dataset scripts are no longer supported"),
         and allenai/scifact is script-based. Its Hub repo contains only
         README.md, dataset_infos.json and scifact.py -- there are no data
         files and no auto-converted parquet branch to fall back to.

    The script's own source URL, however, is plain S3 and is reachable, so
    this reads the tarball directly. That removes the dependency on Hub
    script support entirely, which is the more durable arrangement anyway:
    this loader now depends only on a static file being served.
    """
    import io
    import tarfile
    import urllib.request

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cached = DATA_DIR / "scifact_data.tar.gz"
    if not cached.exists():
        print(f"Downloading SciFact from {SCIFACT_URL} ...")
        with urllib.request.urlopen(SCIFACT_URL, timeout=120) as response:
            cached.write_bytes(response.read())
    print(f"Using SciFact tarball at {cached} ({cached.stat().st_size:,} bytes)")

    members: dict[str, list[dict]] = {}
    with tarfile.open(cached, "r:gz") as tar:
        for member in tar.getmembers():
            name = Path(member.name).name
            if not name.endswith(".jsonl"):
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            text = io.TextIOWrapper(handle, encoding="utf-8")
            members[name] = [json.loads(line) for line in text if line.strip()]

    corpus_by_id = {
        str(doc["doc_id"]): " ".join(doc.get("abstract", []))
        for doc in members.get("corpus.jsonl", [])
    }
    if not corpus_by_id:
        raise RuntimeError(f"SciFact corpus not found in tarball; saw {sorted(members)}")

    # SciFact encodes the label inside `evidence`: a claim with no evidence
    # entry for any cited doc is NOT_ENOUGH_INFO, otherwise the per-document
    # entry carries SUPPORT or CONTRADICT.
    label_map = {"SUPPORT": "SUPPORTS", "CONTRADICT": "REFUTES"}
    rows: list[dict] = []
    for split_file, split in (("claims_train.jsonl", "train"), ("claims_dev.jsonl", "dev")):
        for item in members.get(split_file, []):
            evidence_map = item.get("evidence") or {}
            cited = [str(d) for d in (item.get("cited_doc_ids") or [])]
            if evidence_map:
                labels = {
                    entry.get("label")
                    for entries in evidence_map.values()
                    for entry in entries
                }
                label = next(
                    (label_map[raw] for raw in ("CONTRADICT", "SUPPORT") if raw in labels),
                    "NOT_ENOUGH_INFO",
                )
                doc_ids = [str(d) for d in evidence_map] or cited
            else:
                label = "NOT_ENOUGH_INFO"
                doc_ids = cited
            evidence_text = " ".join(corpus_by_id.get(doc_id, "") for doc_id in doc_ids)
            if not evidence_text.strip():
                continue
            rows.append({
                "claim": item["claim"],
                "evidence": evidence_text,
                "label": label,
                "split": split,
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
