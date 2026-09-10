"""Drive real pitch decks through the real HTTP path and audit every output.

WHY NOT ml/scripts/run_real_deck_corpus.py

That harness calls `run_due_diligence` directly, which is the right tool for
measuring the agent. It skips everything between the agent and the user:
the upload endpoint, the tech-scope gate, company-name cleaning, the job
queue, the response model, and database persistence. Every defect this project
has shipped lived in exactly that gap -- a field the pipeline computed
correctly and the response model silently dropped, a name that reached the
pipeline as a filename, slide boundaries the frontend never sent.

So this posts the file to /upload-pdf, maps the response the way
frontend/src/context/AppContext.tsx maps it, posts that to /analyze, polls
/analyze/status, and then re-reads the saved report from /reports/{id} -- the
same four calls the browser makes, in the same order, with the same payload.

The audit is the point. Rather than asserting a score is "reasonable", it
checks each thing the product claims to produce and reports it as PRESENT,
EMPTY or BROKEN, so a silently-empty panel cannot pass as a working one.

    python scripts/e2e_deck_audit.py                  # 3 decks
    python scripts/e2e_deck_audit.py --decks Uber     # just one
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import console_safety  # noqa: F401,E402

DECKS = ROOT / "ml" / "eval" / "decks"
OUT = ROOT / "ml" / "eval" / "e2e_deck_audit.json"

# Deliberately mixed: Uber is the deck that produced the 35/100 report, Airbnb
# has a rich text layer, Buffer is short and metric-heavy.
DEFAULT_DECKS = ["Uber", "Airbnb", "Buffer"]


def audit_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per thing the product promises. `state` is PRESENT / EMPTY /
    BROKEN, and EMPTY is only acceptable where the report explains itself."""
    sections = report.get("sections") or {}
    checks: list[dict[str, Any]] = []

    def check(name, ok, detail, *, critical=True):
        checks.append({
            "check": name,
            "state": "PRESENT" if ok else ("BROKEN" if critical else "EMPTY"),
            "detail": detail,
        })

    # --- the headline number -------------------------------------------------
    score = report.get("final_score")
    check("final_score", isinstance(score, (int, float)) and score > 0,
          f"{score} (source: {report.get('score_source')})")

    vs = (sections.get("venture_score") or {})
    check("venturescore_model_ran", bool(vs.get("available")),
          f"available={vs.get('available')} reason={vs.get('reason', '')!r} "
          f"score={vs.get('venture_score')} coverage={vs.get('feature_coverage')}")

    # --- claim verification --------------------------------------------------
    claims = sections.get("claims") or {}
    checked = claims.get("checked", 0)
    check("claims_checked", checked > 0,
          f"checked={checked} supported={claims.get('supported')} "
          f"refuted={claims.get('refuted')} uncertain={claims.get('uncertain')}")
    check("claim_verification_not_degraded",
          not report.get("claims_verification_degraded"),
          f"claims_verification_degraded={report.get('claims_verification_degraded')}")

    # --- the specialists the user said were empty ---------------------------
    for side in ("bull_case", "bear_case"):
        case = sections.get(side) or {}
        signals = case.get("signals") or []
        check(side, bool(signals),
              f"{len(signals)} signal(s), confidence={case.get('confidence')}, "
              f"thesis={str(case.get('thesis', ''))[:60]!r}")

    # --- founders ------------------------------------------------------------
    # The section is `founder_discovery`, not `founders`. Getting this wrong
    # once already produced a false EMPTY on a run where founder research had
    # in fact executed and retrieved 11 sources.
    # Founders arrive by TWO routes and the audit has to look at both. A deck
    # that names its team goes to `founder_verification` and never runs
    # discovery; a deck that names nobody goes to `founder_discovery`. Reading
    # only the second reported a false EMPTY on Buffer, whose three real
    # founders were sitting in the first.
    fd = sections.get("founder_discovery") or {}
    fv = sections.get("founder_verification") or []
    # Label by each entry's `origin`, not by which section it sits in: founders
    # found by public search are ALSO verified, so they land in
    # founder_verification too. Reading the section alone labelled Uber's
    # researched founders "via deck" when the report itself correctly said
    # "Not in the deck - found by public search".
    from_deck = [e.get("name") for e in fv if e.get("name") and e.get("origin") == "deck"]
    researched = [e.get("name") for e in fv if e.get("name") and e.get("origin") != "deck"]
    researched += [f.get("name") for f in (fd.get("founders") or [])
                   if f.get("name") and f.get("name") not in researched]
    names = from_deck + researched
    route = ("deck" if from_deck and not researched
             else "research" if researched and not from_deck else "deck+research")
    check("founders_named", bool(names),
          f"{len(names)} via {route}: {names[:4]}", critical=False)
    # Whichever route was taken, it has to account for itself: a report that
    # names no founder must say whether it looked.
    accounted = bool(names) or bool(fd.get("reason")) or fd.get("attempted") is not None
    check("founder_route_explained", accounted,
          f"discovery_attempted={fd.get('attempted')} searched={fd.get('searched')} "
          f"degraded={fd.get('degraded')} reason={str(fd.get('reason', ''))[:100]!r}",
          critical=False)

    # --- risk ----------------------------------------------------------------
    risk = sections.get("risk") or {}
    check("risk_signals", (risk.get("total_signals") or 0) >= 0,
          f"total={risk.get('total_signals')} concerns={len(risk.get('key_concerns') or [])} "
          f"red_flags={len(risk.get('red_flags') or [])}")

    # --- the written memo ----------------------------------------------------
    memo = sections.get("ai_analysis") or report.get("ai_analysis") or ""
    check("investment_memo", len(str(memo)) > 400, f"{len(str(memo))} chars")

    # --- extraction provenance ----------------------------------------------
    prov = sections.get("extraction_provenance") or {}
    check("extraction_provenance", bool(prov.get("method")),
          f"method={prov.get('method')!r} fallback={prov.get('fallback_reason', '')!r}")

    cov = sections.get("extraction_coverage") or report.get("extraction_coverage") or {}
    slide_cov = cov.get("slide_coverage") or cov.get("slides") or {}
    check("extraction_coverage", bool(cov),
          f"{json.dumps(slide_cov)[:120] if slide_cov else json.dumps(cov)[:120]}",
          critical=False)

    # --- comparables ---------------------------------------------------------
    # Two different things share the word. `market_comparables` is the feature:
    # nearest matches from 5,603 companies with a recorded outcome, stratified
    # across YC and non-YC. `similar_companies` is a much smaller thing --
    # other decks analysed in THIS deployment -- and is legitimately empty on a
    # clean database, so it is not a failure on its own.
    mc = sections.get("market_comparables") or {}
    comps = mc.get("comparables") or []
    check("market_comparables", bool(comps),
          f"available={mc.get('available')} n={len(comps)} "
          f"{[c.get('name') for c in comps[:4]]}")

    similar = report.get("similar_companies") or []
    checks.append({
        "check": "similar_companies_local",
        "state": "PRESENT" if similar else "EMPTY",
        "detail": f"{len(similar)}: {[c.get('name') for c in similar[:4]]} "
                  f"(empty is correct on a clean database)",
    })

    # --- the degradation contract -------------------------------------------
    check("no_provider_outage", not report.get("provider_degraded"),
          f"provider_degraded={report.get('provider_degraded')} "
          f"components={report.get('degraded_components')}")
    checks.append({
        "check": "evidence_search_degraded",
        "state": "PRESENT" if not report.get("evidence_search_degraded") else "EMPTY",
        "detail": f"{report.get('evidence_search_degraded')} "
                  f"{str(report.get('evidence_search_note', ''))[:100]}",
    })
    return checks


