"""Run one deck end to end through the live API and print the sections that
matter for a specific fix.

`scripts/batch_deck_test.py` already exists for running a folder of decks and
recording aggregate behaviour. This is the single-deck counterpart used when
verifying one change: it drives the same real HTTP endpoints (multipart upload,
extraction, the background job queue, Neon persistence) and then dumps the
report sections by name, so "the Founder Analysis tab is fixed" can be checked
against the actual bytes the frontend receives rather than against a screenshot.

    python scripts/run_single_deck.py <deck-file> [--api http://localhost:8000]
        [--company NAME] [--sections founder_verification market_comparables team]
        [--out ml/eval/deck_run_<name>.json]

Accepts any format /upload-document accepts, not just PDF.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: F401  (imported for side effect)

POLL_INTERVAL_S = 5
JOB_TIMEOUT_S = 900


def _multipart(file_path: Path, company: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    body = b"".join([
        f'--{boundary}\r\nContent-Disposition: form-data; name="company_name"\r\n\r\n{company}\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        file_path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    return body, f"multipart/form-data; boundary={boundary}"


def _request(url: str, data: bytes | None = None, content_type: str = "application/json") -> dict:
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=310) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{url} -> HTTP {exc.code}: {exc.read().decode()[:500]}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deck")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--company", default=None)
    parser.add_argument("--sections", nargs="*", default=["founder_verification", "market_comparables", "team"])
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    deck = Path(args.deck)
    if not deck.exists():
        raise SystemExit(f"No such file: {deck}")
    company = args.company or deck.stem.replace("_", " ")

    print(f"Uploading {deck.name} as {company!r} ...")
    body, content_type = _multipart(deck, company)
    upload = _request(f"{args.api}/upload-document", body, content_type)
    founders = [f["name"] for f in upload.get("detected_founders", [])]
    print(f"  format={upload.get('document_format')} pages={upload.get('page_count')} "
          f"method={upload.get('extraction_method')} chars={len(upload.get('extracted_text', ''))}")
    print(f"  claims detected: {len(upload.get('detected_claims', []))}")
    print(f"  founders detected: {founders or 'none'}")

    payload = {
        "company_name": company,
        "company_description": upload.get("company_description", ""),
        "claims": upload.get("detected_claims", []),
        "filing_text": upload.get("extracted_text", ""),
        "revenue": upload.get("revenue"),
        "burn_rate": None,
        "runway_months": upload.get("runway_months"),
        "founders": founders,
    }
    print("\nStarting analysis ...")
    job = _request(f"{args.api}/analyze", json.dumps(payload).encode())
    job_id = job["job_id"]

    started = time.time()
    status = job
    while status.get("status") in ("pending", "running"):
        if time.time() - started > JOB_TIMEOUT_S:
            raise SystemExit(f"Job {job_id} did not finish within {JOB_TIMEOUT_S}s")
        time.sleep(POLL_INTERVAL_S)
        status = _request(f"{args.api}/analyze/status/{job_id}")
        print(f"  [{int(time.time() - started):>3}s] {status.get('status')} — {status.get('stage') or '...'}")

    if status.get("status") != "complete" or not status.get("report"):
        raise SystemExit(f"Analysis failed: {status.get('error')}")

    report = status["report"]
    print(f"\nDone in {int(time.time() - started)}s. "
          f"score={report.get('final_score')} ({report.get('score_source')}) "
          f"recommendation={report.get('recommendation')} risk={report.get('risk_level')}")

    for name in args.sections:
        print("\n" + "=" * 74)
        print(f"sections.{name}")
        print("=" * 74)
        print(json.dumps(report.get("sections", {}).get(name), indent=2, ensure_ascii=False))

    out = Path(args.out) if args.out else ROOT / "ml" / "eval" / f"deck_run_{deck.stem}.json"
    out.write_text(json.dumps({"upload": upload, "report": report}, indent=2), encoding="utf-8")
    print(f"\nFull report saved to {out}")


if __name__ == "__main__":
    main()
