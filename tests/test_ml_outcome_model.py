from types import SimpleNamespace

import ventureflow_agent


def test_outcome_model_section_is_present_and_never_blocks_the_report(monkeypatch, tmp_path):
    """The trained outcome model is an additive signal: if it's unavailable
    or errors, the rest of the report must still complete successfully."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ventureflow_agent, "verify_claim", lambda *_a, **_k: {
        "claim": "x", "verdict": "SUPPORTS", "confidence": 0.8,
    })
    monkeypatch.setattr(ventureflow_agent, "score_risk", lambda *_a, **_k: {
        "risk_level": "LOW", "overall_score": 10, "key_concerns": [],
        "positive_factors": [], "red_flags": [], "total_signals": 0,
    })
    monkeypatch.setattr(ventureflow_agent, "run_investment_agents", lambda **_k: {
        "market": {"confidence": 0.5}, "team": {"confidence": 0.5},
    })
    monkeypatch.setattr(ventureflow_agent, "build_context", lambda *_a: {"relevant_reports": []})
    monkeypatch.setattr(ventureflow_agent, "format_context_for_llm", lambda *_a: "")
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **_: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="memo"))])
        ))
    )
    monkeypatch.setattr(ventureflow_agent, "get_client", lambda: fake_client)

    report = ventureflow_agent.run_due_diligence(
        "Test Co", company_description="A" * 120, claims_to_verify=["x"],
        sector="B2B", team_size=5,
    )

    assert "ml_outcome_model" in report["sections"]
    ml_section = report["sections"]["ml_outcome_model"]
    assert "available" in ml_section
    # Whether or not the trained model file happens to be present in this
    # test environment, the report must have completed successfully either way.
    assert report["final_score"] >= 0


def test_outcome_model_failure_is_caught_not_raised(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ventureflow_agent, "verify_claim", lambda *_a, **_k: {
        "claim": "x", "verdict": "NOT_ENOUGH_INFO", "confidence": 0,
    })
    monkeypatch.setattr(ventureflow_agent, "score_risk", lambda *_a, **_k: {
        "risk_level": "LOW", "overall_score": 0, "key_concerns": [],
        "positive_factors": [], "red_flags": [], "total_signals": 0,
    })
    monkeypatch.setattr(ventureflow_agent, "run_investment_agents", lambda **_k: {})
    monkeypatch.setattr(ventureflow_agent, "build_context", lambda *_a: {"relevant_reports": []})
    monkeypatch.setattr(ventureflow_agent, "format_context_for_llm", lambda *_a: "")
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **_: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="memo"))])
        ))
    )
    monkeypatch.setattr(ventureflow_agent, "get_client", lambda: fake_client)

    import ml.inference
    def boom(**_):
        raise RuntimeError("simulated model failure")
    monkeypatch.setattr(ml.inference, "score_company", boom)

    # Must not raise even though the outcome model explodes.
    report = ventureflow_agent.run_due_diligence("Test Co", "A" * 120, [])
    assert report["sections"]["ml_outcome_model"]["available"] is False
