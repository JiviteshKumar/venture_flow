"""Re-run the real deck corpus through the fixed extraction path and diff it
against what the pipeline produced before the fix.

The "before" side is not a reconstruction from memory and not a description of
what the old code would have done. It is the old code: the pre-fix
`pdf_extractor.py` and `structured_extractor.py` are checked out from git into
a scratch directory and imported from there, so the comparison is between two
executables rather than between an executable and a claim about one.

That matters here specifically. The defect being measured was invisible in the
old code's OUTPUT -- an empty result is what a thin deck produces too -- so any
"before" column written by hand would be the same guess that let the bug
survive a manual audit.

Token cost is deliberate. This runs the extraction and founder paths, which is
what Sections A-C changed, and not the specialist agents, memo synthesis or
web-based claim verification, which they did not. On this account's free tier
the full pipeline costs 24-50k tokens per deck against a 200k daily ceiling, so
running all of it for every deck would exhaust the day's budget before the
corpus was half done and would measure mostly unchanged code.

    python scripts/run_section_d.py --decks ml/eval/decks --out ml/eval/section_d_results.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: F401,E402
import extraction_coverage  # noqa: E402
import pdf_extractor  # noqa: E402
import structured_extractor  # noqa: E402

BASELINE_FILES = ("pdf_extractor.py", "structured_extractor.py", "deck_metadata.py")


def materialise_baseline(ref: str) -> Path:
    """Check the pre-fix extractors out of git so they can actually be run."""
    tmp = Path(tempfile.mkdtemp(prefix="vf_baseline_"))
    for name in BASELINE_FILES:
        blob = subprocess.run(
            ["git", "show", f"{ref}:{name}"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        if blob.returncode != 0:
            raise SystemExit(f"could not read {name} at {ref}: {blob.stderr[:200]}")
        (tmp / name).write_text(blob.stdout, encoding="utf-8")
    return tmp


BASELINE_RUNNER = r'''
import json, sys
sys.path.insert(0, sys.argv[1])   # baseline extractors first
sys.path.append(sys.argv[2])      # then the repo, for shared deps
import pdf_extractor as pe
raw = open(sys.argv[3], "rb").read()
text = pe.extract_text_from_pdf(raw)
out = {
    "claims": pe.extract_claims_from_text(text),
    "founders": pe.extract_founders(text),
    "description": pe.extract_company_info(text).get("description", ""),
}
sys.stdout.write("<<<JSON>>>" + json.dumps(out))
'''


def run_baseline(baseline_dir: Path, pdf_path: Path) -> dict:
    """Run the OLD extractors in their own process.

    Separate process because both versions define the same module names; two
    `pdf_extractor`s cannot coexist in one interpreter without import games
    that would themselves become a source of doubt about the result.
    """
    script = baseline_dir / "_runner.py"
    script.write_text(BASELINE_RUNNER, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script), str(baseline_dir), str(ROOT), str(pdf_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    marker = "<<<JSON>>>"
    if marker not in proc.stdout:
        return {"error": (proc.stderr or proc.stdout)[-400:], "claims": [], "founders": []}
    return json.loads(proc.stdout.split(marker, 1)[1])


def analyse(company: str, pdf_path: Path, baseline_dir: Path, do_founders: bool) -> dict:
    raw = pdf_path.read_bytes()
    text = pdf_extractor.extract_text_from_pdf(raw)
    pages = pdf_extractor.extract_pages_from_pdf(raw)

    record: dict = {
        "company": company,
        "file": pdf_path.name,
        "bytes": len(raw),
        "pages": len(pages),
        "extracted_chars": len(text),
    }

    # An image-only deck is a finding, not a failure, and it must not be
    # allowed to look like a thin deck.
    if len(text.strip()) < 50:
        record["status"] = "IMAGE_ONLY"
        record["note"] = (
            f"{len(pages)} page(s) read, {len(text.strip())} characters of text. "
            f"Every page is a slide image with no text layer; VentureFlow has no "
            f"OCR path, so nothing can be extracted. This is a property of the "
            f"file, not of the deck's content."
        )
        return record

    record["status"] = "ANALYSED"

    before = run_baseline(baseline_dir, pdf_path)
    after = structured_extractor.extract_structured(text, company)

    cov_before = extraction_coverage.compute(text, before, pages)
    cov_after = extraction_coverage.compute(text, after, pages)

    record["before"] = {
        "method": "regex_fallback (the LLM path raised NameError on every call)",
        "claims": before.get("claims", []),
        "claim_count": len(before.get("claims", [])),
        "founders": before.get("founders", []),
        "coverage_pct": cov_before.get("coverage_pct"),
        "coverage_verdict": cov_before.get("verdict"),
        "slides_represented": f"{cov_before.get('represented_slides')}/{cov_before.get('content_slides')}",
    }
    record["after"] = {
        "method": after.get("_method"),
        "fallback_reason": after.get("_fallback_reason", ""),
        "claims": after.get("claims", []),
        "claim_count": len(after.get("claims", [])),
        "founders": after.get("founders", []),
        "revenue": after.get("revenue"),
        "burn_rate": after.get("burn_rate"),
        "runway_months": after.get("runway_months"),
        "description": after.get("description", "")[:300],
        "coverage_pct": cov_after.get("coverage_pct"),
        "coverage_verdict": cov_after.get("verdict"),
        "slides_represented": f"{cov_after.get('represented_slides')}/{cov_after.get('content_slides')}",
        "unrepresented_slides": cov_after.get("unrepresented_slides", []),
    }
    record["diff"] = {
        "claims_gained": len(after.get("claims", [])) - len(before.get("claims", [])),
        "coverage_delta_pct": round(
            (cov_after.get("coverage_pct") or 0) - (cov_before.get("coverage_pct") or 0), 1
        ),
        "new_claims": [c for c in after.get("claims", []) if c not in before.get("claims", [])],
    }

    # ── Founder handling: deck-disclosed vs researched ──
    deck_founders = after.get("founders") or []
    if deck_founders:
        record["founder_handling"] = {
            "origin": "deck",
            "names": [f.get("name") for f in deck_founders],
            "note": "Named in the deck text; no external search required.",
        }
    elif do_founders:
        from agents.founder_research import discover_founders

        discovery = discover_founders(
            company, deck_date=str(record.get("deck_year") or ""), context=text[:400]
        )
        record["founder_handling"] = {
            "origin": "external_research",
            "search_fired": True,
            "found": discovery.get("found"),
            "names": [f["name"] for f in discovery.get("founders", [])],
            "sources": {
                f["name"]: f.get("discovery_sources", [])
                for f in discovery.get("founders", [])
            },
            "reason": discovery.get("reason", ""),
            "rejected_ungrounded": discovery.get("rejected_ungrounded", []),
        }
    else:
        record["founder_handling"] = {
            "origin": "none",
            "search_fired": False,
            "note": "Founder research skipped (--no-founders).",
        }
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--decks", default="ml/eval/decks")
    ap.add_argument("--out", default="ml/eval/section_d_results.json")
    ap.add_argument("--baseline-ref", default="HEAD")
    ap.add_argument("--only", default="")
    ap.add_argument("--no-founders", action="store_true")
    args = ap.parse_args()

    decks_dir = ROOT / args.decks
    manifest_path = decks_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"No manifest at {manifest_path}")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    only = {c.strip().lower() for c in args.only.split(",") if c.strip()}
    baseline_dir = materialise_baseline(args.baseline_ref)
    print(f"Baseline extractors checked out from {args.baseline_ref} into {baseline_dir}\n")

    results = []
    for entry in manifest:
        company = entry["company"]
        if only and company.lower() not in only:
            continue
        pdf_path = decks_dir / entry["file"]
        if not pdf_path.exists():
            print(f"{company}: file missing, skipped")
            continue

        print(f"=== {company} ===")
        started = time.time()
        record = analyse(company, pdf_path, baseline_dir, not args.no_founders)
        record["source_url"] = entry.get("source_url")
        record["sha256"] = entry.get("sha256")
        record["deck_year"] = entry.get("deck_year")
        record["seconds"] = round(time.time() - started, 1)
        results.append(record)

        if record["status"] == "IMAGE_ONLY":
            print(f"  IMAGE-ONLY: {record['note'][:90]}")
        else:
            b, a = record["before"], record["after"]
            print(f"  claims   {b['claim_count']:>3} -> {a['claim_count']:<3} "
                  f"({record['diff']['claims_gained']:+d})")
            print(f"  coverage {b['coverage_pct']:>5}% -> {a['coverage_pct']:<5}% "
                  f"({record['diff']['coverage_delta_pct']:+}) "
                  f"[{b['coverage_verdict']} -> {a['coverage_verdict']}]")
            print(f"  slides   {b['slides_represented']} -> {a['slides_represented']}")
            fh = record["founder_handling"]
            print(f"  founders origin={fh['origin']} names={fh.get('names') or 'none'}")
        print(f"  {record['seconds']}s\n")

    out_path = ROOT / args.out
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out_path} ({len(results)} decks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
