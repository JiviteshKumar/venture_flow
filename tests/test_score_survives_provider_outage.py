"""An LLM outage must not be reported as a verdict on the company.

This pins the fix for the worst defect this product has had. Measured across 40
stored reports before the fix: 25 were score-capped at 30, and 19 of those were
capped purely because Groq returned 429 to all four specialist agents. 18 of 40
different startups ended up with an identical 30/100 and an identical
recommendation. A due-diligence tool that cannot rank one deck above another is
not doing its job, and the cause was that an exhausted API quota looked exactly
like a confidence-0 judgement.

The VentureFlow Score never reads the specialists -- it scores company
characteristics, and on 150 real YC companies it spreads 8-86 with sd 24.3. So
when the LLM layer falls over, that number is still the best estimate available
and must survive. What degrades is the narrative, and the report has to say so.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ventureflow_agent

DECK = (
    "Northwind Robotics builds warehouse automation for mid-size distributors. "
    "We booked $1.4M in ARR across 62 customers in our first eight months, and "
    "our anchor customer represents 78% of revenue."
)


def _patch(monkeypatch, *, specialists, claims=None, memo="memo"):
    """Silence every external dependency; `specialists` decides the scenario."""
    monkeypatch.setattr(ventureflow_agent, "verify_claim", lambda *_a, **_k: {
        "claim": "x", "verdict": "NOT_ENOUGH_INFO", "confidence": 0.4,
        "reasoning": "no corroboration found", "key_evidence": "", "total_sources": 5,
    })
    monkeypatch.setattr(ventureflow_agent, "score_risk", lambda *_a, **_k: {
        "risk_level": "MEDIUM", "overall_score": 35, "key_concerns": [],
        "positive_factors": [], "red_flags": [], "total_signals": 1,
        "ai_reasoning": "real risk reasoning",
    })
    monkeypatch.setattr(ventureflow_agent, "run_investment_agents", lambda **_k: specialists)
    monkeypatch.setattr(ventureflow_agent, "build_context", lambda *_a: {"relevant_reports": []})
    monkeypatch.setattr(ventureflow_agent, "format_context_for_llm", lambda *_a: "")
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **_: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=memo))]))))
    monkeypatch.setattr(ventureflow_agent, "get_client", lambda: fake)


def _all_agents_degraded():
    """What a Groq 429 actually produces: confidence 0 plus the marker."""
    from agents.investment_agents import _degraded
    base = {"confidence": 0, "signals": [], "gaps": [], "questions": []}
    return {name: _degraded(dict(base), "provider rate limit / quota exhausted")
            for name in ("market", "team", "bull_case", "bear_case")}


def _all_agents_healthy():
    return {name: {"confidence": 0.4, "signals": [], "gaps": [], "questions": []}
            for name in ("market", "team", "bull_case", "bear_case")}


def _run(monkeypatch, specialists, description=DECK):
    _patch(monkeypatch, specialists=specialists)
    return ventureflow_agent.run_due_diligence(
        company_name="Northwind Robotics",
        company_description=description,
        claims_to_verify=["We booked $1.4M in ARR across 62 customers."],
        filing_text=description,
    )


@pytest.mark.skipif(
    not __import__("ml.venturescore", fromlist=["x"]).is_available(),
    reason="VentureFlow Score model file not present in this checkout",
)
def test_provider_outage_does_not_flatten_the_score(monkeypatch):
    """The regression. Every agent 429s; the score must still be the model's."""
    report = _run(monkeypatch, _all_agents_degraded())

    assert report["provider_degraded"] is True
    assert len(report["degraded_components"]) >= 4
    assert all("quota" in c["reason"] or "provider" in c["reason"]
               for c in report["degraded_components"])

    # The cap is what produced 18 identical 30s. It must not have fired.
    assert report["incomplete_analysis"] is False, (
        "a provider outage was recorded as the analysis having failed"
    )
    assert report["final_score"] != 30, (
        "the score was flattened to the cap by an infrastructure failure"
    )
    assert report["score_source"] == "venturescore_model"


def test_degraded_run_still_refuses_a_decisive_verdict(monkeypatch):
    """Keeping the number must not mean pretending the analysis was complete."""
    report = _run(monkeypatch, _all_agents_degraded())
    assert report["recommendation"] == "NEEDS MORE DILIGENCE"


