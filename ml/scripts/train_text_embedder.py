"""Fits a general-purpose startup-domain text embedder (TF-IDF -> TruncatedSVD)
on the same YC company corpus used to train the Outcome Model
(ml/data/outcome_dataset.jsonl, ~1,560 companies).

Why this exists: real vector retrieval (pgvector, e1 on the Ship List) needs
fixed-length embeddings for company descriptions/report summaries. A
pretrained sentence-transformer would be the usual choice, but this project's
build sandboxes have consistently blocked huggingface.co (see ml/README.md).
TF-IDF+SVD is the same honest substitution already made for the Outcome
Model, applied here too: fully offline, deterministic, and a reasonable
match for retrieval over pitch-deck-style text at this corpus size. Swapping
in real sentence embeddings later is a one-file change (this script plus
embeddings.py's `embed_text`), same as documented for the Outcome Model.

Usage:
    python ml/scripts/train_text_embedder.py
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "ml" / "data" / "outcome_dataset.jsonl"
OUT_PATH = ROOT / "ml" / "models" / "text_embedder.pkl"
DIMENSIONS = 64


def main() -> None:
    texts = []
    with open(DATA_PATH) as f:
        for line in f:
            row = json.loads(line)
            text = (row.get("text") or "").strip()
            if text:
                texts.append(text)

    print(f"Fitting on {len(texts)} company descriptions...")
    tfidf = TfidfVectorizer(max_features=20000, ngram_range=(1, 2), min_df=2, stop_words="english")
    tfidf_matrix = tfidf.fit_transform(texts)

    svd = TruncatedSVD(n_components=DIMENSIONS, random_state=13)
    svd.fit(tfidf_matrix)

    explained = round(float(svd.explained_variance_ratio_.sum()), 3)
    print(f"Explained variance ({DIMENSIONS} dims): {explained}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "wb") as f:
        pickle.dump({
            "tfidf": tfidf, "svd": svd, "dimensions": DIMENSIONS,
            "trained_on": f"{len(texts)} YC company descriptions (yc-oss/api)",
            "explained_variance_ratio": explained,
        }, f)
    print(f"Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
