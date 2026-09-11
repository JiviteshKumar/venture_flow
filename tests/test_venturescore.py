"""Tests for the VentureFlow Score model and its wiring into the pipeline.

Follows the pattern established by tests/test_ml_outcome_model.py: everything
that needs network or an LLM is monkeypatched, so the whole file runs with no
credentials and no internet. The trained model file itself is NOT mocked --
where it is present these tests exercise the real thing, and where it is
absent they assert the documented degradation instead. Both paths matter,
because the degradation path is what runs on a fresh clone.
"""

from types import SimpleNamespace

import pytest

import ventureflow_agent
from ml import venturescore


def _patch_pipeline(monkeypatch, *, verdict="SUPPORTS", risk_score=20, memo="memo"):
    """Silence every external dependency of run_due_diligence."""
    monkeypatch.setattr(ventureflow_agent, "verify_claim", lambda *_a, **_k: {
        "claim": "x", "verdict": verdict, "confidence": 0.8,
        "reasoning": "r", "key_evidence": "e", "total_sources": 2,
    })
    monkeypatch.setattr(ventureflow_agent, "score_risk", lambda *_a, **_k: {
        "risk_level": "LOW", "overall_score": risk_score, "key_concerns": [],
        "positive_factors": [], "red_flags": [], "total_signals": 0,
    })
    monkeypatch.setattr(ventureflow_agent, "run_investment_agents", lambda **_k: {
        "market": {"confidence": 0.6},
    })
    monkeypatch.setattr(ventureflow_agent, "build_context", lambda *_a: {"relevant_reports": []})
    monkeypatch.setattr(ventureflow_agent, "format_context_for_llm", lambda *_a: "")
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **_: SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=memo))]
            )
        ))
    )
    monkeypatch.setattr(ventureflow_agent, "get_client", lambda: fake_client)


# ── the model itself ─────────────────────────────────────────────────────

def test_score_company_returns_a_calibrated_score_with_uncertainty():
    result = venturescore.score_company(
        description="An AI-powered SaaS platform for enterprise developer teams.",
        one_liner="AI dev tools",
        industry="B2B",
    )
    if not result["available"]:
        pytest.skip(f"model file not present in this environment: {result['reason']}")

    assert 0 <= result["venture_score"] <= 100
    assert 0.0 <= result["probability_exit_or_survive"] <= 1.0
    # An uncertainty interval that actually contains the point estimate.
    low, high = result["score_range"]
    assert low <= result["venture_score"] <= high
    assert result["confidence"] in ("low", "medium", "high")
    assert result["ensemble_std"] >= 0.0
    assert 0.0 <= result["feature_coverage"] <= 1.0


def test_contaminated_features_are_not_used_by_the_shipped_model():
    """team_size, age_years and batch_year encode post-outcome information
    (see the CONTAMINATED block in train_venturescore_model.py). Their absence
    from the production feature list is a correctness property, not a detail:
    if a refactor reintroduces them the model starts marking down exactly the
    early-stage companies this product exists to evaluate."""
    if not venturescore.is_available():
        pytest.skip("model file not present in this environment")
    state = venturescore._state
    assert state is not None
    for leaky in ("team_size", "age_years", "batch_year"):
        assert leaky not in state["numeric_features"], f"{leaky} leaked back into the model"


def test_missing_optional_input_lowers_feature_coverage():
    """Coverage must actually respond to how much was supplied, otherwise the
    confidence label is decorative."""
    if not venturescore.is_available():
        pytest.skip("model file not present in this environment")
    sparse = venturescore.score_company(description="A software company.")
    rich = venturescore.score_company(
        description="A software company.", one_liner="software",
        industry="B2B", stage="Early", location="San Francisco, CA, USA",
    )
    assert rich["feature_coverage"] > sparse["feature_coverage"]


def test_score_company_never_raises_on_bad_input():
    for bad in ("", None, 12345):
        result = venturescore.score_company(description=bad)  # type: ignore[arg-type]
        assert "available" in result


def test_blend_with_evidence_lowers_score_and_reports_both_parts():
    base = {
        "available": True, "venture_score": 70, "score_range": [60, 80],
        "probability_exit_or_survive": 0.70,
    }
    blended = venturescore.blend_with_evidence(base, evidence_penalty=0.20)
    assert blended["venture_score"] == 50
    assert blended["model_only_score"] == 70      # both components stay visible
    assert blended["evidence_penalty"] == 0.20
    assert blended["score_range"] == [40, 60]     # interval shifts with the point estimate


def test_blend_with_evidence_passes_through_unavailable_results():
    unavailable = {"available": False, "reason": "no model"}
    assert venturescore.blend_with_evidence(unavailable, 0.3) == unavailable