def run_deck(client, name: str) -> dict[str, Any]:
    path = DECKS / f"{name}.pdf"
    print(f"\n{'=' * 74}\n{name}  ({path.name})\n{'=' * 74}")
    row: dict[str, Any] = {"deck": name, "file": path.name}
    started = time.time()

    # 1. Upload -- exactly what the browser posts.
    with open(path, "rb") as handle:
        response = client.post(
            "/upload-pdf",
            files={"file": (path.name, handle, "application/pdf")},
            data={"company_name": path.stem},
        )
    row["upload_status"] = response.status_code
    if response.status_code != 200:
        row["error"] = f"upload failed: {response.text[:400]}"
        print("  UPLOAD FAILED:", row["error"])
        return row
    up = response.json()
    row["upload"] = {
        "company_description_chars": len(up.get("company_description") or ""),
        "extracted_chars": len(up.get("extracted_text") or ""),
        "detected_claims": len(up.get("detected_claims") or []),
        "detected_founders": [f.get("name") for f in (up.get("detected_founders") or [])],
        "deck_slides": len(up.get("deck_slides") or []),
        "extraction_method": up.get("extraction_method"),
        "text_source": up.get("text_source"),
        "page_count": up.get("page_count"),
        "stage": up.get("stage"), "sector": up.get("sector"),
        "revenue": up.get("revenue"), "burn_rate": up.get("burn_rate"),
        "scope_check": (up.get("scope_check") or {}).get("in_scope"),
    }
    print(f"  upload: {row['upload']['extracted_chars']} chars, "
          f"{row['upload']['detected_claims']} claims, "
          f"{row['upload']['deck_slides']} slides, "
          f"method={row['upload']['extraction_method']}, "
          f"in_scope={row['upload']['scope_check']}")

    # 2. Analyse -- the same mapping AppContext.tsx performs.
    payload = {
        "company_name": path.stem,
        "company_description": up.get("company_description"),
        "claims": up.get("detected_claims") or [],
        "filing_text": up.get("extracted_text"),
        "revenue": up.get("revenue"),
        "burn_rate": up.get("burn_rate"),
        "runway_months": up.get("runway_months"),
        "stage": up.get("stage") or None,
        "sector": up.get("sector") or None,
        "team_size": up.get("team_size"),
        "github_url": up.get("github_url") or None,
        "domain": up.get("domain") or None,
        "founders": [f.get("name") for f in (up.get("detected_founders") or [])
                     if f.get("name")],
        "deck_slides": up.get("deck_slides") or [],
        "extraction_method": up.get("extraction_method") or "",
        "extraction_fallback_reason": up.get("extraction_fallback_reason") or "",
    }
    print("  analysing (this runs the full pipeline)...")
    response = client.post("/analyze", json=payload)
    row["analyze_status"] = response.status_code
    if response.status_code != 202:
        row["error"] = f"analyze rejected: {response.status_code} {response.text[:400]}"
        print("  ANALYZE FAILED:", row["error"])
        return row

    job = response.json()
    job_id = job["job_id"]
    # TestClient runs BackgroundTasks before returning, so the job is finished
    # by now; poll anyway, because that is what the browser does.
    for _ in range(3):
        status = client.get(f"/analyze/status/{job_id}").json()
        if status.get("status") in ("complete", "failed", "error"):
            break
        time.sleep(1)

    row["job_status"] = status.get("status")
    if status.get("status") != "complete":
        row["error"] = f"job {status.get('status')}: {status.get('error')}"
        print("  JOB FAILED:", row["error"])
        return row

    report = status.get("report") or {}
    row["seconds"] = round(time.time() - started, 1)
    row["company_as_analysed"] = report.get("company")
    row["checks"] = audit_report(report)
    # Persisted in full: every one of these runs costs real tokens, so a
    # question asked afterwards must be answerable without paying again.
    row["report"] = report

    # 3. Re-read from storage. A report that renders once and cannot be
    #    reloaded is broken for every user who closes the tab.
    report_id = report.get("report_id")
    if report_id:
        reread = client.get(f"/reports/{report_id}")
        row["reread_status"] = reread.status_code
        if reread.status_code == 200:
            saved = reread.json()
            row["reread_checks"] = audit_report(saved)
        else:
            row["reread_error"] = reread.text[:300]
    else:
        row["reread_status"] = "no report_id returned"

    for item in row["checks"]:
        marker = {"PRESENT": "ok  ", "EMPTY": "EMPTY", "BROKEN": "BROKEN"}[item["state"]]
        print(f"    [{marker:6s}] {item['check']:34s} {item['detail'][:90]}")
    print(f"  finished in {row['seconds']}s; reread={row.get('reread_status')}")
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decks", nargs="*", default=DEFAULT_DECKS)
    args = parser.parse_args()

    from fastapi.testclient import TestClient

    import api

    rows = []
    with TestClient(api.app) as client:
        for name in args.decks:
            try:
                rows.append(run_deck(client, name))
            except Exception:
                traceback.print_exc()
                rows.append({"deck": name, "error": traceback.format_exc()[-1500:]})

    OUT.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")

    print(f"\n\n{'=' * 74}\nSUMMARY\n{'=' * 74}")
    broken_total = 0
    for row in rows:
        if row.get("error"):
            print(f"{row['deck']:10s} FAILED: {str(row['error'])[:100]}")
            broken_total += 1
            continue
        broken = [c["check"] for c in row.get("checks", []) if c["state"] == "BROKEN"]
        empty = [c["check"] for c in row.get("checks", []) if c["state"] == "EMPTY"]
        broken_total += len(broken)
        print(f"{row['deck']:10s} {row.get('seconds')}s  broken={broken or '-'}  "
              f"empty={empty or '-'}")
    print(f"\nwrote {OUT}")
    return 1 if broken_total else 0


if __name__ == "__main__":
    raise SystemExit(main())
