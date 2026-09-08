"""Real comparable-company benchmarking, across more than one accelerator.

WHAT CHANGED AND WHY

This used to search 1,560 Y Combinator companies and nothing else, and said so
in a caveat headed "YC-ONLY POPULATION". That caveat was honest, and it was
also a description of a real defect: a startup with no YC analogue still got
five YC rows back, because the search always returns its closest available
matches however distant they are. Companies that never went near an accelerator
succeed and fail too, and a comp set drawn from one portfolio answers "what is
the nearest YC company" when the user asked "what is the nearest company".

The search now covers two populations:

    Y Combinator   5,133 technology companies from yc-oss/api, with a GRADED
                   outcome (ml/scripts/build_yc_comparables_corpus.py)
    Market-wide      470 technology companies with a recorded outcome, from
                     Wikidata + Wikipedia (ml/scripts/build_market_company_dataset.py)

WHY THE OUTCOMES ARE GRADED, AND WHY THE YC CORPUS TRIPLED

The YC half used to be the model's TRAINING dataset, which keeps only companies
whose outcome resolved to one of two classes: exited, or shut down. Every
company still trading was absent -- and that is 70% of them. So the table showed
30% of the population and implied that a company like yours either exits or
dies, when by far the most likely outcome is that it keeps operating without
either.

It also rendered a modest acquihire and a fund-returning IPO with the same two
words, "Acquired/Public".

Both are now fixed. The YC corpus is built for display rather than training and
carries four tiers:

    Shut down            792   15.4%
    Still operating    3,594   70.0%
    Exit                 672   13.1%
    Outsized outcome      75    1.5%   (Y Combinator's own "top company" flag)

That last tier is REPORTED, never predicted -- see the build script for the
measurement. Ranked within a single YC batch so age cannot inflate it, an
outsized outcome is not separable from a quiet survivor or an ordinary exit
(AUC 0.5892, CI [0.5079, 0.6867]); and among exits, description length alone
scores 0.6354, which is profile-maintenance bias rather than a property of the
company. Showing a VC that three of five comparables quietly kept operating is
useful. Telling them their company has a 1.5% chance of being the next Stripe
would be a number nothing here can support.

WHY THE RESULTS ARE STRATIFIED RATHER THAN MERGED

Merging the two corpora and taking the overall top five does not work, and this
was measured before it was designed around. Across five probe queries in the
style the product actually sends, the merged top five came back 24 of 25 rows
from Y Combinator. The reason is genre, not relevance: the embedder is a
TF-IDF+SVD model fitted on YC's own text, so it scores YC's pitch register ("We
make it easy to...") far above encyclopedia register ("X was a British Internet
service provider..."), whatever the businesses actually are.

So a naive merge would have added a second population to the data and left the
output almost exactly as YC-only as before, while letting the caveat claim
otherwise. Instead the two populations are searched SEPARATELY and both are
shown, each labelled. The user asked to see companies outside YC; the only way
to be sure they do is to reserve them a place.

WHAT THE SIMILARITY NUMBER STILL DOES NOT MEAN

Unchanged from before, and it matters more now that there are two populations:
cosine similarity on this embedder measures lexical overlap, not whether two
businesses are alike. Measured on this corpus, "a commercial laundry servicing
hotels in the Midwest" scores 0.78 against its nearest match while "an AI
developer tools platform that automates code review" scores 0.84 -- the numbers
are in the same range for a query that has a real analogue and one that does
not. Read the company names and judge for yourself.

And because the embedder favours YC's register, a similarity of 0.62 against a
market-wide row is NOT worse evidence than 0.68 against a YC row. The two
columns are not on one scale. That is stated in the caveat the user reads.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent / "ml" / "data"
YC_PATH = _DATA_DIR / "yc_comparables.jsonl"
MARKET_PATH = _DATA_DIR / "market_dataset.jsonl"

# Re-measured on the combined corpus rather than carried over. Second-best
# similarity across 200 probes: YC alone ran min 0.498 / p25 0.638 / median
# 0.706; combined ran min 0.498 / p25 0.652 / median 0.737. The distribution
# barely moved, so the floor set for the YC corpus still sits just under the
# genuine-match band and 0.50 stands.
MIN_SIMILARITY = 0.50

POPULATIONS = {
    "yc": {
        "label": "Y Combinator alumni",
        "path": YC_PATH,
        "source": "yc-oss/api",
        "url": "https://github.com/yc-oss/api",
        "note": (
            "Accelerator-backed, mostly US, mostly 2012 onwards. Includes "
            "companies still operating with no exit, which are 70% of the "
            "population and were previously absent from this table."
        ),
    },
    "market": {
        "label": "Market-wide (non-accelerator)",
        "path": MARKET_PATH,
        "source": "Wikidata (CC0) + English Wikipedia (CC BY-SA)",
        "url": "https://www.wikidata.org/",
        "note": (
            "Technology companies founded 1990-2020 with an outcome recorded in "
            "public reference data. Covers companies notable enough for an "
            "encyclopedia entry, so quiet early failures are under-represented."
        ),
    },
}

_corpus: dict[str, list[dict]] = {}
_embeddings: dict[str, Any] = {}
_load_attempted = False


def _load() -> None:
    global _load_attempted
    if _load_attempted:
        return
    _load_attempted = True
    try:
        import numpy as np

        from embeddings import embed_text, is_available

        if not is_available():
            return

        for key, meta in POPULATIONS.items():
            path = meta["path"]
            if not path.exists():
                logger.info("Comparables: %s corpus missing at %s", key, path)
                continue
            rows, vectors = [], []
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    vector = embed_text(row.get("text", ""))
                    if vector is not None:
                        rows.append(row)
                        vectors.append(vector)
            if rows:
                _corpus[key] = rows
                _embeddings[key] = np.array(vectors)
                logger.info("Comparables: loaded %d rows from %s", len(rows), key)
    except Exception:
        logger.exception("Comparable-company corpus failed to load")
        _corpus.clear()
        _embeddings.clear()


# What the market corpus's binary label means in the YC corpus's graded terms,
# so one column can describe both populations without flattening the YC tiers
# back into the binary they were built to escape.
_MARKET_OUTCOME = {
    1: ("exit", "Exit"),
    0: ("shut_down", "Shut down"),
}


def _row_to_comparable(row: dict, similarity: float, population: str) -> dict:
    """One result row, in a shape that is the same for both populations.

    The outcome is GRADED for YC rows, because "Acquired/Public" rendered a
    modest acquihire and a fund-returning IPO with the same two words, and
    because the table previously could not show a company that simply kept
    operating -- the outcome 70% of them actually had.

    The market corpus has no equivalent grading available (there is no free
    source of exit values), so its rows carry the binary tiers only. A row never
    claims a grade its source cannot support.

    `source_url` is a permalink a reader can open: the YC directory page, or the
    Wikidata item the outcome was read from.
    """
    if population == "market":
        key, label = _MARKET_OUTCOME.get(row.get("label"), ("unknown", "Unknown"))
        tier = 2 if row.get("label") == 1 else 0
    else:
        key = row.get("outcome_key") or "unknown"
        label = row.get("outcome") or "Unknown"
        tier = row.get("outcome_tier")

    return {
        "name": row.get("name"),
        "industry": row.get("industry") or "",
        "stage": row.get("stage") or "",
        "batch": row.get("batch") or "",
        "founded_year": row.get("founded_year") or row.get("batch_year"),
        "outcome": label,
        "outcome_key": key,
        "outcome_tier": tier,
        "outcome_basis": row.get("label_reason", ""),
        "similarity": round(similarity, 3),
        "population": population,
        "population_label": POPULATIONS[population]["label"],
        "source_url": row.get("source_url", ""),
    }


def _search_one(population: str, query_vec, top_k: int) -> tuple[list[dict], float]:
    """(rows above the floor, best similarity seen) for one population."""
    import numpy as np

    matrix = _embeddings.get(population)
    rows = _corpus.get(population)
    if matrix is None or not rows:
        return [], 0.0

    corpus_norms = np.linalg.norm(matrix, axis=1)
    query_norm = np.linalg.norm(query_vec)
    similarities = (matrix @ query_vec) / (corpus_norms * query_norm + 1e-9)

    order = np.argsort(-similarities)
    best = float(similarities[order[0]]) if len(order) else 0.0
    chosen = [
        _row_to_comparable(rows[int(i)], float(similarities[i]), population)
        for i in order[:top_k]
        if float(similarities[i]) >= MIN_SIMILARITY
    ]
    return chosen, best


def _outcome_rates() -> dict[str, Any]:
    """How often each outcome actually happens, across the whole YC population.

    This exists to correct a number the product states elsewhere. The score
    model reports a base rate of 48.9%, which is the share of exits among
    companies that had ALREADY either exited or shut down -- its training set
    excludes the 70% still operating. Read as "how often does a company like
    this exit", 48.9% overstates it by more than three times.

    Both numbers are correct about different questions. Only this one answers
    the question a reader of a comparables table is actually asking.
    """
    rows = _corpus.get("yc") or []
    if not rows:
        return {}
    counts: dict[str, int] = {}
    for row in rows:
        key = row.get("outcome_key") or "unknown"
        counts[key] = counts.get(key, 0) + 1
    total = len(rows)
    exits = counts.get("exit", 0) + counts.get("outsized", 0)
    return {
        "population": "Y Combinator technology companies",
        "n": total,
        "counts": counts,
        "rates": {key: round(value / total, 4) for key, value in counts.items()},
        "exit_rate": round(exits / total, 4),
        "outsized_rate": round(counts.get("outsized", 0) / total, 4),
        "note": (
            f"Across {total:,} Y Combinator technology companies, "
            f"{counts.get('operating', 0) / total:.0%} are still operating with no "
            f"exit, {exits / total:.0%} exited, and "
            f"{counts.get('outsized', 0) / total:.1%} became one of YC's top "
            f"companies. The score model's {0.489:.0%} base rate is a different "
            f"figure: it is the share of exits among companies that had already "
            f"exited or shut down, and excludes everything still operating."
        ),
    }


def find_comparables(description: str, top_k: int = 6) -> dict[str, Any]:
    """Never raises. Returns a dict with `available`; when True, also
    `comparables` (real companies with outcomes, drawn from both populations
    and each labelled with which), plus `by_population`, `population` and
    `caveat`.

    `top_k` is split between the populations rather than pooled, so a non-YC
    company is shown whenever one clears the similarity floor. See the module
    docstring: pooling produced 24 of 25 rows from YC across five probe
    queries, for reasons of text genre rather than relevance.
    """
    _load()
    if not description or not description.strip():
        return {"available": False,
                "reason": "No company description to compare against."}
    if not _corpus:
        return {"available": False,
                "reason": "Comparable-company data or the text embedder isn't available."}

    try:
        import numpy as np

        from embeddings import embed_text

        query_vec = embed_text(description)
        if query_vec is None:
            return {"available": False,
                    "reason": "Could not embed the provided description."}
        query_vec = np.array(query_vec)

        # An even split, with the remainder going to whichever population has
        # more to offer -- the loop below refills from the other side when one
        # returns fewer than its share.
        per_population = max(1, top_k // max(1, len(_corpus)))
        results: dict[str, list[dict]] = {}
        best: dict[str, float] = {}
        for key in POPULATIONS:
            if key not in _corpus:
                continue
            # Search deeper than the quota so the refill below has candidates.
            found, best_seen = _search_one(key, query_vec, top_k)
            results[key] = found
            best[key] = round(best_seen, 3)

        selected: list[dict] = []
        for key, found in results.items():
            selected.extend(found[:per_population])
        # Refill any unused places from whichever population still has matches,
        # so a query with no non-YC analogue still returns a full set rather
        # than a short one.
        if len(selected) < top_k:
            already = {(row["population"], row["name"]) for row in selected}
            leftovers = [
                row for found in results.values() for row in found
                if (row["population"], row["name"]) not in already
            ]
            leftovers.sort(key=lambda r: -r["similarity"])
            selected.extend(leftovers[: top_k - len(selected)])

        selected.sort(key=lambda r: -r["similarity"])

        population_block = {
            key: {
                "label": meta["label"],
                "n": len(_corpus.get(key, [])),
                "source": meta["source"],
                "url": meta["url"],
                "note": meta["note"],
                "matches_above_floor": len(results.get(key, [])),
                "best_similarity": best.get(key, 0.0),
            }
            for key, meta in POPULATIONS.items()
        }
        total = sum(len(rows) for rows in _corpus.values())

        if not selected:
            overall_best = max(best.values()) if best else 0.0
            return {
                "available": True,
                "comparables": [],
                "by_population": {k: [] for k in results},
                "no_close_matches": True,
                "best_similarity": overall_best,
                "threshold": MIN_SIMILARITY,
                "population": population_block,
                "caveat": (
                    f"No close comparables found in either population. The nearest "
                    f"company across all {total:,} scored {overall_best:.2f} "
                    f"similarity, below the {MIN_SIMILARITY} floor, so nothing is "
                    f"shown rather than presenting distant matches as though they "
                    f"were comparable."
                ),
            }

        return {
            "available": True,
            "comparables": selected,
            "by_population": {
                key: found[:per_population] for key, found in results.items()
            },
            "no_close_matches": False,
            "threshold": MIN_SIMILARITY,
            "population": population_block,
            "population_total": total,
            "outcome_rates": _outcome_rates(),
            "caveat": (
                f"TWO POPULATIONS, SHOWN SEPARATELY. These are the nearest matches "
                f"among {total:,} companies with a publicly recorded outcome: "
                f"{len(_corpus.get('yc', [])):,} Y Combinator alumni and "
                f"{len(_corpus.get('market', [])):,} technology companies from "
                f"public reference data that did not go through an accelerator. "
                f"Places are reserved for each population rather than pooled, "
                f"because the text embedder was fitted on YC's own writing and a "
                f"pooled ranking returned 24 of 25 rows from YC for reasons of "
                f"writing style rather than business similarity.\n\n"
                f"DO NOT COMPARE THE TWO SIMILARITY COLUMNS. For the same reason, "
                f"a 0.62 against a market-wide company is not weaker evidence than "
                f"a 0.68 against a YC company; they are not on one scale.\n\n"
                f"SIMILARITY IS LEXICAL, NOT SEMANTIC. Measured on this corpus, "
                f"\"a commercial laundry servicing hotels\" scores 0.78 against its "
                f"nearest match and \"an AI developer tools platform\" scores 0.84 "
                f"-- so a high number does NOT establish that two businesses are "
                f"alike. Read the company names and judge for yourself; treat "
                f"these as leads to look into, not as validated comparables or "
                f"valuation guidance.\n\n"
                f"WHAT THE OUTCOME COLUMN MEANS. 'Still operating' is a real "
                f"outcome and the most common one -- 70% of the Y Combinator "
                f"population. 'Outsized outcome' is Y Combinator's own flag for "
                f"its top companies, an editorial judgement rather than a "
                f"financial figure; there is no free source of exit values, so "
                f"an 'Exit' covers everything from an acquihire to a large sale.\n\n"
                f"WHAT IS STILL MISSING. The market-wide corpus covers companies "
                f"notable enough for an encyclopedia entry, so startups that "
                f"failed quietly and early are under-represented in it. Neither "
                f"population is a market census."
            ),
        }
    except Exception:
        logger.exception("Comparable-company search failed")
        return {"available": False,
                "reason": "Comparable-company search raised an unexpected error."}
