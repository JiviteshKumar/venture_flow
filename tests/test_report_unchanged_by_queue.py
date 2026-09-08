"""Part A must not have changed what an analysis produces -- only how it is
invoked and how the result gets back.

This is a field-by-field comparison, not a "it doesn't crash" check.

An important scoping note, stated rather than glossed: a byte-identical
comparison against a report generated BEFORE this session is not possible,
because Parts D and F deliberately changed behaviour -- the specialist
confidence prompt was rewritten and the risk severity model was replaced. Those
changes are intended and are measured elsewhere.

So what this isolates is Part A specifically: the same analysis function, the
same input, routed through the synchronous path and through the job queue, must
produce the same report. Any difference is plumbing contamination, which is the
only thing Part A could have broken.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api
from tests.test_worker_queue_integration import REPORT_FIELDS, FakeJobStore

FIXED_DECK = {
    "company_name": "Northwind Robotics",
    "company_description": (
        "Warehouse automation for mid-size third-party logistics operators. "
        "We closed $2.4M in ARR this year, up from $310K, across 62 customers. "
        "Monthly burn is $410K against $1.1M cash on hand."
    ),
    "claims": ["We closed $2.4M in ARR across 62 customers."],
}


@pytest.fixture
def wired(monkeypatch):
    store = FakeJobStore()
    monkeypatch.setattr(api, "create_analysis_job", store.create)
    monkeypatch.setattr(api, "update_analysis_job", store.update)
    monkeypatch.setattr(api, "set_analysis_job_stage", store.set_stage)
    monkeypatch.setattr(api, "get_analysis_job", store.get)
    monkeypatch.setattr(api, "count_active_jobs", store.count_active)
    monkeypatch.setattr(api, "reclaim_orphaned_jobs", store.reclaim)
    monkeypatch.setattr(api, "record_analysed_company", lambda **k: None)

    seen = []

    async def deterministic(request, on_stage=None, owner_user_id=None):
        # Deterministic and dependent on the request, so a plumbing bug that
        # dropped or mangled a field would change the output.
        seen.append(request.model_dump())
        return api.DiligenceResponse(**{**REPORT_FIELDS, "company": request.company_name})

    monkeypatch.setattr(api, "_perform_analysis", deterministic)
    return store, seen


def test_the_queue_passes_the_request_through_unmodified(wired):
    """The job payload round-trips through JSON in the database. A field lost or
    coerced there would silently change the analysis input."""
    store, seen = wired
    with TestClient(api.app) as client:
        client.post("/analyze", json=FIXED_DECK)

    assert len(seen) == 1
    delivered = seen[0]
    for key, value in FIXED_DECK.items():
        assert delivered[key] == value, f"{key} was altered in transit"


def test_report_is_field_for_field_identical_through_the_queue(wired):
    """The comparison that matters. Same analysis, same input, two routes."""
    store, _ = wired

    with TestClient(api.app) as client:
        response = client.post("/analyze", json=FIXED_DECK)
        job_id = response.json()["job_id"]
        via_queue = client.get(f"/analyze/status/{job_id}").json()["report"]

    expected = api.DiligenceResponse(
        **{**REPORT_FIELDS, "company": FIXED_DECK["company_name"]}
    ).model_dump()

    assert via_queue is not None, "a completed job must carry its report"
    assert set(via_queue) == set(expected), "the report's field set changed"
    differences = {
        key: (expected[key], via_queue[key])
        for key in expected
        if expected[key] != via_queue[key]
    }
    assert not differences, f"queue path altered report fields: {differences}"


def test_every_scoring_field_survives_the_round_trip(wired):
    """Named explicitly, because these are the fields a user acts on and a
    silent type coercion through JSONB would be easy to miss."""
    store, _ = wired
    with TestClient(api.app) as client:
        job_id = client.post("/analyze", json=FIXED_DECK).json()["job_id"]
        report = client.get(f"/analyze/status/{job_id}").json()["report"]

    assert report["final_score"] == REPORT_FIELDS["final_score"]
    assert isinstance(report["final_score"], float)
    assert report["recommendation"] == REPORT_FIELDS["recommendation"]
    assert report["risk_level"] == REPORT_FIELDS["risk_level"]
    assert report["claims_verified"] == REPORT_FIELDS["claims_verified"]
    assert report["claims_supported"] == REPORT_FIELDS["claims_supported"]
    assert report["claims_refuted"] == REPORT_FIELDS["claims_refuted"]
    assert report["key_concerns"] == REPORT_FIELDS["key_concerns"]
    assert report["ai_analysis"] == REPORT_FIELDS["ai_analysis"]


def test_an_unknown_request_field_is_rejected_rather_than_silently_dropped(wired):
    """A bug this session's own tests walked into.

    The pipeline parameter is `claims_to_verify`; the API field is `claims`.
    Before this fix, posting `claims_to_verify` returned 202 with a job id and
    produced a completed analysis that had verified ZERO claims -- no error, no
    warning, a confident report about a deck whose claims were never checked.

    Analysing something other than what was submitted is worse than refusing
    the request.
    """
    with TestClient(api.app) as client:
        response = client.post("/analyze", json={
            "company_name": "Typo Co",
            "company_description": "A" * 200,
            "claims_to_verify": ["this field name is wrong"],
        })

    assert response.status_code == 422
    assert "claims_to_verify" in response.text
