"""Worker-queue behaviour: orphan recovery, load shedding, and the guarantee
that none of this changed what an analysis produces.

The queue itself predates this file -- `/analyze` already returned 202 with a
job id and the frontend already polled `/analyze/status/{id}`. What did not
exist was any handling of the failure that Render's free tier produces
routinely: the API process dies, every BackgroundTask dies with it, and the job
row sits at 'running' forever while the frontend polls a spinner that can never
resolve.

That is the same defect this codebase keeps finding in other costumes --
infrastructure died and the product reported it as work in progress -- and it
was live: running this reclamation against the real database for the first time
failed a job that had been stuck in 'running' since 22 August.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api

# A minimally complete DiligenceResponse payload. Built from the model's own
# required-field list rather than hand-guessed: the first version of this
# fixture omitted five required fields and the test failed on validation
# instead of on the behaviour it was written to check.
COMPLETED_REPORT = {
    "company": "Done Co",
    "final_score": 62.0,
    "recommendation": "NEEDS MORE DILIGENCE",
    "risk_level": "MEDIUM",
    "ai_analysis": "memo",
    "claims_verified": 3,
    "claims_supported": 2,
    "claims_refuted": 0,
    "claims_uncertain": 1,
    "risk_signals_found": 1,
    "key_concerns": [],
    "red_flags": [],
    "positive_factors": [],
    "session_id": "s1",
    "sections": {},
}


@pytest.fixture
def client():
    return TestClient(api.app)


# ── Load shedding ──────────────────────────────────────────────────────────


def test_submitting_when_at_capacity_is_refused_with_a_retryable_429(client, monkeypatch):
    """Accepting work the process cannot finish turns one overload into many
    orphaned jobs: each in-flight analysis holds a thread and megabytes of deck
    text, and Render's free tier OOM-kills the process, taking every job with
    it. A 429 the caller can retry is a better failure."""
    monkeypatch.setattr(api, "MAX_CONCURRENT_ANALYSES", 2)
    monkeypatch.setattr(api, "count_active_jobs", lambda: 2)

    response = client.post("/analyze", json={
        "company_name": "Overloaded Co", "company_description": "A" * 200,
        "claims": ["a claim"],
    })
    assert response.status_code == 429
    assert "already running" in response.json()["detail"]


def test_below_capacity_the_job_is_accepted(client, monkeypatch):
    monkeypatch.setattr(api, "MAX_CONCURRENT_ANALYSES", 3)
    monkeypatch.setattr(api, "count_active_jobs", lambda: 0)
    monkeypatch.setattr(api, "create_analysis_job", lambda payload: "job-123")
    monkeypatch.setattr(api, "_run_analysis_job", lambda *a, **k: None)

    response = client.post("/analyze", json={
        "company_name": "Fine Co", "company_description": "A" * 200,
        "claims": ["a claim"],
    })
    assert response.status_code == 202
    assert response.json()["job_id"] == "job-123"
    assert response.json()["status"] == "pending"


def test_a_failing_capacity_check_does_not_block_analysis(client, monkeypatch):
    """Bookkeeping must never be able to fail real work. If the count query
    breaks, accept the job."""
    def explode():
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(api, "count_active_jobs", explode)
    monkeypatch.setattr(api, "create_analysis_job", lambda payload: "job-456")
    monkeypatch.setattr(api, "_run_analysis_job", lambda *a, **k: None)

    response = client.post("/analyze", json={
        "company_name": "Degraded Count Co", "company_description": "A" * 200,
        "claims": ["a claim"],
    })
    assert response.status_code == 202


# ── Orphan recovery ────────────────────────────────────────────────────────


def test_polling_a_dead_job_reclaims_it_instead_of_spinning_forever(client, monkeypatch):
    """The user-visible half of the fix. Startup reclamation handles a process
    that restarted; this handles a job whose worker died while the process
    stayed up. Without it the frontend polls 'running' indefinitely."""
    states = iter([
        {"job_id": "dead-1", "status": "running", "result": None,
         "error_message": None, "stage": "Verifying claims"},
        {"job_id": "dead-1", "status": "failed", "result": None,
         "error_message": "The analysis was interrupted before it finished -- the "
                          "server restarted while your deck was being processed.",
         "stage": "Verifying claims"},
    ])
    monkeypatch.setattr(api, "get_analysis_job", lambda job_id: next(states))
    monkeypatch.setattr(api, "reclaim_orphaned_jobs", lambda: [{"job_id": "dead-1"}])

    response = client.get("/analyze/status/dead-1")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert "restarted" in body["error"]
    assert "Please upload it again" in body["error"] or "interrupted" in body["error"]


def test_a_healthy_running_job_is_not_reclaimed(client, monkeypatch):
    """Reclamation must not fail work that is genuinely in progress."""
    job = {"job_id": "alive-1", "status": "running", "result": None,
           "error_message": None, "stage": "Detecting risk signals"}
    monkeypatch.setattr(api, "get_analysis_job", lambda job_id: job)
    monkeypatch.setattr(api, "reclaim_orphaned_jobs", lambda: [])

    body = client.get("/analyze/status/alive-1").json()
    assert body["status"] == "running"
    assert body["stage"] == "Detecting risk signals"
    assert body["error"] is None


def test_a_completed_job_is_never_touched_by_reclamation(client, monkeypatch):
    calls = []
    monkeypatch.setattr(api, "get_analysis_job", lambda job_id: {
        "job_id": "done-1", "status": "complete", "stage": None, "error_message": None,
        "result": COMPLETED_REPORT,
    })
    monkeypatch.setattr(api, "reclaim_orphaned_jobs", lambda: calls.append(1) or [])

    body = client.get("/analyze/status/done-1").json()
    assert body["status"] == "complete"
    assert calls == [], "a finished job must not trigger reclamation work"


def test_reclamation_failure_does_not_break_the_status_endpoint(client, monkeypatch):
    """A user polling a job must get an answer even if reclamation errors."""
    monkeypatch.setattr(api, "get_analysis_job", lambda job_id: {
        "job_id": "x", "status": "running", "result": None,
        "error_message": None, "stage": None})

    def explode():
        raise RuntimeError("reclaim exploded")

    monkeypatch.setattr(api, "reclaim_orphaned_jobs", explode)
    assert client.get("/analyze/status/x").status_code == 200


def test_missing_job_is_404_not_a_spinner(client, monkeypatch):
    monkeypatch.setattr(api, "get_analysis_job", lambda job_id: None)
    assert client.get("/analyze/status/nope").status_code == 404


# ── The reclamation query itself ───────────────────────────────────────────


def test_reclaim_distinguishes_never_started_from_died_midway():
    """`pending` and `running` are different facts and get different messages:
    one job was never picked up, the other was killed mid-analysis. Telling a
    user 'nothing was saved' is only honest if it is true of their case."""
    import db

    captured = {}

    class FakeCursor:
        def execute(self, sql, params=None):
            captured["sql"] = sql
            captured["params"] = params

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    with patch.object(db, "connection", lambda: FakeConn()):
        db.reclaim_orphaned_jobs(stale_minutes=25)

    sql = captured["sql"]
    assert "status IN ('pending', 'running')" in sql
    assert "WHEN status = 'running' THEN" in sql, "the two cases must differ"
    assert "COALESCE(started_at, created_at)" in sql, (
        "a pending job has no started_at, so the staleness clock must fall back "
        "to created_at or pending jobs are never reclaimed"
    )
    assert captured["params"] == (25,)
