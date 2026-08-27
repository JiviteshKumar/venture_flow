"""Measure retrieval quality before and after the company-scoping fix.

The claim verifier's accuracy was already measured (0.955 on
ml/eval/claim_benchmark.jsonl). What was never measured is the quality of the
evidence it reasons over, and that turned out to be the actual defect:
`build_queries()` received only the claim text, because `verify_claim()` had no
company parameter, so the company name never entered the search query. Across 97
real claims the top domains included merriam-webster.com (6),
dictionary.cambridge.org (3), youtube.com (3) and snopes.com (3).

This harness compares three arms on the same claims:

    legacy   - the five pre-fix templates, no relevance gate
    scoped   - company-anchored queries, no relevance gate
    filtered - company-anchored queries plus agents/evidence_filter

and reports, per arm:

    on_topic_rate   share of retrieved sources that name the company
    noise_rate      share from dictionary / fact-check / video domains
    zero_source     claims for which nothing survived
    unique_domains  breadth of the evidence base

`on_topic_rate` is the headline. Accuracy on a benchmark of famous public claims
can stay high while retrieval is broken, because a well-known fact is verifiable
from almost any page about it; a seed-stage startup is not, and that is the case
the product exists to serve.

Costs NO Groq tokens -- DuckDuckGo only, no LLM judge -- which is why it can be
run repeatedly while the daily token budget is spent on end-to-end deck runs.

    python ml/scripts/eval_retrieval_quality.py
    python ml/scripts/eval_retrieval_quality.py --max-claims 12 --arms legacy filtered
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: F401  (Windows cp1252 guard)
from agents.claim_verifier import build_queries, search_web
from agents.evidence_filter import (
    domain_of,
    filter_sources,
    is_noise_domain,
    mentions_company,
)

DECK_RUNS = ROOT / "ml" / "eval" / "real_deck_runs.json"
OUT_PATH = ROOT / "ml" / "eval" / "retrieval_quality_results.json"


def legacy_queries(claim: str) -> list[str]:
    """The exact pre-fix templates, kept here so the comparison is honest.

    Reproduced verbatim rather than referenced, because the point of an A/B is
    that the control does not move when the treatment is edited.
    """
    return [
        f'"{claim}"',
        f"fact check {claim}",
        f"is it true that {claim}",
        f"{claim} evidence proof",
        f"{claim} false wrong debunked",
    ]


def retrieve(queries: list[str], per_query: int = 5) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for query in queries:
        for result in search_web(query, max_results=per_query):
            url = result.get("url", "")
            if url and url not in seen:
                seen.add(url)
                out.append(result)
    return out


def score_arm(items: list[dict], company: str) -> dict:
    if not items:
        return {"sources": 0, "on_topic": 0, "noise": 0,
                "on_topic_rate": 0.0, "noise_rate": 0.0, "domains": []}
    on_topic = sum(
        1 for i in items
        if mentions_company(company, f"{i.get('title', '')} {i.get('snippet', '')}")
    )
    noise = sum(1 for i in items if is_noise_domain(i.get("url", "")))
    return {
        "sources": len(items),
        "on_topic": on_topic,
        "noise": noise,
        "on_topic_rate": round(on_topic / len(items), 4),
        "noise_rate": round(noise / len(items), 4),
        "domains": [domain_of(i.get("url", "")) for i in items],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-claims", type=int, default=20)
    parser.add_argument("--arms", nargs="*",
                        default=["legacy", "scoped", "filtered"])
    parser.add_argument("--per-query", type=int, default=5)
    args = parser.parse_args()

    if not DECK_RUNS.exists():
        print(f"{DECK_RUNS} not found -- run ml/scripts/run_real_deck_corpus.py first.")
        return 2

    runs = json.loads(DECK_RUNS.read_text(encoding="utf-8"))
    # One claim per deck first, then a second from each, so a single verbose
    # deck cannot dominate the sample.
    pairs: list[tuple[str, str]] = []
    for depth in range(5):
        for run in runs:
            claims = run.get("claims_extracted") or []
            if depth < len(claims):
                pairs.append((run["company"], claims[depth]))
    pairs = pairs[: args.max_claims]

    if not pairs:
        print("No claims found in the deck runs.")
        return 2

    print(f"Measuring {len(pairs)} real deck claims across arms: {', '.join(args.arms)}\n")

    rows = []
    for position, (company, claim) in enumerate(pairs, 1):
        print(f"[{position}/{len(pairs)}] {company}: {claim[:70]}")
        row = {"company": company, "claim": claim, "arms": {}}

        if "legacy" in args.arms:
            items = retrieve(legacy_queries(claim), args.per_query)
            row["arms"]["legacy"] = score_arm(items, company)
            print(f"    legacy   {row['arms']['legacy']['sources']:>3} src  "
                  f"on-topic {row['arms']['legacy']['on_topic_rate']:.0%}  "
                  f"noise {row['arms']['legacy']['noise_rate']:.0%}")

        scoped_items = None
        if "scoped" in args.arms or "filtered" in args.arms:
            scoped_items = retrieve(build_queries(claim, company=company), args.per_query)

        if "scoped" in args.arms:
            row["arms"]["scoped"] = score_arm(scoped_items, company)
            print(f"    scoped   {row['arms']['scoped']['sources']:>3} src  "
                  f"on-topic {row['arms']['scoped']['on_topic_rate']:.0%}  "
                  f"noise {row['arms']['scoped']['noise_rate']:.0%}")

        if "filtered" in args.arms:
            kept, dropped = filter_sources(
                scoped_items or [],
                context=f"{company} {claim}",
                company=company,
            )
            scored = score_arm(kept, company)
            scored["dropped"] = len(dropped)
            row["arms"]["filtered"] = scored
            print(f"    filtered {scored['sources']:>3} src  "
                  f"on-topic {scored['on_topic_rate']:.0%}  "
                  f"noise {scored['noise_rate']:.0%}  "
                  f"(dropped {len(dropped)})")

        rows.append(row)
        time.sleep(1.0)  # a free public endpoint; do not hammer it

    summary = {}
    for arm in args.arms:
        arm_rows = [r["arms"][arm] for r in rows if arm in r["arms"]]
        total_sources = sum(a["sources"] for a in arm_rows)
        total_on_topic = sum(a["on_topic"] for a in arm_rows)
        total_noise = sum(a["noise"] for a in arm_rows)
        domains = Counter(d for a in arm_rows for d in a["domains"] if d)
        summary[arm] = {
            "claims": len(arm_rows),
            "total_sources": total_sources,
            "sources_per_claim": round(total_sources / max(1, len(arm_rows)), 2),
            "on_topic_rate": round(total_on_topic / total_sources, 4) if total_sources else 0.0,
            "noise_rate": round(total_noise / total_sources, 4) if total_sources else 0.0,
            "claims_with_zero_sources": sum(1 for a in arm_rows if a["sources"] == 0),
            "claims_with_zero_on_topic": sum(1 for a in arm_rows if a["on_topic"] == 0),
            "unique_domains": len(domains),
            "top_domains": domains.most_common(12),
        }

    print("\n" + "=" * 72)
    print(f"{'arm':<10} {'src/claim':>10} {'on-topic':>10} {'noise':>8} "
          f"{'0-src':>7} {'0-ontopic':>10}")
    for arm, s in summary.items():
        print(f"{arm:<10} {s['sources_per_claim']:>10.1f} {s['on_topic_rate']:>9.1%} "
              f"{s['noise_rate']:>7.1%} {s['claims_with_zero_sources']:>7} "
              f"{s['claims_with_zero_on_topic']:>10}")

    for arm, s in summary.items():
        print(f"\n{arm} top domains: "
              + ", ".join(f"{d}({n})" for d, n in s["top_domains"][:8]))

    OUT_PATH.write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8"
    )
    print(f"\nWrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
