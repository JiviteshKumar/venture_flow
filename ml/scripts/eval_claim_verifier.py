"""Evaluation harness for `agents/claim_verifier.py` against a hand-labeled
benchmark (ml/eval/claim_benchmark.jsonl).

This is the actual "claim-verification benchmark + eval framework" ship-list
deliverable: a fixed, labeled test set plus a script that reports precision,
recall, F1 per verdict class, overall accuracy, a confusion matrix, and a
simple confidence-calibration check (is the model's own stated confidence
actually higher when it's correct?).

The metrics computation (`compute_metrics`) is deliberately a pure function
of a list of {claim_id, gold, predicted, confidence} rows, kept separate from
the part that calls the live claim verifier -- see
tests/test_eval_claim_verifier.py, which exercises `compute_metrics` directly
against a small synthetic case with no network or LLM calls at all. That
test can run (and does run, in CI) without a GROQ_API_KEY; actually running
this script end-to-end against the benchmark needs one, plus live internet
access for the DuckDuckGo search `agents/claim_verifier.py` depends on --
both of which are available now (23 Aug 2026) and were used to produce the
committed results files next to the benchmark.

Every run persists three things, so a reported figure can be reloaded and
recomputed rather than trusted from a log line:

  * `<out>`               -- metrics + one row per claim (verdict, confidence,
                             sources, reasoning)
  * `<out>.partial.jsonl` -- append-only per-claim log written as the run
                             proceeds, so a 150-claim run that dies at claim
                             130 does not throw away an hour of work; the next
                             invocation resumes from it unless --no-resume is
                             passed
  * `evidence` on each row -- the exact retrieved web evidence the LLM judged,
                             so the TF-IDF Claim Model baseline
                             (ml/scripts/eval_claim_model_baseline.py) can be
                             scored against the *same* evidence instead of a
                             separately-retrieved, and therefore incomparable,
                             set

Usage:
    python ml/scripts/eval_claim_verifier.py
    python ml/scripts/eval_claim_verifier.py --benchmark ml/eval/claim_benchmark_v1_30.jsonl \
        --out ml/eval/claim_benchmark_results_v1_30.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Windows stdout is cp1252 and both this script and agents/claim_verifier.py
# print LLM-produced text containing typographic characters. Without this the
# run dies with UnicodeEncodeError partway through -- see console_safety.py.
import console_safety  # noqa: F401  (imported for side effect)

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_PATH = ROOT / "ml" / "eval" / "claim_benchmark.jsonl"
RESULTS_PATH = ROOT / "ml" / "eval" / "claim_benchmark_results.json"
VERDICTS = ["SUPPORTS", "REFUTES", "NOT_ENOUGH_INFO"]


def load_benchmark(path: Path | str | None = None) -> list[dict[str, Any]]:
    rows = []
    with open(path or BENCHMARK_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure function: rows are {gold, predicted, confidence (optional)}.
    No network, no LLM calls -- unit-tested directly."""
    n = len(rows)
    confusion = {g: {p: 0 for p in VERDICTS} for g in VERDICTS}
    for row in rows:
        gold, pred = row["gold"], row["predicted"]
        if gold in confusion and pred in confusion[gold]:
            confusion[gold][pred] += 1

    per_class = {}
    for verdict in VERDICTS:
        tp = confusion[verdict][verdict]
        fp = sum(confusion[g][verdict] for g in VERDICTS if g != verdict)
        fn = sum(confusion[verdict][p] for p in VERDICTS if p != verdict)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        per_class[verdict] = {
            "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3),
            "support": sum(confusion[verdict].values()),
        }

    correct = sum(1 for row in rows if row["gold"] == row["predicted"])
    accuracy = correct / n if n else 0.0

    confidences = [row.get("confidence") for row in rows if row.get("confidence") is not None]
    mean_conf_correct = _mean([row["confidence"] for row in rows if row["gold"] == row["predicted"] and row.get("confidence") is not None])
    mean_conf_incorrect = _mean([row["confidence"] for row in rows if row["gold"] != row["predicted"] and row.get("confidence") is not None])

    # Accuracy broken out by the benchmark's `subset` field, when rows carry
    # one. The three subsets are deliberately different difficulties --
    # well-documented public facts, invented companies, and real-but-obscure
    # companies -- and a single pooled accuracy hides which of them the
    # verifier is actually failing on. Absent on rows without a subset, so
    # older result files and the synthetic unit-test rows are unaffected.
    by_subset: dict[str, dict[str, Any]] = {}
    for row in rows:
        subset = row.get("subset")
        if not subset:
            continue
        bucket = by_subset.setdefault(subset, {"n": 0, "correct": 0})
        bucket["n"] += 1
        bucket["correct"] += int(row["gold"] == row["predicted"])
    for bucket in by_subset.values():
        bucket["accuracy"] = round(bucket["correct"] / bucket["n"], 3) if bucket["n"] else 0.0

    return {
        "n": n,
        "accuracy": round(accuracy, 3),
        "per_class": per_class,
        "confusion_matrix": confusion,
        "by_subset": by_subset,
        "calibration": {
            "mean_confidence_when_correct": round(mean_conf_correct, 3) if mean_conf_correct is not None else None,
            "mean_confidence_when_incorrect": round(mean_conf_incorrect, 3) if mean_conf_incorrect is not None else None,
            "note": (
                "A well-calibrated verifier should show a higher mean confidence "
                "when correct than when incorrect. If these are close or inverted, "
                "the model's stated confidence isn't trustworthy on its own."
            ) if confidences else "No confidence values recorded.",
        },
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


# The exact sentinel agents/claim_verifier.py returns when its Groq call
# raises -- rate limit, bad key, network. Matched on the reasoning string
# because the verifier deliberately degrades rather than propagating the
# exception, so there is nothing else to key on from out here.
_PROVIDER_FAILURE_REASON = "Claim verification is temporarily unavailable."


def _is_provider_failure(result: dict[str, Any]) -> bool:
    return (result.get("reasoning") or "").strip() == _PROVIDER_FAILURE_REASON


def _load_partial(partial_path: Path) -> dict[str, dict[str, Any]]:
    """Rows already scored by an earlier, interrupted run, keyed by claim id."""
    if not partial_path.exists():
        return {}
    done: dict[str, dict[str, Any]] = {}
    with open(partial_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                # A run killed mid-write leaves one truncated final line.
                continue
            done[row["id"]] = row
    return done


def _write_results(
    benchmark_path: Path,
    out_path: Path,
    rows: list[dict[str, Any]],
    *,
    complete: bool,
    expected_n: int,
) -> dict[str, Any]:
    """Serialise metrics + per-claim rows to the results file.

    `complete` is recorded rather than inferred, because a run stopped by an
    exhausted daily quota still produces a legitimate artifact for the claims
    it did score -- and the one thing that must never happen is somebody
    reading a 128-claim result as the 150-claim result.
    """
    metrics = compute_metrics(rows)
    # Retrieval health belongs in the artifact: verify_claim forces
    # NOT_ENOUGH_INFO on a claim it could retrieve nothing for, so a throttled
    # search backend would inflate that class and read as verifier behaviour
    # when it is really an artifact of the evaluation run.
    metrics["retrieval"] = {
        "claims_with_zero_sources": sum(1 for r in rows if not r.get("total_sources")),
        "mean_sources_per_claim": round(
            sum(r.get("total_sources", 0) for r in rows) / len(rows), 2
        ) if rows else 0.0,
    }
    output = {
        "benchmark": benchmark_path.name,
        "verifier": "agents/claim_verifier.py (live web search + LLM judge)",
        "complete": complete,
        "n_scored": len(rows),
        "n_in_benchmark": expected_n,
        "metrics": metrics,
        "rows": rows,
    }
    if not complete:
        output["incomplete_reason"] = (
            "The run stopped on a provider/quota failure. The rows present are real "
            "measurements; the missing claims were never scored, not scored as "
            "NOT_ENOUGH_INFO. Re-run the same command to resume from the partial log."
        )
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


def run_benchmark(
    benchmark_path: Path | str | None = None,
    out_path: Path | str | None = None,
    sleep_s: float = 0.5,
    resume: bool = True,
    provider_retries: int = 5,
    retry_wait_s: float = 120.0,
) -> dict[str, Any]:
    from agents.claim_verifier import verify_claim

    benchmark_path = Path(benchmark_path or BENCHMARK_PATH)
    out_path = Path(out_path or RESULTS_PATH)
    partial_path = out_path.with_suffix(".partial.jsonl")

    benchmark = load_benchmark(benchmark_path)
    if not resume and partial_path.exists():
        partial_path.unlink()
    done = _load_partial(partial_path) if resume else {}
    if done:
        print(f"Resuming: {len(done)} of {len(benchmark)} claims already scored in {partial_path.name}")

    rows = []
    for position, item in enumerate(benchmark, 1):
        cached = done.get(item["id"])
        if cached is not None:
            rows.append(cached)
            continue

        print(f"\n[{position}/{len(benchmark)}] {item['id']}: {item['claim'][:80]}")
        result = verify_claim(item["claim"], verbose=False, include_evidence=True)

        # Groq's free tier caps tokens per *day* on a rolling window, so once
        # the cap is hit quota trickles back at roughly the daily rate rather
        # than arriving all at once. A single claim costs about 4,000 tokens,
        # which is a few minutes of accumulated allowance -- so waiting and
        # retrying genuinely makes progress where giving up immediately does
        # not, and a long benchmark run can grind through the cap instead of
        # needing a human to restart it every few minutes.
        for attempt in range(1, provider_retries + 1):
            if not _is_provider_failure(result):
                break
            print(f"    provider unavailable; waiting {retry_wait_s:.0f}s "
                  f"(attempt {attempt}/{provider_retries})")
            time.sleep(retry_wait_s)
            result = verify_claim(item["claim"], verbose=False, include_evidence=True)

        # Stop rather than record a provider outage as a model prediction.
        #
        # This guard exists because the first 150-claim run hit Groq's free-tier
        # daily token ceiling at claim 36 and kept going for another 14 claims.
        # Every one of those came back NOT_ENOUGH_INFO at confidence 0.0 --
        # indistinguishable, in the results file, from the verifier genuinely
        # judging the evidence insufficient. Left in, they would have depressed
        # SUPPORTS recall and inflated NOT_ENOUGH_INFO precision by an amount
        # that is not a property of the verifier at all. A benchmark that
        # silently scores an outage is worse than one that refuses to finish,
        # so this raises; the partial log holds everything scored so far and
        # the next invocation resumes from it once quota is back.
        if _is_provider_failure(result):
            # Write what was genuinely scored before giving up. A run stopped
            # by an exhausted quota still produced real measurements for every
            # claim before that point, and they should land in a reloadable
            # artifact rather than only in the partial log -- clearly marked
            # `complete: false` so nobody quotes a 128-claim run as 150.
            if rows:
                _write_results(benchmark_path, out_path, rows, complete=False,
                               expected_n=len(benchmark))
                print(f"\nWrote partial results ({len(rows)}/{len(benchmark)} claims) to {out_path}")
            raise RuntimeError(
                f"The claim verifier reported itself unavailable on {item['id']} "
                f"(reason: {result.get('reasoning', '')!r}). This is a provider/quota "
                f"failure, not a verdict. {len(rows)} claims scored so far are in "
                f"{partial_path.name}; re-run this command to resume from there."
            )

        row = {
            "id": item["id"],
            "claim": item["claim"],
            "category": item.get("category", ""),
            "subset": item.get("subset", ""),
            "gold": item["gold_verdict"],
            "predicted": result.get("verdict", "NOT_ENOUGH_INFO"),
            "confidence": result.get("confidence"),
            "reasoning": result.get("reasoning", ""),
            "sources": result.get("sources", []),
            "total_sources": result.get("total_sources", 0),
            "full_pages_read": result.get("full_pages_read", 0),
            # The judged evidence, capped. This is what makes the TF-IDF
            # baseline comparison apples-to-apples -- see the module docstring.
            "evidence": (result.get("evidence_text") or "")[:6000],
        }
        rows.append(row)
        with open(partial_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        print(f"    gold={row['gold']:<16} predicted={row['predicted']:<16} "
              f"conf={row['confidence']} sources={row['total_sources']}")
        time.sleep(sleep_s)  # be polite to the free search backend

    return _write_results(benchmark_path, out_path, rows, complete=True,
                          expected_n=len(benchmark))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Score the claim benchmark against the live verifier.")
    parser.add_argument("--benchmark", default=str(BENCHMARK_PATH))
    parser.add_argument("--out", default=str(RESULTS_PATH))
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--no-resume", action="store_true",
                        help="ignore (and delete) any partial log from an earlier run")
    parser.add_argument("--provider-retries", type=int, default=5,
                        help="how many times to wait out a provider/quota failure per claim")
    parser.add_argument("--retry-wait", type=float, default=120.0,
                        help="seconds to wait between those retries")
    args = parser.parse_args()

    result = run_benchmark(
        args.benchmark, args.out, args.sleep, resume=not args.no_resume,
        provider_retries=args.provider_retries, retry_wait_s=args.retry_wait,
    )
    print(json.dumps(result["metrics"], indent=2))
    print(f"\nFull per-claim results saved to {args.out}")
