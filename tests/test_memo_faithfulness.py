"""Tests for the memo faithfulness evaluator.

Half of these exist because the evaluator's first run was wrong. A loose set of
patterns reported 33 contradictions across 38 reports, and every one was the
instrument misreading a markdown table or the fallback memo's data-quality
line -- not the memo contradicting anything. An evaluator that invents
contradictions is worse than none, because its output looks like evidence.

So the false-positive cases are pinned here by name. If the extraction is ever
loosened again, these fail before any number reaches a write-up.

No network, no LLM, no database: every case is a hand-built report dict.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.scripts.eval_memo_faithfulness import (
    ABSENT,
    CONTRADICTED,
    SUPPORTED,
    check_report,
)


def _report(memo: str, **overrides):
    report = {
        "company": "Testco",
        "final_score": 36.0,
        "recommendation": "NEEDS MORE DILIGENCE",
        "sections": {
            "ai_analysis": memo,
            "claims": {"checked": 5, "supported": 0, "refuted": 1, "uncertain": 4, "details": []},
            "risk": {"risk_level": "MEDIUM", "overall_score": 40.0},
            "venture_score": {
                "available": True, "venture_score": 36, "model_only_score": 50,
                "evidence_penalty": 0.14, "score_range": [24, 48],
                "confidence": "medium", "feature_coverage": 0.625, "ensemble_std": 0.0786,
            },
        },
    }
    report.update(overrides)
    return report


def _verdict(result, kind):
    for a in result["assertions"]:
        if a["kind"] == kind:
            return a["verdict"]
    raise AssertionError(f"no assertion of kind {kind}")


# ── it agrees when the memo agrees ──────────────────────────────────────────

def test_matching_memo_scores_fully_faithful():
    memo = (
        "### WHAT DRIVES THE VENTUREFLOW SCORE\n"
        "* **Model-generated baseline:** 50 / 100\n"
        "* **Evidence-adjustment:** -14 points\n"
        "* **Resulting score:** **36 / 100** (range 24-48).\n"
        "* **Confidence:** *Medium* (feature coverage 62 %; ensemble spread 0.079).\n"
    )
    r = check_report(_report(memo))
    assert r["n_contradicted"] == 0
    assert r["faithfulness"] == 1.0
    for kind in ("final_score", "model_only_score", "evidence_penalty_points",
                 "score_range_low", "score_confidence_band", "ensemble_std"):
        assert _verdict(r, kind) == SUPPORTED, kind


def test_typographic_dashes_and_spaces_do_not_defeat_matching():
    """LLM output uses en dashes and narrow no-break spaces. Left unnormalised
    every numeric check silently reports NOT_ASSERTED."""
    memo = "* **Resulting score:** **36 / 100** (range 24‑48).\n"
    r = check_report(_report(memo))
    assert _verdict(r, "final_score") == SUPPORTED
    assert _verdict(r, "score_range_high") == SUPPORTED


# ── it catches a memo that genuinely disagrees ──────────────────────────────

def test_wrong_score_is_caught():
    r = check_report(_report("* **Resulting score:** 57 / 100 (range 44-71).\n"))
    assert _verdict(r, "final_score") == CONTRADICTED


def test_false_corroboration_is_caught():
    """The failure with real consequences: telling a partner claims were
    verified when the verifier supported none."""
    memo = "Our review found that 3 claims were independently verified against public sources."
    r = check_report(_report(memo))
    assert _verdict(r, "no_false_corroboration") == CONTRADICTED


def test_no_false_corroboration_passes_when_memo_is_honest():
    memo = "None of the claims could be independently verified."
    r = check_report(_report(memo))
    assert _verdict(r, "no_false_corroboration") == SUPPORTED


# ── regressions: every one of these was a real false positive ──────────────

def test_data_quality_score_is_not_read_as_the_venture_score():
    """The fallback memo opens with 'reviewed with HIGH data quality (85/100)'.
    A bare N/100 pattern read that as the headline score on 25 of 38 reports."""
    memo = ("1. EXECUTIVE SUMMARY\nTestco has been reviewed with HIGH data quality "
            "(85/100). This memo should be treated as preliminary.\n")
    r = check_report(_report(memo))
    assert _verdict(r, "final_score") == ABSENT, (
        "the data-quality figure was mistaken for the venture score"
    )


def test_confidence_percent_in_a_claim_table_is_not_read_as_a_refuted_count():
    """'| **REFUTED** | 90 % |' was scored as refuted == 90."""
    memo = ("| # | Claim | Outcome | Confidence |\n|---|---|---|---|\n"
            "| 1 | “Claims settle in 15-30 days.” | **REFUTED** | 90 % |\n")
    r = check_report(_report(memo))
    assert _verdict(r, "claims_refuted") == ABSENT


def test_high_in_a_risk_table_is_not_read_as_the_score_confidence_band():
    """'| **High** | Absence of financial traction |' was scored as the score's
    confidence band being High against a model that said medium."""
    memo = ("### RISK ASSESSMENT\n| Severity | Risk |\n|---|---|\n"
            "| **High** | Absence of financial traction |\n")
    r = check_report(_report(memo))
    assert _verdict(r, "score_confidence_band") == ABSENT


def test_another_companys_risk_score_in_a_comps_table_is_not_read_as_ours():
    memo = ("| Company | Verdict | Score | Risk |\n|---|---|---|---|\n"
            "| Carbon Ledger | “Needs more diligence” | 65 / 100 | Risk score 30 / 100 |\n")
    r = check_report(_report(memo))
    assert _verdict(r, "risk_score") == ABSENT
    assert _verdict(r, "final_score") == ABSENT


def test_empty_memo_produces_no_assertions_rather_than_false_ones():
    r = check_report(_report(""))
    assert r["assertions"] == []
    assert r.get("note")


def test_absent_facts_are_not_counted_against_faithfulness():
    """A memo that simply does not restate a number is not unfaithful for it.
    Only SUPPORTED and CONTRADICTED enter the ratio."""
    memo = "* **Resulting score:** **36 / 100**\n"
    r = check_report(_report(memo))
    absent = [a for a in r["assertions"] if a["verdict"] == ABSENT]
    assert absent, "expected some facts to go unrestated"
    assert r["n_checkable"] == r["n_supported"] + r["n_contradicted"]
    assert r["faithfulness"] == 1.0
