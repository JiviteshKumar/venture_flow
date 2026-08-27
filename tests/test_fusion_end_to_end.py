"""A full deck run through the updated pipeline, checking the score, the memo
and the report sections all reflect the same evidence.

The specific failure this guards against: a scoring change that lands in the
number but not in what the reader sees, so the headline says one thing and the
memo narrates another. That already happened once in this project -- the memo
was synthesised from the UNCAPPED score while the product displayed the capped
one, telling a reader 57/100 on a report headlined 30.

Provider-stubbed, so it costs no quota, but everything above the provider is the
real pipeline: real fusion, real evidence components, real report assembly.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ventureflow_agent

DECK = (
    "Northwind Robotics 2011 seed deck. Warehouse automation for mid-size "
    "logistics operators. We closed $2.4M in ARR this year, up from $310K, "
    "across 62 paying customers. Monthly burn is $410K against $1.1M cash."
)


def _wire(monkeypatch, *, verdict, risk_severity, specialist_confidence, degraded=False):
    monkeypatch.setattr(ventureflow_agent, "verify_claim", lambda *a, **k: {
        "claim": "c", "verdict": verdict, "confidence": 0.8, "reasoning": "r",
        "key_evidence": "e", "sources": [], "total_sources": 3, "full_pages_read": 1,
    })
    monkeypatch.setattr(ventureflow_agent, "score_risk", lambda *a, **k: {
        "risk_level": "LOW", "overall_score": 20, "key_concerns": [],
        "positive_factors": [], "red_flags": [], "total_signals": 0,
        "disclosure_severity": risk_severity, "deck_signals": [],
    })
    specialist = {"confidence": specialist_confidence, "signals": []}
    if degraded:
        specialist = {**specialist, "_degraded": True, "_degraded_reason": "429"}
    monkeypatch.setattr(ventureflow_agent, "run_investment_agents", lambda **k: {
        "market": dict(specialist), "team": dict(specialist),
    })
    monkeypatch.setattr(ventureflow_agent, "build_context", lambda *a: {"relevant_reports": []})
    monkeypatch.setattr(ventureflow_agent, "format_context_for_llm", lambda *a: "")
    monkeypatch.setattr(ventureflow_agent, "get_client", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **_: SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="memo body"))]
            )
        ))
    ))


def _run(**kwargs):
    return ventureflow_agent.run_due_diligence(
        "Northwind Robotics", company_description=DECK,
        claims_to_verify=["We closed $2.4M in ARR.", "We have 62 customers."],
        revenue=2_400_000, burn_rate=410_000, runway_months=2.7,
        sector="B2B", deck_date="2011", **kwargs,
    )


def test_the_fusion_section_is_present_and_inspectable(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _wire(monkeypatch, verdict="SUPPORTS", risk_severity=0.05, specialist_confidence=0.85)
    report = _run(stage="Seed")

    fusion = report["sections"]["evidence_fusion"]
    assert "terms" in fusion and "features" in fusion
    assert "delta_points" in fusion
    assert fusion["bounds"]["max_positive"] == pytest.approx(0.20)
    assert fusion["bounds"]["max_negative"] == pytest.approx(-0.60)


def test_strong_and_weak_evidence_produce_different_scores(monkeypatch, tmp_path):
    """The property that matters: the same company text, different evidence,
    different number. Before this change the pipeline could prove a company
    sound and move the score 2.5 points."""
    monkeypatch.chdir(tmp_path)

    _wire(monkeypatch, verdict="SUPPORTS", risk_severity=0.05, specialist_confidence=0.9)
    strong = _run(stage="Seed")

    _wire(monkeypatch, verdict="REFUTES", risk_severity=0.9, specialist_confidence=0.2)
    weak = _run(stage="Seed")

    assert strong["final_score"] > weak["final_score"], (
        f"evidence did not move the score: strong={strong['final_score']} "
        f"weak={weak['final_score']}"
    )
    assert strong["sections"]["evidence_fusion"]["delta"] > \
        weak["sections"]["evidence_fusion"]["delta"]


def test_stage_changes_the_score(monkeypatch, tmp_path):
    """The starvation fix. Stage was hardcoded to None and is the model's
    largest single lever -- 42 points of range against 24 for industry."""
    monkeypatch.chdir(tmp_path)
    _wire(monkeypatch, verdict="SUPPORTS", risk_severity=0.1, specialist_confidence=0.7)

    scores = {stage: _run(stage=stage)["final_score"] for stage in ("Seed", "Growth")}
    assert scores["Seed"] != scores["Growth"], (
        f"stage had no effect on the score: {scores}"
    )


def test_the_memo_is_given_the_same_score_the_report_publishes(monkeypatch, tmp_path):
    """The exact inversion that already shipped once: the memo narrated a score
    the product did not display."""
    captured = {}

    def capture(**kwargs):
        captured["prompt"] = kwargs["messages"][-1]["content"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="memo body"))]
        )

    monkeypatch.chdir(tmp_path)
    _wire(monkeypatch, verdict="SUPPORTS", risk_severity=0.05, specialist_confidence=0.85)
    monkeypatch.setattr(ventureflow_agent, "get_client", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=capture))
    ))
    report = _run(stage="Seed")

    section = report["sections"]["venture_score"]
    assert str(section["venture_score"]) in captured["prompt"], (
        "the memo was not given the same number the report publishes"
    )


def test_a_degraded_specialist_does_not_look_like_a_bad_company(monkeypatch, tmp_path):
    """The invariant this codebase has had to defend repeatedly. A provider
    outage must not push the score down."""
    monkeypatch.chdir(tmp_path)

    _wire(monkeypatch, verdict="SUPPORTS", risk_severity=0.05,
          specialist_confidence=0.0, degraded=True)
    degraded = _run(stage="Seed")

    fusion = degraded["sections"]["evidence_fusion"]
    assert fusion["features"]["specialist_grounding"] is None, (
        "a degraded agent's zero confidence entered the fusion"
    )
    assert fusion["terms"]["specialist_grounding"] == 0.0
    assert degraded["provider_degraded"] is True
    assert degraded["recommendation"] == "NEEDS MORE DILIGENCE"


def test_the_score_stays_in_range_under_every_evidence_combination(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for verdict in ("SUPPORTS", "REFUTES", "NOT_ENOUGH_INFO"):
        for severity in (0.0, 0.5, 1.0):
            _wire(monkeypatch, verdict=verdict, risk_severity=severity,
                  specialist_confidence=0.5)
            report = _run(stage="Seed")
            assert 0 <= report["final_score"] <= 100


def test_report_sections_and_headline_agree(monkeypatch, tmp_path):
    """No stale cached value: the headline final_score must equal the blended
    score recorded in the venture_score section."""
    monkeypatch.chdir(tmp_path)
    _wire(monkeypatch, verdict="SUPPORTS", risk_severity=0.05, specialist_confidence=0.8)
    report = _run(stage="Seed")

    section = report["sections"]["venture_score"]
    if section.get("available"):
        assert report["final_score"] == pytest.approx(float(section["venture_score"]), abs=0.51)


def test_fusion_failure_degrades_to_the_previous_behaviour(monkeypatch, tmp_path):
    """The fusion must never be able to take a report down."""
    monkeypatch.chdir(tmp_path)
    _wire(monkeypatch, verdict="SUPPORTS", risk_severity=0.05, specialist_confidence=0.8)

    import ml.evidence_fusion as fusion_module

    def explode(*a, **k):
        raise RuntimeError("fusion exploded")

    monkeypatch.setattr(fusion_module, "extract_features", explode)
    report = _run(stage="Seed")
    assert 0 <= report["final_score"] <= 100
    assert report["recommendation"]
