"""Is the memo's free prose supported by the report's own evidence?

THE HALF THAT WAS MISSING

`ml/scripts/eval_memo_faithfulness.py` already measures the *exact* half: where
the memo restates a number the report also contains -- the score, the risk level,
how many claims were checked -- agreement can be checked character by character
with no LLM and no judgement. It scored 0.9907 over 214 assertions across 38
reports. Its own docstring says plainly that it does not attempt the harder
half, and names what that would take: atomic claim decomposition and an
entailment judgement (FActScore, ALCE).

This is that harder half. It matters because the exact check only sees
assertions that happen to restate a structured field. The memo's *prose* -- "the
company has strong customer concentration risk", "the team has relevant domain
experience" -- is where a fabrication would actually live, and nothing has ever
looked at it.

METHOD

Per report, two LLM passes:

  1. **Decompose.** Extract the memo's atomic factual assertions. Only claims
     about THIS company that could be true or false -- not recommendations, not
     hedges, not generic statements about venture investing.
  2. **Adjudicate.** Give the model the report's own structured evidence --
     claim-verification verdicts, risk findings, financial state, specialist
     outputs, the score and its parts -- and ask, for each assertion, whether
     that evidence SUPPORTS it, CONTRADICTS it, or is SILENT.

SILENT is the verdict that matters and is reported separately from CONTRADICTED.
They are different failures: a contradicted assertion is the memo saying
something the report disproves; a silent one is the memo asserting something the
report never established, which is the more common and more insidious case in a
synthesised document.

WHAT THIS IS NOT

The adjudicator is the same family of model that wrote the memo, so this is not
an independent oracle -- it is a consistency check between a document and its own
source material. That is a real limitation and it is recorded in the results
file rather than left for a reader to infer. It cannot detect a fabrication that
the structured sections also contain.

Every assertion, the evidence it was compared against, and the verdict are
written to ml/eval/memo_entailment_results.json so any headline figure can be
recomputed from the artifact.

    python ml/scripts/eval_memo_entailment.py --limit 8
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: E402,F401  (Windows cp1252 guard)
from groq_client import MODEL, get_client  # noqa: E402

OUT_PATH = ROOT / "ml" / "eval" / "memo_entailment_results.json"

_DECOMPOSE = """Extract every atomic factual assertion this investment memo makes
about the company.

Include only statements that are about THIS company and could be checked as true
or false -- financials, traction, team facts, risks, market position, claim
outcomes.

