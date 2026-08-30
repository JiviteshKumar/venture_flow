"""Run one real deck through `run_due_diligence` and dump the report.

`scripts/run_single_deck.py` drives the live HTTP API and needs a running
server plus Neon. This calls the report producer in-process instead, because
what has to be demonstrated here is the CONTENT of the report -- that
extraction coverage is present, that the input-completeness block is labelled
so it cannot be read as parsing completeness, and that the scoring fields are
still there and still populated -- none of which depends on the transport.

    python scripts/run_report_end_to_end.py ml/eval/decks/Uber.pdf --company Uber
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: F401,E402
import pdf_extractor  # noqa: E402
import structured_extractor  # noqa: E402
from ventureflow_agent import run_due_diligence  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("deck")
    ap.add_argument("--company", required=True)
    ap.add_argument("--deck-date", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    path = Path(args.deck)
    raw = path.read_bytes()
    text = pdf_extractor.extract_text_from_pdf(raw)
    pages = pdf_extractor.extract_pages_from_pdf(raw)
    print(f"{args.company}: {len(pages)} pages, {len(text)} chars\n")

    info = structured_extractor.extract_structured(text, args.company)
    print(f"extraction method: {info.get('_method')}")
    print(f"claims extracted:  {len(info.get('claims') or [])}")
    print(f"founders in deck:  {[f.get('name') for f in (info.get('founders') or [])]}\n")

    report = run_due_diligence(
        company_name=args.company,
        company_description=info.get("description", ""),
        claims_to_verify=info.get("claims") or [],
        filing_text=text,
        revenue=info.get("revenue"),
        burn_rate=info.get("burn_rate"),
        runway_months=info.get("runway_months"),
        sector=info.get("sector"),
        team_size=info.get("team_size"),
        github_url=info.get("github_url"),
        founders=[f["name"] for f in (info.get("founders") or [])],
        stage=info.get("stage") or "",
        deck_date=args.deck_date,
        deck_slides=pages,
        extraction_method=info.get("_method", ""),
        extraction_fallback_reason=info.get("_fallback_reason", "") or "",
    )

    out = Path(args.out) if args.out else ROOT / "ml" / "eval" / f"report_{args.company}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
