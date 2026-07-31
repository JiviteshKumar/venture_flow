from types import SimpleNamespace

import ventureflow_agent


def test_due_diligence_uses_report_context_shape(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        ventureflow_agent,
        "build_context",
        lambda _: {"query": "Test", "relevant_reports": [{"name": "Prior Co"}]},
    )
    monkeypatch.setattr(ventureflow_agent, "format_context_for_llm", lambda _: "context")
    monkeypatch.setattr(
        ventureflow_agent,
        "score_risk",
        lambda *_args, **_kwargs: {
            "risk_level": "LOW",
            "overall_score": 10,
            "key_concerns": [],
            "positive_factors": [],
            "red_flags": [],
            "total_signals": 0,
        },
    )
    monkeypatch.setattr(
        ventureflow_agent,
        "client",
        SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="memo"))]
                    )
                )
            )
        ),
    )

    report = ventureflow_agent.run_due_diligence(
        "Test Co", company_description="A" * 120, claims_to_verify=[]
    )

    assert report["sections"]["rag_context"] == {"reports_retrieved": 1}
