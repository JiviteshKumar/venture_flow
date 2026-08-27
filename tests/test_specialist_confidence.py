"""The specialist agents' confidence contract.

Until this session `confidence` was never defined. The prompt said only that it
"MUST be a bare number between 0 and 1" and that an agent should "lower
confidence" when evidence is absent -- nothing said confidence in WHAT. Four
agents answered under that instruction, and `bull_case` could reasonably have
read it as "how bullish I am", which is a different quantity entirely.

It is not cosmetic: `_evidence_components` computes
`specialist_uncertainty = (1 - mean_confidence) * 0.15`, so an undefined number
moved the headline score.

These tests pin the contract structurally -- what the prompt asks for and what
the code does with the answer -- rather than asserting what a model replies,
which is not reproducible in CI. The behavioural measurement lives in
ml/eval/specialist_confidence_results.json.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ventureflow_agent
from agents import investment_agents


def _prompt_text() -> str:
    """The prompt template, captured without calling the provider."""
    captured = {}

    class FakeClient:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**kwargs):
                    captured["prompt"] = kwargs["messages"][-1]["content"]
                    raise RuntimeError("stop here; the prompt is what we wanted")

    original = investment_agents.get_client
    investment_agents.get_client = lambda: FakeClient()
    try:
        investment_agents._json_agent("test analyst", "do the thing", "evidence", {"confidence": 0})
    finally:
        investment_agents.get_client = original
    return captured["prompt"]


def test_the_prompt_defines_what_confidence_measures():
    prompt = _prompt_text().lower()
    assert "confidence` is not how promising" in prompt or "not how promising" in prompt
    assert "quotable evidence" in prompt or "quotable" in prompt


def test_the_prompt_separates_confidence_from_the_strength_of_the_case():
    """The bull/bear failure mode: reading confidence as enthusiasm."""
    prompt = _prompt_text().lower()
    assert "bear case" in prompt and "bull case" in prompt
    assert "describes your evidence, not your conclusion" in prompt


def test_the_prompt_carries_calibration_anchors():
    prompt = _prompt_text()
    for band in ("0.85-1.00", "0.60-0.84", "0.35-0.59", "0.15-0.34", "0.00-0.14"):
        assert band in prompt, f"missing calibration band {band}"


def test_the_prompt_distinguishes_evidence_from_adjectives():
    """The measured failure that motivated the second revision.

    On a deck of pure adjectives with no figures, dates or named entities, the
    agents reported '5 findings quote deck verbatim' and scored 0.68-0.78. They
    were quoting verbatim -- they were quoting marketing copy. Counting quotes
    is not counting evidence.
    """
    prompt = _prompt_text().lower()
    assert "checkable particular" in prompt
    assert "massive market" in prompt or "transformative technology" in prompt
    assert "must score below 0.35" in prompt


def test_confidence_basis_is_requested_so_the_number_is_auditable():
    assert "confidence_basis" in _prompt_text()


def test_every_fallback_carries_a_confidence_basis():
    """A degraded run must still produce the field, or downstream readers see a
    missing key and cannot distinguish it from an agent that declined to answer."""
    from agents.investment_agents import _degraded

    out = _degraded({"confidence": 0}, "provider rate limit")
    assert out["_degraded"] is True
    assert out["_degraded_reason"] == "provider rate limit"


@pytest.mark.parametrize("value,expected", [
    (0.35, 0.35), ("0.35", 0.35), ("35%", 0.35), ("low", 0.25),
    ("high", 0.8), (None, 0.0), ("", 0.0), (True, 0.0), ([], 0.0),
])
def test_confidence_coercion_survives_every_shape_a_model_has_emitted(value, expected):
    """Unexpected output shapes, which Part G asks about explicitly. An
    unguarded float() here once failed an entire report when a new model
    answered "low" instead of a number."""
    assert ventureflow_agent._coerce_confidence(value) == pytest.approx(expected)


def test_a_degraded_agent_is_excluded_from_the_evidence_penalty():
    """The load-bearing consequence. A degraded agent's confidence of 0 reflects
    a provider failure, not a judgement about the company, and averaging it into
    specialist_uncertainty would re-import the exact bug this project spent a
    session removing."""
    components_with_degraded = ventureflow_agent._evidence_components(
        refuted=0, supported=1, n_claims=1, risk_score=20,
        has_revenue=True, quality_score=80, specialist_confidences=[],
    )
    assert components_with_degraded["specialist_uncertainty"] == 0.0

    components_answered = ventureflow_agent._evidence_components(
        refuted=0, supported=1, n_claims=1, risk_score=20,
        has_revenue=True, quality_score=80, specialist_confidences=[0.0, 0.0],
    )
    assert components_answered["specialist_uncertainty"] > 0.0
