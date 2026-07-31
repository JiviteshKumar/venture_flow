from fastapi.testclient import TestClient

import api


def test_analyze_rejects_invalid_payload():
    client = TestClient(api.app)
    response = client.post("/analyze", json={"company_name": "", "claims": []})
    assert response.status_code == 422


def test_analyze_returns_persisted_report(monkeypatch):
    monkeypatch.setattr(api, "find_similar_companies", lambda *_: [{"name": "Existing Co", "similarity": 0.8}])
    monkeypatch.setattr(api, "persist_report", lambda **_: "report-id")
    monkeypatch.setattr(
        api,
        "run_due_diligence",
        lambda *_: {
            "company": "New Co",
            "final_score": 70,
            "recommendation": "INVEST",
            "risk_level": "LOW",
            "data_quality": {},
            "sections": {
                "ai_analysis": "Evidence-backed memo",
                "claims": {"checked": 1, "supported": 1, "refuted": 0, "uncertain": 0, "details": []},
                "risk": {"total_signals": 0, "key_concerns": [], "red_flags": [], "positive_factors": []},
            },
        },
    )
    client = TestClient(api.app)
    response = client.post("/analyze", json={"company_name": "New Co", "company_description": "Test"})
    assert response.status_code == 200
    assert response.json()["report_id"] == "report-id"
    assert response.json()["similar_companies"][0]["name"] == "Existing Co"


def test_analyze_returns_a_clear_error_when_persistence_fails(monkeypatch):
    monkeypatch.setattr(api, "find_similar_companies", lambda *_: [])
    monkeypatch.setattr(api, "run_due_diligence", lambda *_: {"sections": {}})

    def fail_persist(**_):
        raise RuntimeError("schema is missing dd_reports.raw_output")

    monkeypatch.setattr(api, "persist_report", fail_persist)
    client = TestClient(api.app)
    response = client.post("/analyze", json={"company_name": "New Co"})
    assert response.status_code == 503
    assert response.json()["detail"] == "Analysis completed but could not be saved. Please retry."


def test_startup_attempts_idempotent_schema_migration(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "ensure_schema", lambda: calls.append(True))

    with TestClient(api.app):
        pass

    assert calls == [True]
