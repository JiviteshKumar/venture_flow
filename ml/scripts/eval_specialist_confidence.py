"""Is the specialist agents' `confidence` number reproducible, and does it mean
anything?

BACKGROUND

Until this session `confidence` was never defined. The prompt said only that it
"MUST be a bare number between 0 and 1" and that an agent should "lower
confidence" when evidence is absent. Nothing said confidence in WHAT. Four
different agents -- market, team, bull_case, bear_case -- each returned a number
under that instruction, and `bull_case` in particular could reasonably read it
as "how bullish I am", which is a completely different quantity from "how well
evidenced this is".

That number is not cosmetic: `ventureflow_agent._evidence_components` uses
`specialist_uncertainty = (1 - mean_confidence) * 0.15`, so an undefined
quantity moves the headline score.

The prompt now defines it as one thing -- the fraction of the assessment resting
on quotable evidence rather than general inference -- with five calibration
bands and two checkable rules (empty signals implies < 0.15; above 0.60 requires
two verbatim excerpts).

WHAT THIS MEASURES

Two properties, because variance alone is not enough to call a number useful.

1. **Reproducibility.** The same deck through the same agent N times. Spread is
   reported as standard deviation and range. Temperature is 0.1, so a wide
   spread would mean the definition is not doing its job.

2. **Directional validity.** An evidence-RICH deck and an evidence-THIN deck.
   If confidence means what the prompt now says, the rich deck must score higher.
   A number can be perfectly reproducible and still meaningless -- an agent that
   always answers 0.7 has zero variance -- so the ordering check is the one that
   decides whether the definition worked.

Reports what it finds, including if the answer is that this does not work.

    python ml/scripts/eval_specialist_confidence.py --repeats 4
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: F401  (Windows cp1252 guard)
from agents.investment_agents import run_investment_agents

OUT_PATH = ROOT / "ml" / "eval" / "specialist_confidence_results.json"

# Evidence-RICH: specific, quotable numbers, named customers, dated facts.
RICH_DECK = (
    "Northwind Robotics. Warehouse automation for mid-size third-party logistics "
    "operators. Traction: we closed $2.4M in ARR this financial year, up from "
    "$310K the year before, across 62 paying customers. Our largest account, a "
    "national logistics operator, represents $1.9M of that figure under a master "
    "services agreement renewing in four months. Financials: monthly burn is "
    "$410K against $38K in monthly recognised revenue, with $1.1M cash on hand. "
    "Team: our CEO spent six years in operations at a national grocery "
    "distributor and led the rollout of its first automated fulfilment centre; "
    "our CTO previously built routing infrastructure at a logistics unicorn. "
    "Market: third-party analysts size the warehouse execution software market at "
    "$4.1B today. Product: our platform ingests warehouse management system "
    "events and produces a live picking plan for floor staff."
)

# Evidence-THIN: the same company, described only in adjectives. Deliberately
# not empty -- an empty deck is trivially low confidence and would prove nothing.
THIN_DECK = (
    "Northwind Robotics is building the future of warehouse automation. We are a "
    "passionate team solving a massive problem in a huge and rapidly growing "
    "market. Our technology is transformative and our early traction has been "
    "very encouraging. We have strong relationships with major players in the "
    "industry and a clear path to category leadership. The opportunity ahead of "
    "us is enormous and we are uniquely positioned to capture it."
)

AGENTS = ("market", "team", "bull_case", "bear_case")


def _run_once(deck: str) -> dict[str, dict]:
    return run_investment_agents(
        company="Northwind Robotics", document=deck, claims=[], risk={},
    )


def _confidence(result: dict) -> float | None:
    """The agent's number, or None if this run was a degraded fallback.

    A degraded run must never enter the statistics: its confidence is 0 because
    the provider failed, not because the agent judged the evidence poor, and
    averaging those together is the exact confusion this codebase spent a whole
    session removing.
    """
    if not isinstance(result, dict) or result.get("_degraded"):
        return None
    value = result.get("confidence")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=4,
                        help="repeats on the evidence-rich deck")
    parser.add_argument("--thin-repeats", type=int, default=2)
    args = parser.parse_args()

    runs: list[dict] = []
    total_calls = (args.repeats + args.thin_repeats) * len(AGENTS)
    print(f"Running {args.repeats} rich + {args.thin_repeats} thin repeats "
          f"= {total_calls} specialist calls (~{total_calls * 2200:,} tokens estimated)\n")

    for condition, deck, repeats in (("rich", RICH_DECK, args.repeats),
                                     ("thin", THIN_DECK, args.thin_repeats)):
        for attempt in range(1, repeats + 1):
            print(f"[{condition} {attempt}/{repeats}] running four specialists...")
            results = _run_once(deck)
            row = {"condition": condition, "attempt": attempt, "agents": {}}
            for name in AGENTS:
                result = results.get(name, {})
                row["agents"][name] = {
                    "confidence": _confidence(result),
                    "confidence_basis": result.get("confidence_basis"),
                    "degraded": bool(result.get("_degraded")),
                    "degraded_reason": result.get("_degraded_reason"),
                    "n_signals": len(result.get("signals") or result.get("capabilities") or []),
                }
                shown = row["agents"][name]["confidence"]
                print(f"    {name:<10} confidence={shown if shown is not None else 'DEGRADED'}"
                      f"  signals={row['agents'][name]['n_signals']}")
            runs.append(row)
            time.sleep(2.0)  # spread the spend across the per-minute token window

    summary: dict[str, dict] = {}
    for name in AGENTS:
        entry: dict[str, object] = {}
        for condition in ("rich", "thin"):
            values = [
                r["agents"][name]["confidence"] for r in runs
                if r["condition"] == condition and r["agents"][name]["confidence"] is not None
            ]
            entry[condition] = {
                "n": len(values),
                "values": values,
                "mean": round(statistics.mean(values), 4) if values else None,
                "stdev": round(statistics.stdev(values), 4) if len(values) > 1 else None,
                "range": [min(values), max(values)] if values else None,
            }
        rich_mean = entry["rich"].get("mean")  # type: ignore[union-attr]
        thin_mean = entry["thin"].get("mean")  # type: ignore[union-attr]
        entry["directionally_correct"] = (
            None if rich_mean is None or thin_mean is None else bool(rich_mean > thin_mean)
        )
        entry["gap_rich_minus_thin"] = (
            None if rich_mean is None or thin_mean is None else round(rich_mean - thin_mean, 4)
        )
        summary[name] = entry

    degraded = sum(
        1 for r in runs for name in AGENTS if r["agents"][name]["degraded"]
    )

    print("\n" + "=" * 78)
    print(f"{'agent':<12}{'rich mean':>11}{'sd':>8}{'thin mean':>11}{'sd':>8}"
          f"{'gap':>8}  direction")
    print("-" * 78)
    for name, entry in summary.items():
        rich, thin = entry["rich"], entry["thin"]  # type: ignore[index]
        direction = ("OK" if entry["directionally_correct"] else
                     "WRONG WAY" if entry["directionally_correct"] is False else "n/a")
        print(f"{name:<12}"
              f"{_fmt(rich['mean']):>11}{_fmt(rich['stdev']):>8}"
              f"{_fmt(thin['mean']):>11}{_fmt(thin['stdev']):>8}"
              f"{_fmt(entry['gap_rich_minus_thin']):>8}  {direction}")
    print("=" * 78)
    if degraded:
        print(f"NOTE: {degraded} of {total_calls} calls were degraded fallbacks and are "
              f"EXCLUDED from the statistics -- their confidence of 0 reflects a provider "
              f"failure, not a judgement about the evidence.")

    OUT_PATH.write_text(json.dumps({
        "what_this_measures": (
            "Reproducibility (spread across repeats of the same deck) and "
            "directional validity (evidence-rich deck must score above "
            "evidence-thin) of the specialist agents' confidence number, after "
            "the prompt was changed to define confidence as the fraction of the "
            "assessment resting on quotable evidence."
        ),
        "model_temperature": 0.1,
        "degraded_calls_excluded": degraded,
        "total_calls": total_calls,
        "summary": summary,
        "runs": runs,
    }, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT_PATH}")
    return 0


def _fmt(value) -> str:
    return "n/a" if value is None else f"{value:.3f}"


if __name__ == "__main__":
    raise SystemExit(main())
