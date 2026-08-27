"""Faithfulness evaluation for the investment memo.

The memo is the half of this product a VC partner actually reads, and until now
it was the only component with no evaluation of any kind: LLM-synthesised,
unattributed, and never measured. `ml/research/research_question.md` explicitly
excludes it from the project's claims for that reason. This closes part of that
gap.

**What this measures, precisely.** The memo restates facts the pipeline already
established -- the score and its parts, the risk level, how many claims were
checked and how many held up, each claim's confidence. Every one of those is a
number the report itself already contains, so agreement can be checked exactly,
with no LLM and no judgement. Where the memo and the structured section
disagree, the memo is wrong by construction: the section is the source, the
memo is the retelling.

This is deliberately the *cheap, exact* half of memo evaluation. It does not
attempt the harder half -- deciding whether the memo's free prose is entailed
by the retrieved evidence, which needs atomic-claim decomposition and an
entailment model (FActScore, ALCE; see `ml/research/related_work.md` §3). Those
cost LLM calls this project's free-tier quota cannot currently afford, and this
instrument needs none, so it can run over every stored report today and be
re-run on every future one for free.

**Why it is worth having anyway.** The failure it detects is the most dangerous
one this product has. A memo that says "3 claims verified" when the verifier
supported none, or quotes a score the model never produced, hands a VC a
fabricated fact in the one artifact they read closely. An exact restatement
check catches that class completely, which no amount of prose-level scoring
would do more reliably.

    python ml/scripts/eval_memo_faithfulness.py                 # all stored reports
    python ml/scripts/eval_memo_faithfulness.py --report-id 65
    python ml/scripts/eval_memo_faithfulness.py --from-file ml/eval/deck_run_smoke.json

Writes `ml/eval/memo_faithfulness_results.json`: every assertion, its memo
value, the report's own value, and the verdict, so any headline figure can be
recomputed from the artifact rather than trusted from a log line.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: F401  (imported for side effect)

OUT_PATH = ROOT / "ml" / "eval" / "memo_faithfulness_results.json"

SUPPORTED = "SUPPORTED"
CONTRADICTED = "CONTRADICTED"
ABSENT = "NOT_ASSERTED"  # the memo simply did not restate this fact


def _normalise(text: str) -> str:
    """Flatten the typography an LLM emits so regexes can match plain ASCII.

    Memos come back with en dashes, non-breaking hyphens, narrow no-break
    spaces and thin spaces inside numbers ("62 %", "36 / 100", "-14"). Left
    alone these defeat every numeric pattern below and the whole check silently
    reports "not asserted" for facts the memo plainly states -- which would be
    the worst outcome for an instrument whose job is to notice disagreement.
    """
    text = unicodedata.normalize("NFKC", text)
    for dash in "‐‑‒–—―−":
        text = text.replace(dash, "-")
    for space in "    ":
        text = text.replace(space, " ")
    return text


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _assert(kind: str, memo_value, expected, snippet: str, *, tol: float = 0.0) -> dict:
    """One checked assertion, with the tolerance policy stated per kind."""
    if memo_value is None:
        verdict = ABSENT
    elif isinstance(memo_value, str) or isinstance(expected, str):
        verdict = SUPPORTED if str(memo_value).strip().lower() == str(expected).strip().lower() else CONTRADICTED
    else:
        verdict = SUPPORTED if abs(memo_value - expected) <= tol else CONTRADICTED
    return {
        "kind": kind,
        "memo_value": memo_value,
        "report_value": expected,
        "verdict": verdict,
        "snippet": snippet.strip()[:180],
    }


def _line_containing(text: str, index: int) -> str:
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    return text[start: end if end != -1 else len(text)]


def _search(pattern: str, text: str, *, allow_table: bool = False) -> tuple[str | None, str]:
    """First match that is a statement about *this* report, not a table cell.

    Markdown tables are where this check goes wrong if left alone, and every
    early false positive came from one. These memos tabulate per-claim rows and
    per-comparable rows, so a naive search finds "90 %" on a REFUTED claim's row
    and reads it as the refuted *count*; finds "| **High** |" in a risk table and
    reads it as the score's confidence band; finds another company's "Risk score
    30 / 100" in a comps table and reads it as this company's. Every one of
    those was scored as the memo contradicting the report when the memo was
    right.

    A pipe in the matched line means the match sits in a table row. None of the
    facts checked here -- the headline score, its components, the risk level,
    the claim tallies -- is ever legitimately stated inside a table row in these
    memos, so skipping those lines removes the entire false-positive class
    without losing a real assertion.
    """
    for m in re.finditer(pattern, text, re.IGNORECASE):
        line = _line_containing(text, m.start())
        if not allow_table and "|" in line:
            continue
        return m.group(1), line.strip()
    return None, ""


def check_report(report: dict[str, Any]) -> dict[str, Any]:
    """Every exactly-checkable assertion in one report's memo."""
    sections = report.get("sections") or {}
    memo = _normalise(sections.get("ai_analysis") or "")
    checks: list[dict] = []

    if not memo.strip():
        return {"company": report.get("company"), "memo_chars": 0,
                "assertions": [], "note": "no memo produced"}

    vs = sections.get("venture_score") or {}
    claims = sections.get("claims") or {}
    risk = sections.get("risk") or {}

    # -- headline score. Tolerance 0.5 because the memo rounds a float to an int.
    #
    # There is deliberately no bare "N/100" fallback. The fallback memo opens
    # with "reviewed with HIGH data quality (85/100)", and a loose pattern read
    # that data-quality figure as the venture score on 25 of 38 reports --
    # every one recorded as a contradiction the memo had never made. The label
    # has to be explicit, and "data quality" is excluded by name.
    raw, snip = _search(
        r"(?:resulting score|overall score|final score|investment score"
        r"|venture(?:flow)?[- ]?score)\**\W{0,16}\**\s*(\d{1,3}(?:\.\d+)?)\s*/\s*100",
        memo)
    if raw is not None and "data quality" in snip.lower():
        raw, snip = None, ""
    expected = _f(report.get("final_score"))
    if expected is not None:
        checks.append(_assert("final_score", _f(raw), expected, snip, tol=0.5))

    # -- the score's two components, which the memo explains to the reader
    if _f(vs.get("model_only_score")) is not None:
        raw, snip = _search(r"(?:baseline|model[- ]generated|model prior)\D{0,30}(\d{1,3})\s*/\s*100", memo)
        checks.append(_assert("model_only_score", _f(raw), _f(vs["model_only_score"]), snip, tol=0.5))

    if _f(vs.get("evidence_penalty")) is not None:
        # Reported in the memo as points off a 100-scale; stored as a probability delta.
        raw, snip = _search(r"(?:evidence[- ]adjustment|evidence penalty|subtract\w*)\D{0,30}(-?\d{1,3}(?:\.\d+)?)\s*points?", memo)
        value = _f(raw)
        checks.append(_assert("evidence_penalty_points", abs(value) if value is not None else None,
                              round(_f(vs["evidence_penalty"]) * 100, 1), snip, tol=1.0))

    rng = vs.get("score_range")
    if isinstance(rng, (list, tuple)) and len(rng) == 2:
        m = re.search(r"range\D{0,12}(\d{1,3})\s*(?:-|to|–)\s*(\d{1,3})", memo, re.IGNORECASE)
        if m:
            checks.append(_assert("score_range_low", _f(m.group(1)), _f(rng[0]), m.group(0), tol=0.5))
            checks.append(_assert("score_range_high", _f(m.group(2)), _f(rng[1]), m.group(0), tol=0.5))
        else:
            checks.append(_assert("score_range_low", None, _f(rng[0]), ""))

    if vs.get("confidence"):
        raw, snip = _search(r"confidence\W{0,12}\**\s*\*?(low|medium|high)\b", memo)
        checks.append(_assert("score_confidence_band", raw, vs["confidence"], snip))

    if _f(vs.get("feature_coverage")) is not None:
        raw, snip = _search(r"(?:feature[- ]coverage|coverage)\D{0,12}(\d{1,3}(?:\.\d+)?)\s*%", memo)
        # Tolerance 1.0 point: 0.625 may be written 62% or 63%, and both are
        # honest renderings of the same number.
        checks.append(_assert("feature_coverage_pct", _f(raw),
                              round(_f(vs["feature_coverage"]) * 100, 1), snip, tol=1.0))

    if _f(vs.get("ensemble_std")) is not None:
        raw, snip = _search(r"(?:ensemble (?:spread|std|standard deviation))\D{0,12}(\d\.\d+)", memo)
        checks.append(_assert("ensemble_std", _f(raw), _f(vs["ensemble_std"]), snip, tol=0.005))

    # -- risk
    if risk.get("risk_level"):
        raw, snip = _search(r"(?:overall )?risk[- ]level\W{0,12}\**\s*\*?(LOW|MEDIUM|HIGH|CRITICAL|UNKNOWN)\b", memo)
        checks.append(_assert("risk_level", raw, risk["risk_level"], snip))
    if _f(risk.get("overall_score")) is not None:
        raw, snip = _search(r"risk score\D{0,14}(\d{1,3})", memo)
        checks.append(_assert("risk_score", _f(raw), _f(risk["overall_score"]), snip, tol=0.5))

    # -- claim bookkeeping
    for label, key in (("checked", "checked"), ("supported", "supported"),
                       ("refuted", "refuted"), ("uncertain", "uncertain")):
        if claims.get(key) is None:
            continue
        raw, snip = _search(rf"claims?\s+{label}\W{{0,12}}(\d{{1,3}})", memo)
        if raw is None:
            raw, snip = _search(rf"\b{label}\W{{0,12}}(\d{{1,3}})\b", memo)
        checks.append(_assert(f"claims_{key}", _f(raw), _f(claims[key]), snip, tol=0.0))

    # -- the check that matters most for this product.
    #
    # If the verifier supported nothing, the memo must not tell a partner that
    # anything was verified. This is the failure mode with real consequences:
    # a fabricated corroboration in the one artifact an investor reads closely.
    if claims.get("checked") and not claims.get("supported"):
        m = re.search(
            r"\b(\d+)\s+claims?\s+(?:were\s+)?(?:independently\s+)?(?:verified|confirmed|corroborated|substantiated)\b",
            memo, re.IGNORECASE)
        asserted = int(m.group(1)) if m else 0
        checks.append({
            "kind": "no_false_corroboration",
            "memo_value": asserted,
            "report_value": 0,
            "verdict": SUPPORTED if asserted == 0 else CONTRADICTED,
            "snippet": (m.group(0) if m else "memo asserts no verified claims -- correct"),
        })

    # -- comparables must be real ones the search actually returned
    comparables = (sections.get("market_comparables") or {}).get("comparables") or []
    if comparables:
        known = {c.get("name", "").lower() for c in comparables}
        # Only look inside a comparables/comps heading, so ordinary prose that
        # happens to name a company is not mistaken for a fabricated comp.
        block = re.search(r"(?:comparable|comps?\b)[^\n]*\n(.{0,900})", memo, re.IGNORECASE | re.DOTALL)
        fabricated = []
        if block:
            for candidate in re.findall(r"\b([A-Z][A-Za-z0-9]+(?:\s[A-Z][A-Za-z0-9]+)?)\b", block.group(1)):
                low = candidate.lower()
                if low in known or low in (report.get("company") or "").lower():
                    continue
                if any(low in name or name in low for name in known):
                    continue
                fabricated.append(candidate)
        checks.append({
            "kind": "no_fabricated_comparable",
            "memo_value": sorted(set(fabricated))[:6] or None,
            "report_value": sorted(known),
            # Reported, never scored. Capitalised prose produces too many
            # false positives for this to be a pass/fail signal; it is a
            # pointer for a human to look, and saying so is more useful than a
            # number nobody should trust.
            "verdict": ABSENT,
            "snippet": "capitalised tokens near a comparables heading, for manual review",
        })

    scored = [c for c in checks if c["verdict"] in (SUPPORTED, CONTRADICTED)]
    supported = sum(1 for c in scored if c["verdict"] == SUPPORTED)
    return {
        "report_id": report.get("report_id"),
        "company": report.get("company"),
        "memo_chars": len(memo),
        "n_checkable": len(scored),
        "n_supported": supported,
        "n_contradicted": len(scored) - supported,
        "faithfulness": round(supported / len(scored), 3) if scored else None,
        "assertions": checks,
    }


