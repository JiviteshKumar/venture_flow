"""
Run a folder of pitch decks through the live VentureFlow API and report how
the product actually behaves on them.

This deliberately drives the real HTTP endpoints rather than importing
`ventureflow_agent` directly, because the point is to exercise everything a
real user's upload touches: multipart handling, PDF extraction, the
schema-validated LLM extractor, the background job queue, Neon persistence,
and the score model. Calling the Python functions directly would skip most of
the surface area where this product has historically broken.

Runs sequentially on purpose. The API's own rate limiter defaults to 30
requests/minute and Groq has its own quota; hammering it in parallel would
measure the rate limiter rather than the product.

Usage:
    python scripts/batch_deck_test.py <folder-of-pdfs> [--api http://localhost:8000]

Writes results to ml/eval/deck_batch_results.json and prints a summary table.
Any single deck failing is recorded and the run continues -- a batch test that
aborts on the first error tells you about one deck instead of twenty.
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

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "ml" / "eval" / "deck_batch_results.json"

POLL_INTERVAL_S = 5
JOB_TIMEOUT_S = 600          # analysis is documented as 2-4 minutes
PACE_BETWEEN_DECKS_S = 2


def _post_multipart(url: str, file_path: Path, fields: dict[str, str]) -> dict:
    """Minimal multipart/form-data POST, so this script needs no extra deps."""
    boundary = uuid.uuid4().hex
    body = bytearray()
    for key, value in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
        body += f"{value}\r\n".encode()
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/pdf"
    body += f"--{boundary}\r\n".encode()
    body += (
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    body += file_path.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode()

    request = urllib.request.Request(
        url, data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read())


def _post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=120) as response:
        return json.loads(response.read())


def _describe_http_error(exc: urllib.error.HTTPError) -> str:
    try:
        detail = json.loads(exc.read()).get("detail", "")
    except Exception:
        detail = ""
    return f"HTTP {exc.code} {detail}".strip()


def run_deck(api: str, pdf: Path) -> dict:
    result: dict = {"deck": pdf.name, "ok": False, "stage": "start"}
    started = time.time()
    company = pdf.stem.replace("_", " ")

    # ── 1. Upload + extract ────────────────────────────────────────────
    try:
        result["stage"] = "upload"
        upload = _post_multipart(f"{api}/upload-pdf", pdf, {"company_name": company})
    except urllib.error.HTTPError as exc:
        result["error"] = f"upload failed: {_describe_http_error(exc)}"
        result["elapsed_s"] = round(time.time() - started, 1)
        return result
    except Exception as exc:
        result["error"] = f"upload failed: {type(exc).__name__}: {exc}"
        result["elapsed_s"] = round(time.time() - started, 1)
        return result

    extracted_text = upload.get("extracted_text") or ""
    claims = upload.get("detected_claims") or []
    result["extraction"] = {
        "method": upload.get("extraction_method"),
        "page_count": upload.get("page_count"),
        "text_chars": len(extracted_text),
        "claims_detected": len(claims),
        "revenue": upload.get("revenue"),
        "runway_months": upload.get("runway_months"),
        "description_chars": len(upload.get("company_description") or ""),
    }

    # ── 2. Queue the analysis ──────────────────────────────────────────
    try:
        result["stage"] = "analyze-submit"
        job = _post_json(f"{api}/analyze", {
            "company_name": company,
            "company_description": upload.get("company_description") or "",
            "claims": claims,
            "filing_text": extracted_text,
            "revenue": upload.get("revenue"),
            "burn_rate": None,
            "runway_months": upload.get("runway_months"),
        })
    except urllib.error.HTTPError as exc:
        result["error"] = f"analyze submit failed: {_describe_http_error(exc)}"
        result["elapsed_s"] = round(time.time() - started, 1)
        return result
    except Exception as exc:
        result["error"] = f"analyze submit failed: {type(exc).__name__}: {exc}"
        result["elapsed_s"] = round(time.time() - started, 1)
        return result

    job_id = job.get("job_id")
    result["job_id"] = job_id

    # ── 3. Poll to completion ──────────────────────────────────────────
    result["stage"] = "analyze-poll"
    deadline = time.time() + JOB_TIMEOUT_S
    status = job
    while status.get("status") in ("pending", "running"):
        if time.time() > deadline:
            result["error"] = f"job timed out after {JOB_TIMEOUT_S}s (last status {status.get('status')})"
            result["elapsed_s"] = round(time.time() - started, 1)
            return result
        time.sleep(POLL_INTERVAL_S)
        try:
            status = _get_json(f"{api}/analyze/status/{job_id}")
        except Exception as exc:
            result["error"] = f"status poll failed: {type(exc).__name__}: {exc}"
            result["elapsed_s"] = round(time.time() - started, 1)
            return result

    if status.get("status") != "complete" or not status.get("report"):
        result["error"] = f"job {status.get('status')}: {status.get('error') or 'no report returned'}"
        result["elapsed_s"] = round(time.time() - started, 1)
        return result

    # ── 4. Record what the product actually produced ───────────────────
    report = status["report"]
    sections = report.get("sections") or {}
    venture = sections.get("venture_score") or {}
    risk = sections.get("risk") or {}

    result.update({
        "ok": True,
        "stage": "done",
        "report_id": report.get("report_id"),
        "final_score": report.get("final_score"),
        "score_source": report.get("score_source"),
        "recommendation": report.get("recommendation"),
        "risk_level": report.get("risk_level"),
        "incomplete_analysis": report.get("incomplete_analysis"),
        "claims": {
            "verified": report.get("claims_verified"),
            "supported": report.get("claims_supported"),
            "refuted": report.get("claims_refuted"),
            "uncertain": report.get("claims_uncertain"),
        },
        "venture_score": {
            "available": venture.get("available"),
            "reason": venture.get("reason"),
            "score": venture.get("venture_score"),
            "model_only": venture.get("model_only_score"),
            "evidence_penalty": venture.get("evidence_penalty"),
            "range": venture.get("score_range"),
            "confidence": venture.get("confidence"),
            "coverage": venture.get("feature_coverage"),
        },
        "risk_signals": risk.get("total_signals"),
        "memo_chars": len(sections.get("ai_analysis") or ""),
        "memo_explains_score": "VENTUREFLOW SCORE" in (sections.get("ai_analysis") or "").upper(),
        "elapsed_s": round(time.time() - started, 1),
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", help="folder containing pitch-deck PDFs")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--limit", type=int, default=0, help="only run the first N decks")
    args = parser.parse_args()

    folder = Path(args.folder)
    decks = sorted(folder.glob("*.pdf"))
    if args.limit:
        decks = decks[: args.limit]
    if not decks:
        print(f"No PDFs found in {folder}")
        return 1

    try:
        health = _get_json(f"{args.api}/health")
    except Exception as exc:
        print(f"Cannot reach the API at {args.api}: {exc}")
        return 1
    print(f"API health: {health}")
    print(f"Running {len(decks)} decks sequentially...\n")

    results = []
    for index, pdf in enumerate(decks, 1):
        print(f"[{index}/{len(decks)}] {pdf.name} ... ", end="", flush=True)
        outcome = run_deck(args.api, pdf)
        results.append(outcome)
        if outcome["ok"]:
            venture = outcome["venture_score"]
            print(
                f"OK  score={outcome['final_score']} ({outcome['recommendation']}) "
                f"model={venture.get('score')} conf={venture.get('confidence')} "
                f"claims={outcome['claims']['verified']} {outcome['elapsed_s']}s"
            )
        else:
            print(f"FAIL [{outcome['stage']}] {outcome.get('error')}")
        time.sleep(PACE_BETWEEN_DECKS_S)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "api": args.api,
        "folder": str(folder),
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_decks": len(decks),
        "n_ok": sum(1 for r in results if r["ok"]),
        "results": results,
    }, indent=2), encoding="utf-8")

    ok = [r for r in results if r["ok"]]
    print(f"\n{'='*74}")
    print(f"Completed: {len(ok)}/{len(decks)}")
    if ok:
        scores = [r["final_score"] for r in ok if r.get("final_score") is not None]
        model_ok = sum(1 for r in ok if r["venture_score"].get("available"))
        explains = sum(1 for r in ok if r.get("memo_explains_score"))
        capped = sum(1 for r in ok if r.get("incomplete_analysis"))
        print(f"Model score available:      {model_ok}/{len(ok)}")
        print(f"Memo explains the score:    {explains}/{len(ok)}")
        print(f"Capped (incomplete):        {capped}/{len(ok)}")
        if scores:
            print(f"Final score: min={min(scores)} max={max(scores)} "
                  f"mean={sum(scores)/len(scores):.1f}")
        print(f"Mean runtime: {sum(r['elapsed_s'] for r in ok)/len(ok):.0f}s")
    for r in results:
        if not r["ok"]:
            print(f"  FAILED {r['deck']}: [{r['stage']}] {r.get('error')}")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
