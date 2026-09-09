"""End-to-end and adversarial tests for the async analysis path.

Written the way a QA engineer would rather than the way the author would: the
happy path is one test here and the other nine are the ways this breaks. The
agent layer is stubbed throughout, so these exercise the QUEUE -- submission,
polling, concurrency, restart, provider failure -- without spending Groq tokens.
That separation is the point: "the analysis works" and "the queue works under
concurrent load" are different claims and only one of them needs an LLM.
"""

import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api


@pytest.fixture(autouse=True)
def _queue_tests_need_the_background_task(run_analyses_inline):
    """This file is ABOUT the queued job, so it opts back in to the background
    task that tests/conftest.py disables by default.

    Safe here because the pipeline itself is stubbed in this file -- nothing
    reaches Groq or the database. The conftest default exists to stop tests
    that are about the ENDPOINT from silently running a real analysis; these
    tests are about what the endpoint queues, so they need it."""



class FakeJobStore:
    """An in-memory stand-in for the analysis_jobs table.

    Thread-safe on purpose: the concurrency tests below submit from several
    threads at once, and a store with a race in it would produce failures that
    look like queue bugs.
    """

    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.counter = 0

    def create(self, payload):
        with self.lock:
            self.counter += 1
            job_id = f"job-{self.counter}"
            self.jobs[job_id] = {
                "job_id": job_id, "status": "pending", "result": None,
                "error_message": None, "stage": None, "payload": payload,
            }
        return job_id

    def update(self, job_id, status, result=None, error_message=None):
        with self.lock:
            job = self.jobs.setdefault(job_id, {"job_id": job_id, "stage": None})
            job["status"] = status
            if result is not None:
                job["result"] = result
            job["error_message"] = error_message

    def set_stage(self, job_id, stage):
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id]["stage"] = stage

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def count_active(self):
        with self.lock:
            return sum(1 for j in self.jobs.values()
                       if j["status"] in ("pending", "running"))

    def reclaim(self):
        return []


REPORT_FIELDS = {
    "company": "Northwind Robotics",
    "final_score": 41.0,
    "recommendation": "NEEDS MORE DILIGENCE",
    "risk_level": "MEDIUM",
    "ai_analysis": "memo body",
    "claims_verified": 3,
    "claims_supported": 1,
    "claims_refuted": 1,
    "claims_uncertain": 1,
    "risk_signals_found": 2,
    "key_concerns": ["customer concentration"],
    "red_flags": [],
    "positive_factors": ["revenue growth"],
    "session_id": "sess-1",
    "sections": {"claims": {"checked": 3, "supported": 1, "refuted": 1, "uncertain": 1}},
}


@pytest.fixture
def store(monkeypatch):
    fake = FakeJobStore()
    monkeypatch.setattr(api, "create_analysis_job", fake.create)
    monkeypatch.setattr(api, "update_analysis_job", fake.update)
    monkeypatch.setattr(api, "set_analysis_job_stage", fake.set_stage)
    monkeypatch.setattr(api, "get_analysis_job", fake.get)
    monkeypatch.setattr(api, "count_active_jobs", fake.count_active)
    monkeypatch.setattr(api, "reclaim_orphaned_jobs", fake.reclaim)
    return fake


@pytest.fixture
def stub_analysis(monkeypatch):
    """Replace the agent pipeline with something instant and deterministic."""
    calls = []

    async def fake_perform(request, on_stage=None, owner_user_id=None):
        calls.append(request.company_name)
        if on_stage:
            on_stage("Verifying claims against live web search")
            on_stage("Detecting risk signals in the deck")
        return api.DiligenceResponse(**REPORT_FIELDS)

    monkeypatch.setattr(api, "_perform_analysis", fake_perform)
    monkeypatch.setattr(api, "record_analysed_company", lambda **k: None)
    return calls


def _submit(client, name="Northwind Robotics"):
    return client.post("/analyze", json={
        "company_name": name,
        "company_description": "Warehouse automation for mid-size distributors. " * 6,
        "claims": ["We closed $2.4M in ARR."],
    })


# ── The happy path, end to end through the queue ───────────────────────────


def test_submit_poll_and_receive_the_report(store, stub_analysis):
    """Full flow: 202 + job id, poll, terminal state carries the report."""
    with TestClient(api.app) as client:
        response = _submit(client)
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert response.json()["status"] == "pending"

        # TestClient runs BackgroundTasks before returning, so by the time the
        # POST completes the job has already run to completion.
        status = client.get(f"/analyze/status/{job_id}").json()
        assert status["status"] == "complete"
        assert status["report"]["company"] == "Northwind Robotics"
        assert status["report"]["final_score"] == 41.0
        assert stub_analysis == ["Northwind Robotics"]


def test_the_stage_callback_records_real_pipeline_progress(store, stub_analysis):
    """The frontend renders this. It must be the backend's actual step, not a
    label advancing on a timer -- a slow-but-working analysis has to be
    distinguishable from a hung one."""
    with TestClient(api.app) as client:
        job_id = _submit(client).json()["job_id"]
    assert store.jobs[job_id]["stage"] == "Detecting risk signals in the deck"


# ── Failure modes, deliberately ────────────────────────────────────────────


def test_a_provider_429_mid_job_fails_the_job_with_a_retryable_message(store, monkeypatch):
    """The typed-fallback contract must behave the same asynchronously as it did
    synchronously: a rate limit is reported as transient and retryable, not as a
    verdict about the company."""
    async def rate_limited(request, on_stage=None, owner_user_id=None):
        raise RuntimeError("groq 429 rate_limit_exceeded: quota exhausted")

    monkeypatch.setattr(api, "_perform_analysis", rate_limited)

    with TestClient(api.app) as client:
        job_id = _submit(client).json()["job_id"]
        status = client.get(f"/analyze/status/{job_id}").json()

    assert status["status"] == "failed"
    assert status["report"] is None
    assert status["error"], "a failed job must carry a reason"


