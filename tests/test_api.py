from fastapi.testclient import TestClient

import api


def test_analyze_rejects_invalid_payload():
    client = TestClient(api.app)
    response = client.post("/analyze", json={"company_name": "", "claims": []})
    assert response.status_code == 422


def test_analyze_returns_persisted_report(monkeypatch):
    monkeypatch.setattr(api, "create_analysis_job", lambda _: "job-id")
    updates = []
    monkeypatch.setattr(api, "update_analysis_job", lambda *args, **kw: updates.append(args))
    monkeypatch.setattr(api, "find_similar_companies", lambda *_: [{"name": "Existing Co", "similarity": 0.8}])
    monkeypatch.setattr(api, "persist_report", lambda **_: "report-id")
    monkeypatch.setattr(
        api,
        "run_due_diligence",
        # **kwargs, because api.py now binds every pipeline argument by
        # keyword. A positional-only stub raises TypeError inside the job, which
        # the queue faithfully records as a failed analysis -- so this test
        # would fail for a reason that has nothing to do with what it checks.
        lambda *_a, **_k: {
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
    assert response.status_code == 202
    # Assert on the fields this test is about rather than exact dict equality,
    # so an additive field on AnalysisJobResponse (e.g. `stage`, added for real
    # progress reporting) does not fail a test that is really about the 202
    # accept-and-queue behaviour.
    body = response.json()
    assert body["job_id"] == "job-id"
    assert body["status"] == "pending"
    assert body["report"] is None
    assert body["error"] is None
    assert updates[-1][1] == "complete"


def test_analyze_returns_a_clear_error_when_persistence_fails(monkeypatch):
    monkeypatch.setattr(api, "create_analysis_job", lambda _: "job-id")
    updates = []
    monkeypatch.setattr(api, "update_analysis_job", lambda *args: updates.append(args))
    monkeypatch.setattr(api, "find_similar_companies", lambda *_: [])
    monkeypatch.setattr(api, "run_due_diligence", lambda *_a, **_k: {"sections": {}})

    def fail_persist(**_):
        raise RuntimeError("schema is missing dd_reports.raw_output")

    monkeypatch.setattr(api, "persist_report", fail_persist)
    client = TestClient(api.app)
    response = client.post("/analyze", json={"company_name": "New Co"})
    assert response.status_code == 202
    assert updates[-1][1] == "failed"


def test_analysis_status_returns_completed_report(monkeypatch):
    monkeypatch.setattr(api, "get_analysis_job", lambda _: {"job_id": "job-id", "status": "complete", "error_message": None, "result": {"company": "New Co", "final_score": 20, "recommendation": "PASS", "risk_level": "LOW", "ai_analysis": "memo", "claims_verified": 0, "claims_supported": 0, "claims_refuted": 0, "claims_uncertain": 0, "risk_signals_found": 0, "key_concerns": [], "red_flags": [], "positive_factors": [], "sections": {}, "data_quality": {}, "session_id": "s"}})
    response = TestClient(api.app).get("/analyze/status/job-id")
    assert response.status_code == 200
    assert response.json()["report"]["company"] == "New Co"


def test_startup_attempts_idempotent_schema_migration(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "ensure_schema", lambda: calls.append(True))

    with TestClient(api.app):
        pass

    assert calls == [True]


def test_saved_report_endpoints(monkeypatch):
    monkeypatch.setattr(api, "list_reports", lambda: [{"report_id": "r1", "company": "Saved Co", "final_score": 42, "recommendation": "PASS", "created_at": "2026-08-01T00:00:00Z"}])
    monkeypatch.setattr(api, "get_report", lambda _: {"report_id": "r1", "company": "Saved Co", "raw_output": {"sections": {"claims": {}, "risk": {}}, "final_score": 42, "recommendation": "PASS"}})
    client = TestClient(api.app)
    assert client.get("/reports").json()[0]["company"] == "Saved Co"
    detail = client.get("/reports/r1")
    assert detail.status_code == 200
    assert detail.json()["report_id"] == "r1"
