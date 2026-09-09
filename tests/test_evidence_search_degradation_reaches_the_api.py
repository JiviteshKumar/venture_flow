"""A field the pipeline sets is worth nothing until the response declares it.

This repository has now been bitten by the same Pydantic behaviour twice. A
response model silently drops any key it does not declare, so a value can be
computed correctly, attached to the report correctly, and still arrive at the
UI missing -- with no error anywhere. That is how `provider_degraded` reached
the frontend as False on reports where every LLM-backed component had failed,
and it is why the Uber report showed an empty Bull/Bear panel that read as
"no positive signals identified" rather than "these agents did not run".

`evidence_search_degraded` is the third state and the newest, so it gets the
test the first two earned:

    _degraded                  the model never ran -> claim excluded from score
    thin_evidence              the deck genuinely said very little
    evidence_search_degraded   the model ran, on evidence gathered without the
                               general web index (94% -> 32% on-topic)

The distinctions matter because the remedies are opposite. Dropping a claim is
right for the first and wrong for the third.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _minimal(**overrides):
    """DiligenceResponse has fourteen required fields; none of them is what
    these tests are about."""
    import api

    base = dict(
        company="Buffer", final_score=50.0, recommendation="HOLD",
        risk_level="medium", ai_analysis="", claims_verified=0,
        claims_supported=0, claims_refuted=0, claims_uncertain=0,
        risk_signals_found=0, key_concerns=[], red_flags=[],
        positive_factors=[], session_id="s1",
    )
    base.update(overrides)
    return api.DiligenceResponse(**base)


class TestTheResponseModelDeclaresIt:
    def test_the_fields_exist_on_the_model(self):
        import api

        fields = api.DiligenceResponse.model_fields
        assert "evidence_search_degraded" in fields, (
            "an undeclared field is dropped silently; the UI would never see it"
        )
        assert "evidence_search_note" in fields

    def test_a_report_carrying_them_survives_serialisation(self):
        import api

        model = _minimal(
            evidence_search_degraded=True,
            evidence_search_note="DuckDuckGo was rate-limited.",
        )
        dumped = model.model_dump()
        assert dumped["evidence_search_degraded"] is True
        assert dumped["evidence_search_note"] == "DuckDuckGo was rate-limited."

    def test_they_default_to_a_clean_run(self):
        import api

        model = _minimal()
        assert model.evidence_search_degraded is False
        assert model.evidence_search_note == ""


class TestTheThreeStatesStayDistinct:
    """Each has a different remedy, so collapsing any two is a defect.

    `thin_evidence` is the fourth state and is deliberately not asserted here:
    it reaches the UI as `evidence_penalty` nested inside `venture_score`
    rather than as a top-level field on this model.
    """

    @pytest.mark.parametrize("field", [
        "provider_degraded",
        "claims_verification_degraded",
        "evidence_search_degraded",
    ])
    def test_each_state_is_separately_reportable(self, field):
        import api

        assert field in api.DiligenceResponse.model_fields

    def test_a_thin_search_does_not_claim_the_provider_was_down(self):
        """The costly conflation. `provider_degraded` is what excludes claims
        from the score; a rate-limited search must not trigger it, because the
        verdicts it produced are real."""
        import api

        model = _minimal(evidence_search_degraded=True)
        assert model.provider_degraded is False
        assert model.claims_verification_degraded is False