EXCLUDE: the investment recommendation itself, hedges and caveats ("further
diligence is required"), generic statements about venture investing, and
anything that is purely a restatement of the memo's own structure.

Split compound sentences into separate assertions. Keep each one close to the
memo's wording.

Return ONLY JSON: {"assertions": ["...", "..."]}

MEMO:
"""

_ADJUDICATE = """You are checking whether an investment memo is supported by the
evidence in its own report.

For each assertion, decide using ONLY the evidence below:
- "SUPPORTED"    the evidence states or directly implies it
- "CONTRADICTED" the evidence states something incompatible with it
- "SILENT"       the evidence neither establishes nor contradicts it

SILENT is not a failure of the evidence -- it means the memo asserted something
its own report never established. Use it whenever the evidence simply does not
speak to the assertion. Do not reason from your own knowledge of the company or
of companies in general; only the evidence below counts.

Return ONLY JSON:
{"verdicts": [{"assertion": "...", "verdict": "SUPPORTED|CONTRADICTED|SILENT", "why": "one short sentence"}]}

EVIDENCE FROM THE REPORT:
{evidence}

ASSERTIONS TO CHECK:
{assertions}
"""


def _evidence_block(report: dict) -> str:
    sections = report.get("sections") or {}
    claims = sections.get("claims") or {}
    risk = sections.get("risk") or {}
    financial = sections.get("financial_state") or {}
    venture = sections.get("venture_score") or {}

    lines = [
        f"FINAL SCORE: {report.get('final_score')} ({report.get('score_source')})",
        f"RECOMMENDATION: {report.get('recommendation')}",
        f"RISK LEVEL: {report.get('risk_level')} (score {risk.get('overall_score')})",
        f"INCOMPLETE ANALYSIS: {report.get('incomplete_analysis')}; "
        f"THIN EVIDENCE: {report.get('thin_evidence')}; "
        f"PROVIDER DEGRADED: {report.get('provider_degraded')}",
        "",
        f"CLAIM VERIFICATION: {claims.get('checked', 0)} checked, "
        f"{claims.get('supported', 0)} supported, {claims.get('refuted', 0)} refuted, "
        f"{claims.get('uncertain', 0)} uncertain",
    ]
    for detail in (claims.get("details") or [])[:8]:
        lines.append(
            f"  - [{detail.get('verdict')}] {str(detail.get('claim'))[:160]} "
            f"(confidence {detail.get('confidence')}) :: "
            f"{str(detail.get('reasoning'))[:200]}"
        )

    lines += ["", "RISK FINDINGS:"]
    for key in ("key_concerns", "red_flags", "positive_factors"):
        values = risk.get(key) or []
        lines.append(f"  {key}: {'; '.join(str(v) for v in values)[:400] or 'none recorded'}")

    if financial:
        stated = {k: v for k, v in financial.items() if v is not None and k != "evidence"}
        lines += ["", f"FINANCIAL STATE (parsed from the deck): {json.dumps(stated, default=str)[:500]}"]

    if venture.get("available"):
        lines += ["", f"MODEL SCORE: {venture.get('venture_score')}/100, "
                      f"model-only {venture.get('model_only_score')}, "
                      f"evidence penalty {venture.get('evidence_penalty')}, "
                      f"confidence {venture.get('confidence')}"]

    for name in ("market", "team", "bull_case", "bear_case"):
        agent = sections.get(name) or {}
        if not agent:
            continue
        signals = agent.get("signals") or agent.get("capabilities") or []
        rendered = "; ".join(
            str(s.get("finding") or s.get("area") or "")[:100] for s in signals[:4]
        )
        lines.append(f"  SPECIALIST {name}: confidence {agent.get('confidence')} :: {rendered[:300]}")

    return "\n".join(lines)


# Groq's free tier allows 8,000 tokens per MINUTE, which is the binding
# constraint here rather than the daily cap. Each report costs two calls whose
# prompts and completions together approach that ceiling, so firing them back to
# back rate-limits every one -- as the first run of this script did, failing all
# seven reports while the daily budget was untouched (7,923 of 8,000 tokens
# remaining at the time).
#
# Pacing on the published per-minute budget rather than a fixed sleep, because
# the cost per report varies with memo length.
TOKENS_PER_MINUTE = 8000
_last_call_at = 0.0
_tokens_this_window = 0
_window_started_at = 0.0


def _throttle(estimated_tokens: int) -> None:
    """Wait until `estimated_tokens` fits inside the per-minute budget."""
    global _tokens_this_window, _window_started_at
    now = time.time()
    if now - _window_started_at >= 60:
        _window_started_at, _tokens_this_window = now, 0
    if _tokens_this_window + estimated_tokens > TOKENS_PER_MINUTE * 0.85:
        wait = max(0.0, 60 - (now - _window_started_at)) + 1.0
        print(f"      [pacing {wait:.0f}s for the per-minute token budget]",
              flush=True)
        time.sleep(wait)
        _window_started_at, _tokens_this_window = time.time(), 0


def _call_json(prompt: str, max_tokens: int) -> tuple[dict, int]:
    global _tokens_this_window

    estimated = len(prompt) // 4 + max_tokens
    for attempt in range(4):
        _throttle(estimated)
        try:
            response = get_client().chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=max_tokens,
            )
        except Exception as exc:  # noqa: BLE001
            if "rate" not in f"{type(exc).__name__}{exc}".lower() or attempt == 3:
                raise
            # Wait out the window rather than hammering it.
            print(f"      [rate limited; waiting 62s, attempt {attempt + 1}/3]", flush=True)
            time.sleep(62)
            _window_started_at_reset = time.time()
            globals()["_window_started_at"] = _window_started_at_reset
            _tokens_this_window = 0
            continue

        raw = (response.choices[0].message.content or "{}").strip()
        used = response.usage.total_tokens if response.usage else estimated
        _tokens_this_window += used
        try:
            return json.loads(raw), used
        except json.JSONDecodeError:
            return {}, used
    return {}, 0


def evaluate_report(report: dict, company: str) -> dict:
    memo = ((report.get("sections") or {}).get("ai_analysis") or "").strip()
    if len(memo) < 200:
        return {"company": company, "skipped": "memo too short or absent"}

    decomposed, tokens_a = _call_json(_DECOMPOSE + memo[:3500], max_tokens=900)
    assertions = [a for a in (decomposed.get("assertions") or []) if isinstance(a, str)][:18]
    if not assertions:
        return {"company": company, "skipped": "no assertions extracted",
                "tokens": tokens_a}

    evidence = _evidence_block(report)
    prompt = _ADJUDICATE.replace("{evidence}", evidence[:3500]).replace(
        "{assertions}", json.dumps(assertions, indent=1)[:2000]
    )
    adjudicated, tokens_b = _call_json(prompt, max_tokens=1500)
    verdicts = [v for v in (adjudicated.get("verdicts") or []) if isinstance(v, dict)]

    counts = {"SUPPORTED": 0, "CONTRADICTED": 0, "SILENT": 0}
    for verdict in verdicts:
        label = str(verdict.get("verdict", "")).upper()
        if label in counts:
            counts[label] += 1

    total = sum(counts.values())
    return {
        "company": company,
        "memo_chars": len(memo),
        "n_assertions_extracted": len(assertions),
        "n_adjudicated": total,
        "counts": counts,
        "supported_rate": round(counts["SUPPORTED"] / total, 4) if total else None,
        "verdicts": verdicts,
        "evidence_used": evidence,
        "tokens": tokens_a + tokens_b,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--from-file", default=str(ROOT / "ml" / "eval" / "real_deck_runs.json"))
    parser.add_argument("--token-budget", type=int, default=45000,
                        help="stop before exceeding this many Groq tokens")
    args = parser.parse_args()

    source = Path(args.from_file)
    if not source.exists():
        print(f"{source} not found.")
        return 2
    rows = json.loads(source.read_text(encoding="utf-8"))

    results, spent = [], 0
    for row in rows[: args.limit]:
        company = row.get("company", "?")
        # real_deck_runs rows are flattened; rebuild the shape evaluate_report wants.
        report = {
            "final_score": row.get("final_score"),
            "score_source": row.get("score_source"),
            "recommendation": row.get("recommendation"),
            "risk_level": row.get("risk_level"),
            "incomplete_analysis": row.get("incomplete_analysis"),
            "thin_evidence": row.get("thin_evidence"),
            "provider_degraded": row.get("provider_degraded"),
            "sections": {
                "ai_analysis": row.get("memo"),
                "claims": {**(row.get("claims_summary") or {}),
                           "details": row.get("claim_results") or []},
                "risk": row.get("risk") or {},
                "financial_state": (row.get("risk") or {}).get("financial_state") or {},
                "venture_score": row.get("venture_score") or {},
            },
        }
        if spent >= args.token_budget:
            print(f"Stopping: token budget {args.token_budget:,} reached after "
                  f"{len(results)} report(s).")
            break

        print(f"[{len(results) + 1}] {company} ...", end=" ", flush=True)
        try:
            outcome = evaluate_report(report, company)
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED ({type(exc).__name__})")
            results.append({"company": company, "error": f"{type(exc).__name__}: {exc}"[:300]})
            continue
        spent += outcome.get("tokens", 0)
        results.append(outcome)
        if outcome.get("skipped"):
            print(f"skipped ({outcome['skipped']})")
        else:
            c = outcome["counts"]
            print(f"{c['SUPPORTED']} supported / {c['SILENT']} silent / "
                  f"{c['CONTRADICTED']} contradicted  [{spent:,} tokens]")

    scored = [r for r in results if r.get("n_adjudicated")]
    totals = {"SUPPORTED": 0, "CONTRADICTED": 0, "SILENT": 0}
    for r in scored:
        for k in totals:
            totals[k] += r["counts"][k]
    grand = sum(totals.values())

    print("\n" + "=" * 74)
    print(f"Reports scored          : {len(scored)}")
    print(f"Assertions adjudicated  : {grand}")
    if grand:
        print(f"  SUPPORTED             : {totals['SUPPORTED']} ({totals['SUPPORTED']/grand:.1%})")
        print(f"  SILENT (unsupported)  : {totals['SILENT']} ({totals['SILENT']/grand:.1%})")
        print(f"  CONTRADICTED          : {totals['CONTRADICTED']} ({totals['CONTRADICTED']/grand:.1%})")
    print(f"Groq tokens spent       : {spent:,}")
    print("=" * 74)

    OUT_PATH.write_text(json.dumps({
        "what_this_measures": (
            "Whether the memo's PROSE assertions are entailed by the report's own "
            "structured evidence. Complements eval_memo_faithfulness.py, which "
            "checks exact restatement of numeric fields and scored 0.9907."
        ),
        "limitation": (
            "The adjudicator is the same model family that wrote the memo, so this "
            "is a consistency check between a document and its own source material, "
            "not an independent oracle. It cannot detect a fabrication that the "
            "structured sections also contain."
        ),
        "verdict_meanings": {
            "SUPPORTED": "the report's evidence states or directly implies it",
            "CONTRADICTED": "the report's evidence is incompatible with it",
            "SILENT": "the memo asserted something its own report never established",
        },
        "n_reports_scored": len(scored),
        "total_assertions": grand,
        "totals": totals,
        "supported_rate": round(totals["SUPPORTED"] / grand, 4) if grand else None,
        "unsupported_rate": round((totals["SILENT"] + totals["CONTRADICTED"]) / grand, 4) if grand else None,
        "groq_tokens_spent": spent,
        "per_report": results,
    }, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
