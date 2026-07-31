from agents import investment_agents


def test_specialist_agents_return_all_four_structured_results(monkeypatch):
    def fake_agent(role, _task, _evidence, fallback):
        return {**fallback, "role": role, "confidence": 42}

    monkeypatch.setattr(investment_agents, "_json_agent", fake_agent)

    results = investment_agents.run_investment_agents(
        "Example Co", "The founder has 10 years of experience.", [], {"risk_level": "LOW"}
    )

    assert set(results) == {"market", "team", "bull_case", "bear_case"}
    assert all(result["confidence"] == 42 for result in results.values())
