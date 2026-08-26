"""Does the headline score actually discriminate between companies?

This exists because of a measured product failure, not as a generic stats
utility. Across the stored reports it was found that **18 of 40 different
startups had scored an identical 30.0**, because `run_due_diligence` ended with
`final_score = min(final_score, 30)` whenever the specialist agents all returned
confidence 0 or no claim was extractable -- and 19 of the 20 capped reports were
capped purely because Groq had returned 429 to all four agents. An exhausted API
quota was being published as a verdict on the company.

The single number that matters here is therefore not the mean or the standard
deviation. It is **the size of the largest cluster of identical scores**. A
scoring system can have a perfectly healthy standard deviation while still
mapping a third of its inputs onto one constant, and that constant is what a
user actually sees.

Run:
    python ml/scripts/check_score_distribution.py
    python ml/scripts/check_score_distribution.py --source ml/eval/deck_runs/*.json

Reports nothing it did not read. If the database is unreachable it says so and
exits non-zero rather than printing a distribution of nothing.
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import console_safety  # noqa: F401  (Windows cp1252 guard -- see FIELD_NOTES)


def _from_db(limit: int) -> list[tuple[str, float, str]]:
    import db

    if not db.healthcheck():
        print("Database unreachable -- refusing to report a distribution I did not read.")
        raise SystemExit(2)
    rows = db.list_reports(limit=limit)
    return [
        (r["company"], float(r["final_score"]), r.get("recommendation", "?"))
        for r in rows
        if r.get("final_score") is not None
    ]


def _from_files(patterns: list[str]) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"  skipped {path}: {exc}")
                continue
            reports = data if isinstance(data, list) else [data]
            for report in reports:
                if not isinstance(report, dict) or report.get("final_score") is None:
                    continue
                out.append((
                    report.get("company_name") or report.get("company") or Path(path).stem,
                    float(report["final_score"]),
                    report.get("recommendation", "?"),
                ))
    return out


def summarise(rows: list[tuple[str, float, str]], label: str) -> dict:
    scores = [s for _, s, _ in rows]
    n = len(scores)
    if n == 0:
        print(f"{label}: no scores found.")
        return {}

    counts = Counter(scores)
    top_value, top_count = counts.most_common(1)[0]
    distinct = len(counts)
    ordered = sorted(scores)

    print(f"\n=== {label} ===")
    print(f"n reports            : {n}")
    print(f"distinct scores      : {distinct}  ({distinct / n:.0%} of n)")
    print(f"range                : {min(scores):.1f} - {max(scores):.1f}")
    print(f"mean / median        : {statistics.mean(scores):.1f} / {statistics.median(scores):.1f}")
    if n > 1:
        print(f"standard deviation   : {statistics.stdev(scores):.1f}")
    print(f"LARGEST IDENTICAL CLUSTER: {top_count} reports all scoring {top_value:.1f} "
          f"({top_count / n:.0%} of all reports)")

    if n >= 10:
        deciles = statistics.quantiles(scores, n=10)
        print("deciles              : " + " ".join(f"{d:.1f}" for d in deciles))

    print("\nmost common scores:")
    for value, count in counts.most_common(5):
        if count == 1:
            break
        companies = [c for c, s, _ in rows if s == value][:6]
        print(f"  {value:5.1f}  x{count:<3}  {', '.join(companies)}"
              + (" ..." if count > 6 else ""))

    verdicts = Counter(v for _, _, v in rows)
    print("\nrecommendations      : " + ", ".join(f"{k}={v}" for k, v in verdicts.most_common()))

    # The specific defect, named explicitly so a regression is unmissable.
    at_30 = counts.get(30.0, 0)
    if at_30 >= 3:
        print(f"\n!! {at_30} reports sit at exactly 30.0 -- the signature of the old hard cap.")
    verdict_ok = top_count / n <= 0.15
    print(f"\nVERDICT: {'PASS' if verdict_ok else 'FAIL'} "
          f"-- largest identical cluster is {top_count / n:.0%} of reports "
          f"(threshold: no single value may hold more than 15%).")

    return {
        "label": label, "n": n, "distinct": distinct,
        "largest_cluster_value": top_value, "largest_cluster_count": top_count,
        "largest_cluster_share": round(top_count / n, 4),
        "min": min(scores), "max": max(scores),
        "mean": round(statistics.mean(scores), 2),
        "stdev": round(statistics.stdev(scores), 2) if n > 1 else None,
        "reports_at_exactly_30": at_30,
        "passes": verdict_ok,
        "ordered_scores": ordered,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", nargs="*", default=None,
                        help="glob(s) of report JSON files; omit to read the database")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--out", default=None, help="write the summary as JSON")
    args = parser.parse_args()

    if args.source:
        rows = _from_files(args.source)
        label = f"report files ({', '.join(args.source)})"
    else:
        rows = _from_db(args.limit)
        label = "stored reports (database)"

    summary = summarise(rows, label)
    if args.out and summary:
        Path(args.out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0 if summary.get("passes") else 1


if __name__ == "__main__":
    raise SystemExit(main())