def test_blend_with_evidence_clamps_to_valid_probability_range():
    base = {
        "available": True, "venture_score": 10, "score_range": [5, 15],
        "probability_exit_or_survive": 0.10,
    }
    blended = venturescore.blend_with_evidence(base, evidence_penalty=0.9)
    assert blended["venture_score"] == 0
    assert 0 <= blended["score_range"][0] <= blended["score_range"][1] <= 100


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0.35, 0.35), (1, 1.0), (0, 0.0),
        ("0.4", 0.4), ("85%", 0.85), (85, 0.85),
        # The shapes that actually broke production when the Groq model
        # changed under the app: a word instead of a number.
        ("low", 0.25), ("HIGH", 0.8), ("Medium", 0.5),
        # Anything unparseable must degrade to 0, never raise.
        ("banana", 0.0), (None, 0.0), ([], 0.0), (True, 0.0),
    ],
)
def test_coerce_confidence_never_raises_on_llm_authored_values(raw, expected):
    assert ventureflow_agent._coerce_confidence(raw) == pytest.approx(expected)


def test_specialist_string_confidence_does_not_crash_the_report(monkeypatch, tmp_path):
    """Regression guard for the outage this pass fixed: a specialist agent
    returning confidence as the string "low" used to raise ValueError out of
    run_due_diligence() and fail the whole report."""
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)
    monkeypatch.setattr(ventureflow_agent, "run_investment_agents", lambda **_k: {
        "market": {"confidence": "low"},
        "team": {"confidence": "high"},
        "bull": {"confidence": "not a number at all"},
    })
    report = ventureflow_agent.run_due_diligence(
        "Test Co", company_description="A" * 200, claims_to_verify=["x"], revenue=1_000,
    )
    assert 0 <= report["final_score"] <= 100


@pytest.mark.parametrize("bad", [None, "not a number", [], True, {}])
def test_evidence_penalty_survives_null_llm_numbers(bad):
    """Regression guard for the crash that failed real analyses end-to-end:

        TypeError: unsupported operand type(s) for /: 'NoneType' and 'float'

    The risk agent returns `overall_score: null` when its own LLM call fails,
    and `risk_result.get("overall_score", 30)` returns None for a key that is
    present-but-null. The arithmetic then raised, and the exception escaped
    every try/except in the pipeline and failed the whole job.
    """
    penalty = ventureflow_agent._evidence_penalty(
        refuted=bad, supported=bad, n_claims=bad,
        risk_score=bad, has_revenue=True, quality_score=bad,
    )
    assert 0.0 <= penalty <= 0.60


@pytest.mark.parametrize("bad", [None, "not a number", [], {}])
def test_legacy_formula_survives_null_llm_numbers(bad):
    """The fallback scorer takes the same LLM-derived inputs, so it needs the
    same guard -- otherwise the fallback path crashes exactly when it is most
    needed."""
    score = ventureflow_agent._legacy_formula_score(
        refuted=bad, supported=bad, n_claims=bad,
        risk_score=bad, has_revenue=False, quality_score=bad,
    )
    assert 0.0 <= score <= 100.0


def test_null_risk_score_does_not_fail_the_whole_report(monkeypatch, tmp_path):
    """End-to-end version of the same regression: a risk agent that returns a
    null score must degrade that section, not take the report down."""
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)
    monkeypatch.setattr(ventureflow_agent, "score_risk", lambda *_a, **_k: {
        "risk_level": None, "overall_score": None, "key_concerns": [],
        "positive_factors": [], "red_flags": [], "total_signals": None,
    })
    report = ventureflow_agent.run_due_diligence(
        "Null Risk Co", company_description="A" * 200,
        claims_to_verify=["a claim"], revenue=1_000, sector="B2B",
    )
    assert 0 <= report["final_score"] <= 100
    assert report["recommendation"] in ("INVEST", "PASS", "NEEDS MORE DILIGENCE")


def test_evidence_penalty_is_bounded_and_monotonic_in_refuted_claims():
    penalties = [
        ventureflow_agent._evidence_penalty(
            refuted=n, supported=3, n_claims=5, risk_score=20,
            has_revenue=True, quality_score=80,
        )
        for n in range(5)
    ]
    assert all(0.0 <= p <= 0.60 for p in penalties)
    assert penalties == sorted(penalties), "more refuted claims must never raise the score"


# ── wiring into the report pipeline ──────────────────────────────────────

