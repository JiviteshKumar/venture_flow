"""Real comparable-company benchmarking.

Replaces trigram name/domain matching against your own report history
(`db.find_similar_companies`, which stays as a complementary signal -- "have
I looked at something like this before" is still useful) with similarity
search over an independent, real dataset: the same 1,560 Y Combinator
companies used to train the Outcome Model (`ml/data/outcome_dataset.jsonl`,
pulled from `yc-oss/api`). Addresses the "replaces trigram matching with an
actual market-data source" ship-list item -- "actual market-data source"
here means real companies with real recorded outcomes, not a paid
Crunchbase/PitchBook feed (see `market_data.py` for the path to one of
those).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_PATH = Path(__file__).resolve().parent / "ml" / "data" / "outcome_dataset.jsonl"

_corpus: list[dict] | None = None
_corpus_embeddings = None
_load_attempted = False


def _load() -> None:
    global _corpus, _corpus_embeddings, _load_attempted
    if _load_attempted:
        return
    _load_attempted = True
    try:
        import numpy as np

        from embeddings import embed_text, is_available

        if not is_available() or not DATA_PATH.exists():
            return

        rows, vectors = [], []
        with open(DATA_PATH) as f:
            for line in f:
                row = json.loads(line)
                vec = embed_text(row.get("text", ""))
                if vec is not None:
                    rows.append(row)
                    vectors.append(vec)
        if rows:
            _corpus = rows
            _corpus_embeddings = np.array(vectors)
    except Exception:
        logger.exception("Comparable-company corpus failed to load")
        _corpus = None


def find_comparables(description: str, top_k: int = 5) -> dict[str, Any]:
    """Never raises. Returns a dict with `available`; when True, also
    `comparables` (a list of real companies with name/industry/stage/
    outcome/similarity) and `source`/`caveat` strings."""
    _load()
    if not description or not description.strip():
        return {"available": False, "reason": "No company description to compare against."}
    if _corpus is None or _corpus_embeddings is None:
        return {"available": False, "reason": "Comparable-company data or the text embedder isn't available."}

    try:
        import numpy as np

        from embeddings import embed_text

        query_vec = embed_text(description)
        if query_vec is None:
            return {"available": False, "reason": "Could not embed the provided description."}

        query_vec = np.array(query_vec)
        corpus_norms = np.linalg.norm(_corpus_embeddings, axis=1)
        query_norm = np.linalg.norm(query_vec)
        similarities = (_corpus_embeddings @ query_vec) / (corpus_norms * query_norm + 1e-9)

        top_indices = np.argsort(-similarities)[:top_k]
        comparables = []
        for idx in top_indices:
            row = _corpus[int(idx)]
            comparables.append({
                "name": row.get("name"),
                "industry": row.get("industry"),
                "stage": row.get("stage"),
                "batch": row.get("batch"),
                "outcome": "Acquired/Public" if row.get("label") == 1 else "Shut down",
                "similarity": round(float(similarities[idx]), 3),
            })

        return {
            "available": True,
            "comparables": comparables,
            "source": "1,560 Y Combinator companies (yc-oss/api), TF-IDF+SVD text similarity",
            # Stated as a first-class field, not buried at the end of a
            # footnote. "Why these five companies" deserves an answer a reader
            # can act on, and the honest answer is that the search space is one
            # accelerator's portfolio -- so a company with no YC analogue gets
            # the nearest YC company regardless of how far away that is.
            "population": {
                "name": "Y Combinator alumni with a recorded outcome",
                "n": 1560,
                "universe": "yc-oss/api, 6,194 YC companies total",
                "labelled_available": 1903,
                "coverage_of_labelled": 0.82,
                "excluded": (
                    "4,291 YC companies are still Active and therefore have no "
                    "outcome to compare against; the remaining ~343 labelled "
                    "companies fall outside this product's tech-startup scope or "
                    "carry no usable description text."
                ),
                "not_included": (
                    "Non-YC startups of any kind. No accelerator-independent, "
                    "European, Asian, bootstrapped or later-stage population is "
                    "represented."
                ),
                "why_not_broader": (
                    "Crunchbase's API returns 401 without a paid licence and its "
                    "free Open Data Map is no longer published; the startup "
                    "datasets on public model hubs are unattributed third-party "
                    "scrapes with no verifiable provenance. Broadening this "
                    "population is a budget item, not an engineering one."
                ),
            },
            "caveat": (
                "YC-ONLY POPULATION. These are the nearest matches among 1,560 Y "
                "Combinator companies -- not the nearest companies in the market. "
                "A startup with no YC analogue still gets five rows here, because "
                "the search always returns its closest available matches however "
                "distant they are. It is also a text-similarity match over "
                "descriptions, not a market-data-verified comp set: treat these "
                "as leads to look into, not as validated comparables or valuation "
                "guidance."
            ),
        }
    except Exception:
        logger.exception("Comparable-company search failed")
        return {"available": False, "reason": "Comparable-company search raised an unexpected error."}
