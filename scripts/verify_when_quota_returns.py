"""Run every check that needs a live language model, in priority order.

WHY THIS EXISTS

Groq's free tier caps tokens per day at 200,000 on a rolling window. A full
deck analysis costs 25,000-50,000 of them and one benchmark claim costs about
4,000, so the day's budget is four to eight analyses -- and once it is spent it
does not come back all at once. It trickles back at roughly the rate it was
spent, which means a run that hits the ceiling cannot simply retry in a few
minutes; it needs the window to age out, which takes most of a day.

Everything that does not need the model has already been measured and is
covered by the test suite. What is left is the work that genuinely cannot be
done without one, collected here so it can be started with a single command
rather than reconstructed from notes:

    python scripts/verify_when_quota_returns.py

Steps run in priority order and the script stops at the first one that hits the
ceiling, reporting exactly how far it got. Re-running resumes: the benchmark
harness keeps an append-only partial log, and the earlier steps are cheap.

Check the budget before starting a long step:

    python scripts/verify_when_quota_returns.py --check-only
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import console_safety  # noqa: F401,E402

# Rough token cost of each step, so the script can say what will not fit rather
# than starting something that is certain to fail halfway through.
STEPS = [
    {
        "name": "claim-verifier benchmark subset (19 claims)",
        "cost": 80_000,
        "why": (
            "The retrieval fixes are measured only at the retrieval layer so "
            "far: 5 of the 6 failing claims now retrieve the fact the judge "
            "said was missing. Whether the verdicts actually flip needs the "
            "judge, and this subset is the 6 failures plus the 13 controls "
            "most at risk of being broken by the change."
        ),
        "cmd": [
            sys.executable, "ml/scripts/eval_claim_verifier.py",
            "--benchmark", "ml/eval/claim_benchmark_subset_retrieval.jsonl",
            "--out", "ml/eval/claim_benchmark_subset_retrieval_results.json",
        ],
    },
    {
        "name": "full claim-verifier benchmark (150 claims)",
        "cost": 600_000,
        "why": (
            "The headline accuracy figure. The committed run scored 134 of 150 "
            "at 0.955 before hitting the ceiling; this needs several days of "
            "budget and resumes from its partial log across runs."
        ),
        "cmd": [
            sys.executable, "ml/scripts/eval_claim_verifier.py",
            "--benchmark", "ml/eval/claim_benchmark.jsonl",
            "--out", "ml/eval/claim_benchmark_results.json",
        ],
    },
]


def budget() -> tuple[bool, str]:
    """Ask the provider directly. There is no header for this: the only way to
    learn the remaining daily budget is to be refused by a real request."""
    import groq_client

    probe = "evidence: " + ("lorem ipsum dolor sit amet " * 400)
    try:
        groq_client.get_client().chat.completions.create(
            model=groq_client.MODEL,
            messages=[{"role": "user", "content": probe + "\nReply OK."}],
            max_tokens=2048,
        )
        return True, "budget available"
    except Exception as exc:  # noqa: BLE001 - the message is the payload
        match = re.search(
            r"Limit (\d+), Used (\d+).*?try again in ([0-9hms.]+)", str(exc))
        if match:
            limit, used, wait = match.groups()
            return False, (f"{int(used):,} of {int(limit):,} tokens used; "
                           f"next window in {wait}")
        return False, str(exc)[:200]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true",
                        help="report the remaining budget and exit")
    args = parser.parse_args()

    ok, detail = budget()
    print(f"Groq daily budget: {detail}\n")
    if args.check_only:
        return 0 if ok else 1
    if not ok:
        print("Nothing below can run yet. Re-run this script when the window "
              "has aged out (usually the next day).")
        return 1

    for index, step in enumerate(STEPS, 1):
        print(f"\n{'=' * 70}\n[{index}/{len(STEPS)}] {step['name']}")
        print(f"  approx cost : {step['cost']:,} tokens")
        print(f"  why         : {step['why']}\n{'=' * 70}\n")
        result = subprocess.run(step["cmd"], cwd=ROOT)
        if result.returncode != 0:
            print(f"\nStopped at step {index} ({step['name']}).")
            print("If this was the token ceiling, re-run tomorrow; the "
                  "benchmark harness resumes from its partial log.")
            return result.returncode

    print("\nAll steps completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