def test_report_score_comes_from_the_model_not_the_legacy_formula(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)
    report = ventureflow_agent.run_due_diligence(
        "Test Co",
        company_description="An AI-powered SaaS platform for enterprise developer teams. " * 3,
        claims_to_verify=["claim one", "claim two"],
        sector="B2B", revenue=1_000_000,
    )
    assert "venture_score" in report["sections"]
    if report["sections"]["venture_score"]["available"]:
        assert report["score_source"] == "venturescore_model"
        assert report["final_score"] == report["sections"]["venture_score"]["venture_score"]
    else:
        assert report["score_source"] == "legacy_formula_fallback"


def test_model_failure_falls_back_to_legacy_formula_without_failing_the_report(monkeypatch, tmp_path):
    """The whole point of the try/except: a broken score model degrades the
    score, it does not take the report down with it."""
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)

    def boom(**_):
        raise RuntimeError("simulated model failure")
    monkeypatch.setattr(venturescore, "score_company", boom)

    report = ventureflow_agent.run_due_diligence(
        "Test Co", company_description="A" * 200, claims_to_verify=["x"], revenue=500_000,
    )
    assert report["sections"]["venture_score"]["available"] is False
    assert report["score_source"] == "legacy_formula_fallback"
    assert 0 <= report["final_score"] <= 100
    assert report["recommendation"] in ("INVEST", "PASS", "NEEDS MORE DILIGENCE")


def test_unverifiable_claims_do_not_cap_the_score(monkeypatch, tmp_path):
    """Regression guard for the finding from the 20-deck batch run.

    An early-stage company that nobody has written about yet will legitimately
    return NOT_ENOUGH_INFO on every claim. That used to flip
    `incomplete_analysis` and hard-cap the score at 30, so twenty different
    seed decks all scored identically and the trained model's estimate was
    discarded. Unverifiable is not the same as failed.
    """
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch, verdict="NOT_ENOUGH_INFO")
    report = ventureflow_agent.run_due_diligence(
        "Unknown Seed Co",
        company_description="An AI-powered SaaS platform for enterprise developer teams. " * 3,
        # Real claims, not placeholders. agents/claim_router.py skips extraction
        # fragments like "claim one" by design, so a placeholder is never
        # checked and this test would silently stop testing anything.
        claims_to_verify=[
            "The platform integrates with GitHub, GitLab and Bitbucket.",
            "Unknown Seed Co was founded in Austin, Texas in 2023.",
        ],
        sector="B2B", revenue=500_000,
    )
    assert report["claims_unverified"] is True
    assert report["incomplete_analysis"] is False, "unverifiable claims must not read as a failed analysis"
    if report["sections"]["venture_score"]["available"]:
        # The score must still be the model's, not the 30-point cap.
        assert report["final_score"] == report["sections"]["venture_score"]["venture_score"]
    # Honesty is still enforced at the recommendation layer.
    assert report["recommendation"] == "NEEDS MORE DILIGENCE"


def _score_with(monkeypatch, name, *, specialists, claims):
    """Run the pipeline twice-comparably: same company text, different evidence."""
    monkeypatch.setattr(ventureflow_agent, "run_investment_agents", lambda **_k: specialists)
    return ventureflow_agent.run_due_diligence(
        name,
        company_description="An AI-powered SaaS platform for enterprise developer teams. " * 3,
        claims_to_verify=claims, sector="B2B", revenue=500_000,
    )


def test_specialists_at_zero_lower_the_score_smoothly_instead_of_capping_it(monkeypatch, tmp_path):
    """When every specialist that actually ran returns confidence 0, that is a
    real signal about a content-free deck -- but it must be priced as a
    *penalty*, not as a cap.

    This is the regression guard for the defect that motivated the change: the
    old rule was `final_score = min(final_score, 30)`, which mapped every thin
    deck onto one identical number. Measured across 40 stored reports, 18 of 40
    different startups scored exactly 30.0. So the assertion here is
    deliberately COMPARATIVE rather than a threshold -- a constant-score
    implementation passes `<= 30` and fails this.
    """
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)
    confident = _score_with(
        monkeypatch, "Confident Co",
        specialists={"market": {"confidence": 0.9}, "team": {"confidence": 0.9},
                     "bull": {"confidence": 0.9}},
        claims=["claim one"],
    )
    zeroed = _score_with(
        monkeypatch, "Zeroed Co",
        specialists={"market": {"confidence": 0}, "team": {"confidence": 0},
                     "bull": {"confidence": 0}},
        claims=["claim one"],
    )

    # The deck is not "unanalysable" -- it had text, the pipeline ran.
    assert zeroed["incomplete_analysis"] is False
    # ...but it IS thin, and the report says so out loud.
    assert zeroed["thin_evidence"] is True
    # The penalty moved, and moved the right way.
    assert zeroed["final_score"] < confident["final_score"]
    assert zeroed["evidence_penalty"] > confident["evidence_penalty"]
    # And no thin deck may reach a decisive verdict regardless of the number.
    assert zeroed["recommendation"] == "NEEDS MORE DILIGENCE"


