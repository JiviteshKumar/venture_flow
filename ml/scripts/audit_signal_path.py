"""Trace every structured field from PDF text to the number a user sees.

WHY

Two bugs of the same shape have now shipped silently for the entire life of this
product:

  * `stage` was hardcoded to None in `ventureflow_agent`, discarding the score
    model's single largest lever -- 42 points of range.
  * `description` was truncated to 1,200 characters, flattening `desc_len`, a
    real model feature, to a near-constant.

Neither raised an error. Neither failed a test. Both produced plausible numbers.
The lesson is that a field being *declared* somewhere proves nothing about
whether real deck content reaches the thing that consumes it, so this walks the
whole path and reports, per field, exactly where the chain breaks:

    extractor -> upload response -> UI payload -> request model -> pipeline
    -> consumer

A field can be lost at any hop. Pydantic silently drops keys a response model
does not declare; a UI can hardcode a literal over a value it was handed; a
pipeline can accept a parameter and never pass it on. All three have happened
here.

    python ml/scripts/audit_signal_path.py
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: F401  (Windows cp1252 guard)

OUT_PATH = ROOT / "ml" / "eval" / "signal_path_audit.json"

# Fields something downstream actually consumes, and what consumes them.
CONSUMED_BY = {
    "revenue": "evidence_fusion.financial_disclosure; _evidence_components.no_revenue; deck_financials",
    "burn_rate": "evidence_fusion.financial_disclosure; deck_financials.burn_multiple",
    "runway_months": "evidence_fusion.financial_disclosure; deck_financials.runway",
    "stage": "venturescore.score_company (largest lever: 42 points of range)",
    "sector": "venturescore.score_company as `industry` (24 points of range)",
    "team_size": "accepted by the pipeline; check whether anything reads it",
    "github_url": "technical_scoring",
    "domain": "db.find_similar_companies (portfolio matching)",
    "founders": "agents.founder_verifier",
    "deck_date": "claim_verifier as_of (temporal grounding)",
    "claims": "claim_verifier",
    "company_description": "venturescore text features; all agents",
}


def _regex_extractor_fields() -> set[str]:
    from structured_extractor import _regex_fallback

    sample = (
        "Northwind Robotics - Seed Round. B2B warehouse automation SaaS. "
        "We closed $2.4M ARR, up from $310K, across 62 customers. Monthly burn "
        "$410K against $1.1M cash. Team of 14. github.com/northwind northwind.io"
    )
    return set(_regex_fallback(sample))


def _llm_extractor_fields() -> set[str]:
    from structured_extractor import ExtractedFinancials

    return set(ExtractedFinancials.model_fields)


def _model_fields(name: str) -> set[str]:
    import api

    return set(getattr(api, name).model_fields)


def _pipeline_params() -> set[str]:
    import inspect

    import ventureflow_agent

    return set(inspect.signature(ventureflow_agent.run_due_diligence).parameters)


def _ui_payload() -> dict[str, str]:
    """Parse the analyze payload the frontend actually builds.

    Parsed rather than assumed: the UI hardcoded `burn_rate: null` over a value
    the extractor produces, and no Python-side check could have seen that.
    """
    source = (ROOT / "frontend" / "src" / "context" / "AppContext.tsx").read_text(
        encoding="utf-8", errors="replace"
    )
    match = re.search(r"startAnalysis\(\{(.*?)\n\s*\}\)", source, re.DOTALL)
    if not match:
        return {}
    body = match.group(1)
    fields: dict[str, str] = {}
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("//") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", key):
            continue
        fields[key] = value.strip().rstrip(",") or "(multiline)"
    return fields


def _pipeline_forwards(field: str) -> bool:
    """Does run_due_diligence pass this parameter onward, or accept and drop it?"""
    source = (ROOT / "ventureflow_agent.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run_due_diligence":
            body = ast.get_source_segment(source, node) or ""
            # Used anywhere other than the signature line itself.
            uses = len(re.findall(rf"\b{re.escape(field)}\b", body))
            return uses > 1
    return False


def main() -> int:
    regex_fields = _regex_extractor_fields()
    llm_fields = _llm_extractor_fields()
    upload_response = _model_fields("PDFExtractResponse")
    request = _model_fields("DiligenceRequest")
    pipeline = _pipeline_params()
    ui = _ui_payload()

    rows = []
    for field, consumer in sorted(CONSUMED_BY.items()):
        # Several fields travel under a different name at each hop, and getting
        # this wrong produces a false "broken chain" -- an inaccurate audit is
        # itself the kind of overclaim this file exists to catch.
        extractor_alias = {
            "company_description": "description",
            "claims": "claims",
            "founders": "founders",
        }.get(field, field)
        upload_alias = {
            "claims": "detected_claims",
            "founders": "detected_founders",
            "company_description": "company_description",
        }.get(field, field)
        pipeline_name = {"claims": "claims_to_verify"}.get(field, field)

        extracted = (
            field in regex_fields or field in llm_fields
            or extractor_alias in regex_fields or extractor_alias in llm_fields
        )
        in_upload = field in upload_response or upload_alias in upload_response
        ui_value = ui.get(field)
        ui_sends = ui_value is not None
        ui_hardcoded = ui_sends and ui_value.strip() in {"null", "0", '""', "false", "[]"}
        in_request = field in request
        in_pipeline = pipeline_name in pipeline
        forwarded = _pipeline_forwards(pipeline_name) if in_pipeline else False

        # Where the chain first breaks.
        if field == "deck_date":
            # Derived in-pipeline by ventureflow_agent._infer_deck_vintage from
            # the deck's own text. Not extracted upstream, and that is correct:
            # the inference needs the full text, which the extractor's truncated
            # description would not carry.
            break_at = ""
        elif not extracted:
            break_at = "EXTRACTOR: nothing populates this from deck text"
        elif not in_upload:
            break_at = "UPLOAD RESPONSE: extracted but the response model drops it"
        elif not ui_sends:
            break_at = "UI: never included in the analyze payload"
        elif ui_hardcoded:
            break_at = f"UI: HARDCODED to {ui_value.strip()} over the extracted value"
        elif not in_request:
            break_at = "REQUEST MODEL: no such field"
        elif field == "domain":
            # Consumed in the API layer by find_similar_companies rather than
            # inside run_due_diligence, so "not a pipeline parameter" is correct
            # and not a break. Verified against api._perform_analysis.
            break_at = ""
        elif not in_pipeline:
            break_at = "PIPELINE: not a parameter"
        elif not forwarded:
            break_at = "PIPELINE: accepted but never used"
        else:
            break_at = ""

        rows.append({
            "field": field,
            "consumed_by": consumer,
            "extracted": extracted,
            "in_upload_response": in_upload,
            "ui_sends": ui_sends,
            "ui_value": ui_value,
            "ui_hardcoded": ui_hardcoded,
            "in_request_model": in_request,
            "in_pipeline": in_pipeline,
            "pipeline_forwards": forwarded,
            "breaks_at": break_at,
            "reaches_consumer": not break_at,
        })

    broken = [r for r in rows if r["breaks_at"]]

    print("=" * 92)
    print("SIGNAL PATH AUDIT -- does real deck content reach what consumes it?")
    print("=" * 92)
    header = f"{'field':<20}{'extr':>5}{'upl':>5}{'ui':>4}{'req':>5}{'pipe':>6}{'fwd':>5}  breaks at"
    print(header)
    print("-" * 92)
    for r in rows:
        def mark(value: bool) -> str:
            return " ok " if value else " -- "
        print(f"{r['field']:<20}{mark(r['extracted']):>5}{mark(r['in_upload_response']):>5}"
              f"{mark(r['ui_sends']):>4}{mark(r['in_request_model']):>5}"
              f"{mark(r['in_pipeline']):>6}{mark(r['pipeline_forwards']):>5}  "
              f"{r['breaks_at'][:44]}")
    print("-" * 92)
    print(f"{len(rows) - len(broken)}/{len(rows)} consumed fields reach their consumer "
          f"from a real upload.")

    if broken:
        print("\nBROKEN CHAINS, in the order a fix would matter:")
        for r in broken:
            print(f"  * {r['field']}")
            print(f"      consumed by : {r['consumed_by']}")
            print(f"      breaks at   : {r['breaks_at']}")

    OUT_PATH.write_text(json.dumps({
        "what_this_checks": (
            "Whether each structured field the scoring model or report consumes "
            "actually carries real deck content from a real upload, hop by hop: "
            "extractor -> upload response -> UI payload -> request model -> "
            "pipeline -> consumer. A field can be lost at any hop, and all three "
            "of 'response model drops it', 'UI hardcodes a literal over it' and "
            "'pipeline accepts and never uses it' have happened in this codebase."
        ),
        "n_fields": len(rows),
        "n_reaching_consumer": len(rows) - len(broken),
        "n_broken": len(broken),
        "fields": rows,
    }, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