def load_reports(report_id: str | None, from_file: str | None, limit: int) -> list[dict]:
    if from_file:
        payload = json.loads(Path(from_file).read_text(encoding="utf-8"))
        return [payload.get("report", payload)]

    from db import close_pool, get_report, list_reports
    try:
        if report_id:
            stored = get_report(report_id)
            if not stored:
                raise SystemExit(f"No report {report_id}")
            raw = stored["raw_output"]
            raw.setdefault("company", stored.get("company"))
            raw.setdefault("report_id", report_id)
            return [raw]
        out = []
        for summary in list_reports(limit=limit):
            stored = get_report(summary["report_id"])
            if not stored or not stored.get("raw_output"):
                continue
            raw = stored["raw_output"]
            raw.setdefault("company", stored.get("company"))
            raw.setdefault("report_id", summary["report_id"])
            out.append(raw)
        return out
    finally:
        try:
            close_pool()
        except Exception:
            pass


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Measure memo faithfulness against the report's own sections.")
    parser.add_argument("--report-id")
    parser.add_argument("--from-file")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    reports = load_reports(args.report_id, args.from_file, args.limit)
    results = [check_report(r) for r in reports]
    graded = [r for r in results if r.get("n_checkable")]

    total_checkable = sum(r["n_checkable"] for r in graded)
    total_supported = sum(r["n_supported"] for r in graded)
    contradictions = [
        {"report_id": r.get("report_id"), "company": r.get("company"), **a}
        for r in graded for a in r["assertions"] if a["verdict"] == CONTRADICTED
    ]

    payload = {
        "what_this_measures": (
            "Exact agreement between the memo and the structured sections of the same "
            "report. Where they disagree the memo is wrong by construction: the section "
            "is the source and the memo is the retelling. Does NOT evaluate whether the "
            "memo's free prose is entailed by retrieved evidence -- that needs atomic "
            "claim decomposition and an entailment model (FActScore/ALCE)."
        ),
        "n_reports": len(results),
        "n_reports_with_checkable_assertions": len(graded),
        "total_assertions_checked": total_checkable,
        "total_supported": total_supported,
        "overall_faithfulness": round(total_supported / total_checkable, 4) if total_checkable else None,
        "contradictions": contradictions,
        "per_report": results,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Reports examined                 : {len(results)}")
    print(f"  with checkable assertions      : {len(graded)}")
    print(f"Assertions checked               : {total_checkable}")
    print(f"  supported                      : {total_supported}")
    print(f"  contradicted                   : {total_checkable - total_supported}")
    if total_checkable:
        print(f"OVERALL MEMO FAITHFULNESS        : {total_supported / total_checkable:.3f}")
    if contradictions:
        print(f"\n{len(contradictions)} contradiction(s):")
        for c in contradictions[:15]:
            print(f"  [{c.get('company')}] {c['kind']}: memo said {c['memo_value']!r}, "
                  f"report says {c['report_value']!r}")
    print(f"\nSaved to {args.out}")


if __name__ == "__main__":
    main()
