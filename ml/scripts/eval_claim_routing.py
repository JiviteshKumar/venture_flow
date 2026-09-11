"""Does claim routing change what the verifier can establish on REAL decks?

agents/claim_router.py sends a claim that names no company through both
anchored and unanchored search, instead of gluing the company name onto every
query. Its motivating cases are real claims from real decks that came back
NOT_ENOUGH_INFO: "Medallions cost ~$500k, drivers make 31k" (Uber, 2008),
"Total available market is 1.9 Billion+ trips booked worldwide" (Airbnb).

The measurement is an A/B in ONE session, not a comparison against verdicts
stored on other days: retrieval varies run to run, and a before/after across
days would mix the routing change with that noise. For every claim whose search
mode changed, the old mode ("company") and the new mode run back to back;
claims whose mode is unchanged run once. Each claim is judged against its deck's
own year.

Synthetic test decks are excluded on purpose. A company that does not exist can
never be corroborated, and including them would measure nothing about routing.

The verdict cache is turned off, so a measurement never seeds production data
and every check is fresh.

    python ml/scripts/eval_claim_routing.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

os.environ["VENTUREFLOW_CLAIM_CACHE"] = "off"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import console_safety  # noqa: F401,E402
import observability  # noqa: E402

observability.configure_logging()

import db  # noqa: E402
from agents.claim_router import GARBLED, SEARCH_BOTH, classify  # noqa: E402
from agents.claim_verifier import verify_claim  # noqa: E402

OUT = ROOT / "ml" / "eval" / "claim_routing_real_decks.json"
REAL_DECKS = ("Uber", "Airbnb", "Buffer", "Coinbase", "Front", "Intercom", "Mint")


def deck_years() -> dict[str, str]:
    manifest = json.loads((ROOT / "ml" / "eval" / "decks" / "manifest.json").read_text(encoding="utf-8"))
    return {row["company"]: str(row.get("deck_year") or "") for row in manifest}


def stored_claims() -> list[dict]:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT dr.id, c.name, dr.raw_output FROM dd_reports dr "
            "JOIN companies c ON c.id = dr.company_id WHERE c.name = ANY(%s) ORDER BY dr.id",
            (list(REAL_DECKS),),
        )
        rows = cur.fetchall()
    seen, out = set(), []
    for row in rows:
        details = ((row["raw_output"] or {}).get("sections") or {}).get("claims", {}).get("details") or []
        for d in details:
            if not isinstance(d, dict) or d.get("_degraded"):
                continue
            claim = " ".join((d.get("claim") or "").split())
            key = (row["name"], claim.lower())
            if claim and key not in seen:
                seen.add(key)
                out.append({"company": row["name"], "claim": claim, "report_id": row["id"],
                            "stored_verdict": d.get("verdict"),
                            "stored_sources": d.get("total_sources")})
    return out


def check(claim: str, company: str, year: str, search: str) -> dict:
    r = verify_claim(claim, verbose=False, company=company, as_of=year, search=search)
    return {"verdict": r.get("verdict"), "confidence": r.get("confidence"),
            "sources": r.get("total_sources"), "degraded": bool(r.get("_degraded")),
            "degraded_kind": r.get("_degraded_kind"),
            "reasoning": (r.get("reasoning") or "")[:300]}


def _provider_down(result: dict | None) -> bool:
    """Stop only when the provider is down. An unreadable judge reply
    (`_degraded_kind` "unparseable") is the verifier failing on one claim -- a
    result to count, not a reason to stop."""
    return bool(result) and result["degraded"] and result.get("degraded_kind") != "unparseable"


def _previous() -> dict[tuple[str, str], dict]:
    """Rows already measured by an earlier run, so a run stopped by the daily
    token ceiling resumes instead of paying for the same claims again. Rows
    that ended in a provider outage are dropped and re-measured."""
    if not OUT.exists():
        return {}
    done = {}
    for row in json.loads(OUT.read_text(encoding="utf-8")).get("rows", []):
        if row.get("skipped") or not (_provider_down(row.get("new")) or _provider_down(row.get("old"))):
            done[(row["company"], row["claim"])] = row
    return done


def main() -> int:
    years = deck_years()
    items = stored_claims()
    rows, stopped = [], None
    print(f"{len(items)} distinct claims from real decks\n")

    previous = _previous()
    if previous:
        print(f"resuming: {len(previous)} claim(s) already measured\n")
    for n, item in enumerate(items, 1):
        if (item["company"], item["claim"]) in previous:
            rows.append(previous[(item["company"], item["claim"])])
            continue
        routed = classify(item["claim"], item["company"])
        row = {**item, "kind": routed.kind, "search": routed.search,
               "year": years.get(item["company"], "")}
        if routed.kind == GARBLED:
            row["skipped"] = routed.reason
            rows.append(row)
            print(f"[{n}] skip (fragment): {item['claim'][:70]}")
            continue

        row["new"] = check(routed.claim, item["company"], row["year"], routed.search)
        if routed.search == SEARCH_BOTH:
            row["old"] = check(routed.claim, item["company"], row["year"], "company")
        rows.append(row)

        if _provider_down(row["new"]) or _provider_down(row.get("old")):
            stopped = f"provider unavailable at claim {n}: {row['new']['reasoning'][:120]}"
            print("STOPPING:", stopped)
            break
        old = row.get("old")
        print(f"[{n}] {routed.kind:8s} {routed.search:7s} "
              f"old={(old or {}).get('verdict', '(same mode)'):16s} new={row['new']['verdict']:16s} "
              f"src {(old or {}).get('sources', '-')}->{row['new']['sources']}  {item['claim'][:60]}")
        time.sleep(1)

    OUT.write_text(json.dumps({"complete": stopped is None, "stopped": stopped, "rows": rows},
                              indent=2, default=str), encoding="utf-8")

    ab = [r for r in rows if r.get("old") and r.get("new")]
    decisive = lambda v: v in ("SUPPORTS", "REFUTES")
    print("\n" + "=" * 70)
    print(f"A/B claims (mode changed): {len(ab)}")
    print(f"  decisive, old mode: {sum(decisive(r['old']['verdict']) for r in ab)}")
    print(f"  decisive, new mode: {sum(decisive(r['new']['verdict']) for r in ab)}")
    print(f"  mean sources, old: {sum((r['old']['sources'] or 0) for r in ab) / max(1, len(ab)):.1f}"
          f"   new: {sum((r['new']['sources'] or 0) for r in ab) / max(1, len(ab)):.1f}")
    checked = [r for r in rows if r.get("new")]
    by_kind = Counter((r["kind"], decisive(r["new"]["verdict"])) for r in checked)
    print(f"all checked (new mode): {len(checked)}; decisive {sum(decisive(r['new']['verdict']) for r in checked)}")
    for kind in ("market", "company", "internal"):
        print(f"  {kind:8s} decisive {by_kind[(kind, True)]}/{by_kind[(kind, True)] + by_kind[(kind, False)]}")
    print(f"\nwrote {OUT}")
    return 0 if stopped is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