def test_no_extractable_claims_is_priced_as_thin_evidence_not_as_a_cap(monkeypatch, tmp_path):
    """No claims at all means nothing was checked. That is real missing
    evidence and must cost the company score -- but it is not the same thing as
    the analysis having failed, and it must not flatten the number."""
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)
    with_claims = _score_with(
        monkeypatch, "Some Claims Co",
        specialists={"market": {"confidence": 0.6}},
        # Real claims, not placeholders. agents/claim_router.py skips extraction
        # fragments like "claim one" by design, so a placeholder is never
        # checked and this test would silently stop testing anything.
        claims=[
            "The platform integrates with GitHub, GitLab and Bitbucket.",
            "Some Claims Co was founded in Austin, Texas in 2023.",
            "The product was launched publicly in March 2024.",
        ],
    )
    without = _score_with(
        monkeypatch, "No Claims Co",
        specialists={"market": {"confidence": 0.6}},
        claims=[],
    )

    assert without["incomplete_analysis"] is False
    assert without["claims_unverified"] is False
    assert without["thin_evidence"] is True
    assert without["final_score"] < with_claims["final_score"]
    assert without["recommendation"] == "NEEDS MORE DILIGENCE"


def test_claim_sparsity_is_graded_rather_than_stepped(monkeypatch, tmp_path):
    """The specific anti-cliff property: 0, 1, 2 and 3 claims must produce four
    distinct penalties, not two."""
    penalties = [
        ventureflow_agent._evidence_components(
            refuted=0, supported=n, n_claims=n, risk_score=20,
            has_revenue=True, quality_score=80,
        )["claim_sparsity"]
        for n in range(4)
    ]
    assert penalties == sorted(penalties, reverse=True), "more claims must never cost more"
    assert len(set(penalties)) == 4, f"claim sparsity collapsed to a step: {penalties}"


def test_a_deck_with_no_readable_text_at_all_is_still_floored(monkeypatch, tmp_path):
    """The one hard floor that survives. If text extraction produced nothing,
    the product genuinely knows nothing and must say so rather than reporting
    the model's prior as if it were an assessment."""
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)
    report = ventureflow_agent.run_due_diligence(
        "Empty Deck Co", company_description="", filing_text="",
        claims_to_verify=["claim one"], sector="B2B", revenue=500_000,
    )
    assert report["incomplete_analysis"] is True
    assert report["final_score"] <= 30


def test_low_model_confidence_blocks_a_decisive_recommendation(monkeypatch, tmp_path):
    """A score the model itself says is poorly supported must not turn into a
    confident INVEST or PASS."""
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)
    monkeypatch.setattr(venturescore, "score_company", lambda **_: {
        "available": True, "venture_score": 95, "score_range": [70, 99],
        "probability_exit_or_survive": 0.95, "confidence": "low",
        "ensemble_std": 0.2, "feature_coverage": 0.3, "imputed_features": [],
        "base_rate": 0.46, "lift_over_base_rate": 0.49,
        "model": {"family": "rf", "cv_roc_auc": 0.67, "cv_roc_auc_ci95": [0.65, 0.68],
                  "cv_ece": 0.016, "cv_brier": 0.22, "trained_n": 1560,
                  "calibration": "isotonic", "excluded_contaminated_features": []},
        "caveat": "test",
    })
    report = ventureflow_agent.run_due_diligence(
        "Test Co", company_description="A" * 200,
        claims_to_verify=["a", "b", "c"], revenue=9_000_000, sector="B2B",
    )
    assert report["recommendation"] == "NEEDS MORE DILIGENCE"


def test_the_memo_prompt_receives_the_score_before_synthesis(monkeypatch, tmp_path):
    """Ordering guard. The score must already exist when the LLM is called,
    otherwise the narrative is authoring the number instead of explaining it
    -- which is the exact regression this pass was built to prevent."""
    monkeypatch.chdir(tmp_path)
    captured = {}

    def capture(**kwargs):
        captured["messages"] = kwargs.get("messages", [])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="memo"))])

    _patch_pipeline(monkeypatch)
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=capture))
    )
    monkeypatch.setattr(ventureflow_agent, "get_client", lambda: fake_client)

    ventureflow_agent.run_due_diligence(
        "Test Co",
        company_description="An AI-powered SaaS platform for enterprise developer teams. " * 3,
        claims_to_verify=["claim one"], sector="B2B", revenue=1_000_000,
    )

    user_content = "\n".join(m.get("content", "") for m in captured["messages"])
    assert "VENTUREFLOW SCORE" in user_content
    assert "NOT by you" in user_content or "unavailable" in user_content
