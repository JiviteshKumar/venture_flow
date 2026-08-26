"""Run the real scraped pitch decks end to end and record everything needed to
judge whether the output is true.

This is the evaluation the project has never had. Every prior deck run used a
deck written for the occasion, which can test that the pipeline executes but
cannot test whether it is right -- the author of the deck already knew the
answer. These decks were written by founders to raise real money, and the
companies' outcomes are a matter of public record, so a human can check the
tool's claim verdicts against reality.

What it records, per deck, so nothing has to be re-run to answer a question
later: the extracted text length and method, every claim the extractor pulled
out, every claim verdict with its confidence and the exact source URLs the
verdict was based on, how many sources the new relevance gate dropped and why,
the score with its evidence breakdown, the degradation flags, and the memo.

Costs Groq tokens: roughly 24,000 per deck measured, against a 200,000/day free
tier scoped to the organisation. Seven decks is about 167,000, so this is close
to a full day's budget and the script is built to resume rather than restart --
a completed deck is never re-run.

    python ml/scripts/run_real_deck_corpus.py
    python ml/scripts/run_real_deck_corpus.py --only Airbnb Uber
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: E402,F401  (Windows cp1252 guard)
from document_extractor import extract_document  # noqa: E402
from structured_extractor import extract_structured  # noqa: E402
from ventureflow_agent import run_due_diligence  # noqa: E402

DECK_DIR = ROOT / "ml" / "eval" / "decks"
OUT_PATH = ROOT / "ml" / "eval" / "real_deck_runs.json"


def _load_done() -> dict[str, dict]:
    if not OUT_PATH.exists():
        return {}
    try:
        return {row["company"]: row for row in json.loads(OUT_PATH.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(rows: dict[str, dict]) -> None:
    OUT_PATH.write_text(
        json.dumps(list(rows.values()), indent=2, default=str), encoding="utf-8"
    )


def run_one(entry: dict) -> dict:
    company = entry["company"]
    data = (DECK_DIR / entry["file"]).read_bytes()

    extracted = extract_document(entry["file"], data)
    text = (extracted.get("text") or "").strip()

    # The structured extractor is what turns slide text into the claims the
    # verifier checks, so its output is recorded verbatim. If the claims are
    # wrong, every downstream verdict is answering the wrong question, and that
    # needs to be visible in the results rather than inferred from them.
    structured = extract_structured(text)

    started = time.time()
    report = run_due_diligence(
        company_name=company,
        company_description=structured.get("description") or text[:1500],
        claims_to_verify=structured.get("claims") or [],
        filing_text=text,
        revenue=structured.get("revenue"),
        burn_rate=structured.get("burn_rate"),
        runway_months=structured.get("runway_months"),
        founders=structured.get("founders"),
        deck_date=entry.get("deck_year", ""),
    )
    elapsed = round(time.time() - started, 1)

    claims = (report.get("sections", {}).get("claims") or {}).get("details", []) or []
    return {
        "company": company,
        "source_url": entry["source_url"],
        "sha256": entry["sha256"],
        "deck_year": entry.get("deck_year", ""),
        "extracted_chars": len(text),
        "extraction_method": structured.get("_method"),
        "elapsed_s": elapsed,
        "claims_extracted": structured.get("claims") or [],
        "revenue": structured.get("revenue"),
        "founders": structured.get("founders"),
        "final_score": report.get("final_score"),
        "score_source": report.get("score_source"),
        "recommendation": report.get("recommendation"),
        "risk_level": report.get("risk_level"),
        "incomplete_analysis": report.get("incomplete_analysis"),
        "thin_evidence": report.get("thin_evidence"),
        "provider_degraded": report.get("provider_degraded"),
        "degraded_components": report.get("degraded_components"),
        "evidence_penalty": report.get("evidence_penalty"),
        "evidence_components": report.get("sections", {}).get("evidence_components"),
        "venture_score": report.get("sections", {}).get("venture_score"),
        "claim_results": [
            {
                "claim": c.get("claim"),
                "verdict": c.get("verdict"),
                "confidence": c.get("confidence"),
                "reasoning": c.get("reasoning"),
                "sources": c.get("sources", []),
                "total_sources": c.get("total_sources"),
                "sources_dropped": c.get("sources_dropped"),
                "dropped_sources": c.get("dropped_sources", []),
            }
            for c in claims
        ],
        "risk": report.get("sections", {}).get("risk"),
        "claims_summary": {k: v for k, v in (report.get("sections", {}).get("claims") or {}).items() if k != "details"},
        "memo": report.get("sections", {}).get("ai_analysis"),
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--force", action="store_true", help="re-run decks already recorded")
    args = parser.parse_args()

    manifest = json.loads((DECK_DIR / "manifest.json").read_text(encoding="utf-8"))
    rows = {} if args.force else _load_done()

    for entry in manifest:
        company = entry["company"]
        if args.only and company not in args.only:
            continue
        if company in rows:
            print(f"{company}: already recorded, skipping")
            continue

        print(f"\n{'#' * 70}\n# {company}  ({entry['extracted_chars']:,} chars)\n{'#' * 70}")
        try:
            rows[company] = run_one(entry)
        except Exception:  # noqa: BLE001
            # Record the failure instead of losing the run. A deck that breaks
            # the pipeline is a finding, and the decks that already succeeded
            # cost real quota that must not be thrown away.
            traceback.print_exc()
            rows[company] = {
                "company": company, "source_url": entry["source_url"],
                "error": traceback.format_exc()[-2000:],
                "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        _save(rows)
        print(f"  -> score {rows[company].get('final_score')} "
              f"{rows[company].get('recommendation')} "
              f"(degraded={rows[company].get('provider_degraded')})")

    _save(rows)
    print(f"\nWrote {len(rows)} runs to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
