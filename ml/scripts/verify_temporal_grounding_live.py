"""Does the temporal fix actually change a live verdict?

Part 1 established the fix is structurally present: the regex matches, the field
exists, and the year reaches `verify_claim` through the live API path. That is
necessary and not sufficient. The question this answers is behavioural -- given
a real historical claim and real retrieved evidence, does telling the verifier
the deck's vintage change what it decides?

WHY THIS IS THE CHEAP WAY TO ASK

A full deck run costs roughly 24,000 tokens and cannot complete inside the free
tier's 8,000-tokens-per-minute ceiling, so every attempt degrades and the claim
verdicts come back "temporarily unavailable" -- which answers nothing. Verifying
a handful of claims directly costs about 4,000 tokens each and isolates exactly
the behaviour in question.

THE CLAIMS

Real metrics from the corpus decks, each true when written and false today. This
is the exact pattern that produced the worst finding this project has made: four
confident REFUTES at 0.95-0.97, every one of them wrong, because a 2011 figure
was being judged against 2026 evidence.

A correct result is NOT necessarily SUPPORTS -- public evidence for a small
company's 2011 metrics may genuinely not exist. A correct result is **not a
confident REFUTES**. The failure being tested for is the verifier calling growth
a lie.

    python ml/scripts/verify_temporal_grounding_live.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: F401  (Windows cp1252 guard)
from agents.claim_verifier import verify_claim

OUT_PATH = ROOT / "ml" / "eval" / "temporal_grounding_live.json"

# (company, deck year, claim). All were true at the time and are false now.
CASES = [
    ("Buffer", "2011", "Buffer has 800 paying users."),
    ("Coinbase", "2012", "Coinbase processes $2M per day in transaction volume."),
]


def main() -> int:
    results = []
    for company, year, claim in CASES:
        for label, as_of in (("WITHOUT deck date", ""), ("WITH deck date", year)):
            print(f"\n[{company} / {label}] {claim}")
            try:
                out = verify_claim(
                    claim, verbose=False, company=company,
                    context=f"{company} pitch deck", as_of=as_of,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"    FAILED: {type(exc).__name__}: {exc}")
                results.append({"company": company, "arm": label, "error": str(exc)[:200]})
                time.sleep(30)
                continue

            verdict = out.get("verdict")
            confidence = float(out.get("confidence") or 0)
            print(f"    verdict={verdict} confidence={confidence:.2f}")
            print(f"    reasoning: {str(out.get('reasoning'))[:200]}")
            # A provider failure is NOT a passing result.
            #
            # The first version of this harness counted them as passes, because
            # "temporarily unavailable" is not a confident REFUTES -- technically
            # true and completely meaningless. It reported "0 confident
            # refutations" from four runs in which the verifier never actually
            # ran, which is precisely the defect this project keeps finding
            # elsewhere: infrastructure failure recorded as a finding.
            reasoning = str(out.get("reasoning") or "")
            unavailable = (
                "temporarily unavailable" in reasoning.lower()
                or "no external evidence could be retrieved" in reasoning.lower()
                or (verdict == "NOT_ENOUGH_INFO" and confidence == 0.0
                    and not out.get("total_sources"))
            )
            results.append({
                "company": company, "deck_year": year, "claim": claim,
                "arm": label, "as_of": as_of,
                "verdict": verdict, "confidence": confidence,
                "reasoning": reasoning[:600],
                "sources": out.get("sources", [])[:3],
                "total_sources": out.get("total_sources", 0),
                "provider_unavailable": unavailable,
                # The failure mode under test.
                "is_confident_refutation": verdict == "REFUTES" and confidence >= 0.8,
            })
            # Pace against the 8,000 tokens-per-minute ceiling.
            time.sleep(45)

    attempted = [r for r in results if "verdict" in r]
    # Only runs where the verifier actually reached a judgement count.
    scored = [r for r in attempted if not r["provider_unavailable"]]
    unavailable = [r for r in attempted if r["provider_unavailable"]]
    bad = [r for r in scored if r["is_confident_refutation"]]

    print("\n" + "=" * 74)
    print("RESULT")
    print("=" * 74)
    for r in scored:
        marker = "BAD " if r["is_confident_refutation"] else "ok  "
        print(f"  [{marker}] {r['company']:<9} {r['arm']:<19} "
              f"{r['verdict']:<16} conf={r['confidence']:.2f}")
    print(f"\n  verdicts actually reached          : {len(scored)}/{len(attempted)}")
    if unavailable:
        print(f"  provider-unavailable, NOT SCORED   : {len(unavailable)} "
              f"(these prove nothing either way)")
    print(f"  confident refutations of true claims: {len(bad)}")
    if not scored:
        print("  -> INCONCLUSIVE. The verifier never reached a judgement, so this "
              "run says nothing about the fix.")
    elif not bad:
        print("  -> The failure this fix targets did not occur on the claims that "
              "were actually judged.")
    else:
        print("  -> the defect REPRODUCED; the fix is not sufficient.")

    OUT_PATH.write_text(json.dumps({
        "what_this_tests": (
            "Whether supplying the deck's vintage changes a live claim verdict, on "
            "real metrics that were true when written and are false today. A "
            "correct outcome is NOT necessarily SUPPORTS -- evidence for a small "
            "company's old metrics may not exist -- it is the ABSENCE of a "
            "confident REFUTES."
        ),
        "n_attempted": len(attempted),
        "n_verdicts_actually_reached": len(scored),
        "n_provider_unavailable_not_scored": len(unavailable),
        "n_confident_refutations": len(bad),
        "conclusive": bool(scored),
        "caveat": (
            "Only runs where the verifier reached a judgement are scored. A "
            "provider failure is excluded rather than counted as a pass -- an "
            "earlier version of this harness reported 0 confident refutations "
            "from four runs in which the verifier never executed."
        ),
        "results": results,
    }, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
