"""Text embeddings for real vector retrieval (pgvector) -- see
migrations/006_pgvector_retrieval.sql and rag_engine.py.

Backed by the TF-IDF+SVD embedder trained in
ml/scripts/train_text_embedder.py; that script's docstring explains why
TF-IDF+SVD rather than a pretrained sentence-transformer (the same honest
substitution already made for the Outcome Model, for the same reason --
huggingface.co has been blocked in every build sandbox used on this project
so far).

`embed_text()` returns None, not a zero vector, when the embedder isn't
available -- callers must treat that as "fall back to keyword search," never
as a valid embedding.
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parent / "ml" / "models" / "text_embedder.pkl"
DIMENSIONS = 64

_state: dict | None = None
_load_attempted = False


def _load() -> dict | None:
    global _state, _load_attempted
    if _load_attempted:
        return _state
    _load_attempted = True
    try:
        with open(MODEL_PATH, "rb") as f:
            _state = pickle.load(f)
    except Exception as exc:
        logger.info("Text embedder not available (%s) -- vector retrieval will fall back to keyword search.", exc)
        _state = None
    return _state


def is_available() -> bool:
    return _load() is not None


def embed_text(text: str) -> list[float] | None:
    """Never raises. Returns a fixed-length embedding, or None if the
    embedder isn't trained/loadable or `text` is empty."""
    state = _load()
    if state is None or not text or not text.strip():
        return None
    try:
        vector = state["svd"].transform(state["tfidf"].transform([text[:4000]]))[0]
        return [float(x) for x in vector]
    except Exception:
        logger.exception("Text embedding failed")
        return None