def test_healthy_run_is_not_marked_degraded(monkeypatch):
    report = _run(monkeypatch, _all_agents_healthy())
    assert report["provider_degraded"] is False
    assert report["degraded_components"] == []


def test_genuinely_empty_input_is_still_capped(monkeypatch):
    """The cap keeps its real job: when there is no deck text at all, the
    product genuinely knows nothing and must not present a confident number."""
    _patch(monkeypatch, specialists=_all_agents_healthy())
    report = ventureflow_agent.run_due_diligence(
        company_name="Nothing Co", company_description="", claims_to_verify=[], filing_text="",
    )
    # Either refused up front by the data-quality gate, or capped.
    assert report["final_score"] <= 30


def test_two_different_decks_get_different_scores_under_outage(monkeypatch):
    """The product-level property the user actually cares about: under a total
    LLM outage, two different companies must still receive different scores."""
    a = _run(monkeypatch, _all_agents_degraded(), description=DECK)
    b = _run(monkeypatch, _all_agents_degraded(), description=(
        "Perennial Bio is a clinical-stage therapeutics company developing small "
        "molecule treatments. No revenue; pre-clinical pipeline of three assets."
    ))
    assert a["final_score"] != b["final_score"], (
        "two very different companies received the same score during an outage -- "
        "this is exactly the defect the fix exists to remove"
    )


def test_a_failed_claim_check_is_flagged_however_its_message_is_worded(monkeypatch, tmp_path):
    """Degradation must be detected on a flag, never on the wording of a
    message.

    Regression guard for a bug this file's own fix originally shipped with. The
    pipeline has TWO fallback sites for a failed claim check -- one inside
    agents/claim_verifier ("Claim verification is temporarily unavailable.")
    and one in ventureflow_agent's exception handler ("Claim verification was
    temporarily unavailable.") -- and the detector string-compared against only
    the first. A claim that failed through the second path was recorded at
    confidence 0.0 with `provider_degraded` left False.

    Found on the first real pitch deck run through the pipeline: Airbnb's "There
    are 10.6M trips booked worldwide" failed exactly that way, and the report
    declared itself complete. That is the original constant-score defect in
    another costume -- an infrastructure failure counted as a finding about the
    company -- so it is tested on the mechanism, not on the sentence.
    """
    monkeypatch.chdir(tmp_path)
    _patch(monkeypatch, specialists=_all_agents_healthy())

    def explode(*_args, **_kwargs):
        raise RuntimeError("groq 429: rate limit exceeded")

    monkeypatch.setattr(ventureflow_agent, "verify_claim", explode)

    report = ventureflow_agent.run_due_diligence(
        company_name="Northwind Robotics",
        company_description=DECK,
        # Real claims, not placeholders. agents/claim_router.py skips extraction
        # fragments like "claim one" by design, so a placeholder is never
        # checked and this test would silently stop testing anything.
        claims_to_verify=[
            "Northwind Robotics was founded in Pittsburgh in 2019.",
            "The platform integrates with SAP and Oracle warehouse systems.",
        ],
        filing_text=DECK,
        revenue=500_000,
    )

    assert report["provider_degraded"] is True, (
        "a claim check that failed via the pipeline's own exception handler "
        "must still register as provider degradation"
    )
    components = {c["component"] for c in report["degraded_components"]}
    assert "claim_verification" in components
    assert report["recommendation"] == "NEEDS MORE DILIGENCE"
    # And the defining property: the outage must not be scored as a verdict.
    assert report["incomplete_analysis"] is False


def test_risk_analysis_degradation_is_also_flag_based(monkeypatch, tmp_path):
    """Same fault, same fix, other component: the risk branch looked for
    "Error in analysis" while ventureflow_agent's own fallback writes "Risk
    analysis unavailable.", so a risk outage raised through the pipeline was
    never flagged either."""
    monkeypatch.chdir(tmp_path)
    _patch(monkeypatch, specialists=_all_agents_healthy())

    def explode(*_args, **_kwargs):
        raise RuntimeError("groq 429: rate limit exceeded")

    monkeypatch.setattr(ventureflow_agent, "score_risk", explode)

    report = ventureflow_agent.run_due_diligence(
        company_name="Northwind Robotics",
        company_description=DECK,
        claims_to_verify=["a claim"],
        filing_text=DECK,
        revenue=500_000,
    )
    assert report["provider_degraded"] is True
    assert "risk_analysis" in {c["component"] for c in report["degraded_components"]}
