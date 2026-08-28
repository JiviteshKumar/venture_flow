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

# Set from the measured distribution of genuine in-corpus matches: across 40
# real company descriptions the second-best similarity ran min 0.536, p25
# 0.642, median 0.698. Sitting just under that floor keeps real matches and
# drops the detached tail.
MIN_SIMILARITY = 0.50
POPULATION_N = 1560
SOURCE = "1,560 Y Combinator companies (yc-oss/api), TF-IDF+SVD text similarity"

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

        # A floor, so the tab can return fewer than `top_k` -- including none.
        #
        # It previously returned exactly five rows for every query, however
        # distant, which presents "the nearest things in a 1,560-company corpus"
        # as though it meant "these are comparable companies".
        #
        # The threshold is set from measurement, not taste. Across 40 real
        # in-corpus descriptions the second-best similarity (excluding the
        # company itself) ran min 0.536, p25 0.642, median 0.698. MIN_SIMILARITY
        # sits just below that floor so genuine company-to-company matches
        # survive and the unrelated tail does not.
        #
        # WHAT THIS THRESHOLD HONESTLY DOES NOT DO, measured directly:
        # cosine similarity on this TF-IDF+SVD embedder does not separate
        # relevant from irrelevant. "A commercial laundry servicing hotels in
        # the Midwest" scores 0.827 against this corpus -- HIGHER than "an AI
        # developer tools platform that automates code review" at 0.760. The
        # embedder measures lexical overlap, not whether two businesses are
        # actually alike. So this filter removes the clearly-detached tail and
        # must not be described as a relevance guarantee; the caveat below says
        # so in the words a reader will see.
        order = np.argsort(-similarities)
        top_indices = [i for i in order[:top_k] if float(similarities[i]) >= MIN_SIMILARITY]
        n_below = int(top_k - len(top_indices))

        if not top_indices:
            best = float(similarities[order[0]]) if len(order) else 0.0
            return {
                "available": True,
                "comparables": [],
                "no_close_matches": True,
                "best_similarity": round(best, 3),
                "threshold": MIN_SIMILARITY,
                "source": SOURCE,
                "caveat": (
                    f"No close comparables found. The nearest company in the "
                    f"{POPULATION_N:,}-company Y Combinator corpus scored "
                    f"{best:.2f} similarity, below the {MIN_SIMILARITY} floor, so "
                    f"nothing is shown rather than presenting distant matches as "
                    f"though they were comparable. This is the expected result for "
                    f"a company with no YC analogue."
                ),
            }

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
            "source": SOURCE,
            "no_close_matches": False,
            "threshold": MIN_SIMILARITY,
            "n_below_threshold": n_below,
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
                "guidance.\n\nSIMILARITY IS LEXICAL, NOT SEMANTIC. Measured on this "
                "corpus, the description \"a commercial laundry servicing hotels\" "
                "scores 0.83 while \"an AI developer tools platform\" scores 0.76 -- "
                "so a high similarity number does NOT establish that two businesses "
                "are alike. The score reflects shared wording. Read the company "
                "names and judge for yourself; do not read the percentage as a "
                "measure of relevance."
            ),
        }
    except Exception:
        logger.exception("Comparable-company search failed")
        return {"available": False, "reason": "Comparable-company search raised an unexpected error."}