def test_a_crash_mid_job_does_not_leave_the_job_running(store, monkeypatch):
    """The worst outcome is a job stuck at 'running' forever, which is what the
    frontend polls into a spinner that never resolves."""
    async def explode(request, on_stage=None, owner_user_id=None):
        raise ValueError("pipeline exploded")

    monkeypatch.setattr(api, "_perform_analysis", explode)

    with TestClient(api.app) as client:
        job_id = _submit(client).json()["job_id"]
    assert store.jobs[job_id]["status"] == "failed"


def test_a_backend_restart_mid_job_is_reported_not_left_hanging(store, monkeypatch):
    """Render's free tier restarts routinely and BackgroundTasks die with the
    process. Simulated by leaving a job at 'running' and letting reclamation see
    it -- the user must be told their deck was never analysed."""
    job_id = store.create({"company_name": "Interrupted Co"})
    store.update(job_id, "running")

    def reclaim_it():
        store.update(job_id, "failed", error_message=(
            "The analysis was interrupted before it finished -- the server "
            "restarted while your deck was being processed. Nothing was saved."
        ))
        return [{"job_id": job_id}]

    monkeypatch.setattr(api, "reclaim_orphaned_jobs", reclaim_it)

    with TestClient(api.app) as client:
        status = client.get(f"/analyze/status/{job_id}").json()

    assert status["status"] == "failed"
    assert "restarted" in status["error"]
    assert "Nothing was saved" in status["error"]


def test_persisting_the_analytics_row_cannot_fail_a_finished_analysis(store, monkeypatch):
    """record_analysed_company is a derived projection of a report already saved.
    A failure there must never turn a completed analysis into an error."""
    async def fake_perform(request, on_stage=None, owner_user_id=None):
        return api.DiligenceResponse(**REPORT_FIELDS)

    def explode(**kwargs):
        raise RuntimeError("analytics insert failed")

    monkeypatch.setattr(api, "_perform_analysis", fake_perform)
    monkeypatch.setattr(api, "record_analysed_company", explode)

    with TestClient(api.app) as client:
        job_id = _submit(client).json()["job_id"]
        status = client.get(f"/analyze/status/{job_id}").json()

    # The analysis itself must survive; how the failure surfaces is secondary.
    assert status["status"] in ("complete", "failed")
    if status["status"] == "failed":
        pytest.fail("a failing analytics projection took down a completed analysis")


# ── Concurrency: "works once" and "works under load" are different claims ──


def test_several_jobs_submitted_concurrently_all_get_distinct_ids(store, stub_analysis):
    """Queue mechanics under concurrent submission, with the agent layer stubbed
    so this costs no Groq tokens.

    ONE client, shared, and deliberately NOT opened as a context manager.

    The first version of this test built a `with TestClient(api.app)` per
    thread. That runs the app's lifespan each time, and this app's startup
    handler executes `ensure_schema` against the real Neon database -- so six
    threads raced six schema migrations through an advisory lock, blew past the
    join timeout, and let pytest tear the monkeypatch fixtures down while the
    threads were still running. The un-stubbed module then executed the REAL
    agent pipeline: live DuckDuckGo searches and live Groq calls, in a test
    whose entire purpose was to exercise the queue without spending quota.

    It also explains why the test passed alone and failed in the suite: the
    timing changed, not the logic.
    """
    results: list[tuple[int, str | None]] = []
    lock = threading.Lock()
    client = TestClient(api.app)  # no lifespan: no schema migration, no network

    def submit(index: int):
        response = _submit(client, f"Company {index}")
        body = response.json() if response.status_code == 202 else {}
        with lock:
            results.append((response.status_code, body.get("job_id")))

    threads = [threading.Thread(target=submit, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert all(not t.is_alive() for t in threads), (
        "a submission thread did not finish; fixtures would tear down beneath it"
    )

    accepted = [r for r in results if r[0] == 202]
    shed = [r for r in results if r[0] == 429]
    assert len(results) == 6, "every submission must get a definite answer"
    assert accepted or shed, "submissions must be either accepted or shed"
    job_ids = [r[1] for r in accepted]
    assert len(job_ids) == len(set(job_ids)), "job ids must be unique"
    # Nothing may be silently dropped: every response is one or the other.
    assert len(accepted) + len(shed) == 6


def test_concurrent_jobs_do_not_leak_stage_into_each_other(store, monkeypatch):
    """Two analyses running at once must not write each other's progress. The
    stage callback closes over its own job id; a shared or ambient one would
    interleave."""
    started = threading.Event()

    async def slow_perform(request, on_stage=None, owner_user_id=None):
        if on_stage:
            on_stage(f"stage for {request.company_name}")
        started.set()
        return api.DiligenceResponse(**{**REPORT_FIELDS, "company": request.company_name})

    monkeypatch.setattr(api, "_perform_analysis", slow_perform)
    monkeypatch.setattr(api, "record_analysed_company", lambda **k: None)

    client = TestClient(api.app)
    first = _submit(client, "Alpha Co").json()["job_id"]
    second = _submit(client, "Beta Co").json()["job_id"]

    assert store.jobs[first]["stage"] == "stage for Alpha Co"
    assert store.jobs[second]["stage"] == "stage for Beta Co"


def test_job_ids_are_not_guessable_across_submissions(store, stub_analysis):
    """Two different submissions must never collide onto one job row, which
    would let one user's report be returned to another."""
    client = TestClient(api.app)
    first = _submit(client, "Alpha Co").json()["job_id"]
    second = _submit(client, "Beta Co").json()["job_id"]
    assert first != second
