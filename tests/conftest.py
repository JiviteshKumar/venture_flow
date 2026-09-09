"""Suite-wide isolation of module-level state.

This project keeps finding the same defect in different costumes: a value that
lives at module scope, is mutated by one test, and is then read by every test
that runs afterwards. Each instance is invisible while tests run in a fixed
order and only one file touches the state.

Found so far:

  * `api.DEMO_ACCESS_TOKEN` -- `test_demo_gate.py` calls `importlib.reload(api)`
    with the token set. monkeypatch restores the environment variable but not
    the reloaded module constant, so every API test after it got 401. Fixed in
    that file with a teardown reload; surfaced when 21 new tests all passed
    alone and failed together.

  * `rate_limiter._memory_windows` -- a module-level defaultdict of request
    timestamps. Every TestClient request arrives from the same client key
    ("testclient"), so once the suite makes 30 requests inside one minute the
    limiter starts returning 429 to whichever unrelated test asks next. Found by
    running the suite under `pytest-randomly`: a demo-gate test asserting 401
    got 429 instead, and two worker-queue tests read `job_id` out of a 429 body.

  * `observability` counters -- harmless in itself, but a test asserting on
    aggregate counts would read another test's events.

The fixtures below reset all three before every test. They are autouse and live
in conftest so nothing has to remember to ask for them; the alternative is
rediscovering this class of bug a fourth time.

Run the suite in randomised order to keep finding these:

    python -m pytest tests/ -p randomly --randomly-seed=<n>
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Give every test a fresh request budget.

    Without this the suite's own volume of requests trips the production rate
    limit, and the resulting 429 surfaces as an unrelated assertion failure in
    whichever test happens to run next.
    """
    import rate_limiter

    rate_limiter._memory_windows.clear()
    yield
    rate_limiter._memory_windows.clear()


@pytest.fixture(autouse=True)
def reset_observability_counters():
    """Degradation counts are process-global and accumulate across tests."""
    try:
        import observability
    except ImportError:  # pragma: no cover - observability is not optional today
        yield
        return

    observability.reset_for_tests()
    yield
    observability.reset_for_tests()


@pytest.fixture(autouse=True)
def guard_demo_gate_state():
    """Fail loudly if a test leaves the demo gate enabled.

    Not a reset -- a detector. `api` is reloaded by test_demo_gate rather than
    monkeypatched, so silently clearing the token here would hide the leak
    instead of reporting it. This asserts the invariant that the gate is off
    outside the tests that deliberately turn it on.
    """
    yield
    api = sys.modules.get("api")
    if api is not None and getattr(api, "DEMO_ACCESS_TOKEN", None) is not None:
        pytest.fail(
            "DEMO_ACCESS_TOKEN was left set on the api module. Every API test "
            "running after this one will receive 401. The test that enabled the "
            "gate must restore module state (see test_demo_gate.py's "
            "restore_api_module_state fixture)."
        )


@pytest.fixture(autouse=True)
def disable_founder_research():
    """Never reach the open web for a founder name in a test.

    Same shape as the pacing fixture below, and found the same way. Founder
    research runs inline in `run_due_diligence` whenever a deck names no team,
    which is most decks and nearly every test fixture. It fires up to six
    DuckDuckGo searches and six page fetches, none of which any existing test
    opted into -- so adding it silently attached a live network dependency to
    every test that exercised the full pipeline. The suite went from finishing
    to hanging in `test_score_survives_provider_outage`, which mocks the LLM
    and the risk scorer but had no reason to know a web search now existed.

    Disabled rather than mocked because the module's own switch returns an
    explicit "not attempted", so a test can still tell a disabled search from a
    search that found nothing. Tests that DO exercise founder research patch
    `search_web` directly and are unaffected by this.
    """
    import agents.founder_research as founder_research

    original = founder_research.RESEARCH_ENABLED
    founder_research.RESEARCH_ENABLED = False
    yield
    founder_research.RESEARCH_ENABLED = original


@pytest.fixture(autouse=True)
def reset_daily_quota_breaker():
    """Give every test an unblocked provider.

    Fourth instance of the pattern this file exists to document, and it behaved
    exactly like the first three: `test_specialist_confidence.py` passed alone
    (16 of 16) and failed five tests inside the suite.

    `groq_client` trips a process-global breaker the first time it sees a
    tokens-per-day 429, after which `pace_for` raises for every later call --
    correct in production, where one exhausted quota should stop the other
    eleven components wasting six retries each, and poison in a test process,
    where one test simulating a quota failure silently disables the LLM path
    for everything that runs after it.
    """
    import groq_client

    groq_client.reset_quota_breaker()
    yield
    groq_client.reset_quota_breaker()


@pytest.fixture(autouse=True)
def no_live_scope_adjudication():
    """Keep the tech-scope gate running, but off the network.

    Unlike the fixtures above this does NOT disable the feature, because the
    gate now sits in front of /analyze and /upload-pdf and a disabled gate would
    leave the suite unable to notice if it started refusing valid decks.

    What is stubbed is only the LLM call, which is replaced by "unreachable" --
    a state the module is required to handle anyway, by falling back to its
    keyword signals and allowing anything it cannot classify. Tests that want to
    exercise adjudication patch `tech_scope._adjudicate` themselves.
    """
    import tech_scope

    original = tech_scope._adjudicate
    tech_scope._adjudicate = lambda text, company_name: None
    yield
    tech_scope._adjudicate = original


@pytest.fixture(autouse=True)
def disable_ocr():
    """Never run OCR unless a test asked for it.

    Third instance of the same shape as `disable_founder_research` above, and
    worth stating plainly because the pattern keeps recurring: a feature that is
    correct to run automatically in production becomes a hidden cost attached to
    every test the moment it is wired into a shared code path.

    OCR fires on any uploaded PDF whose text layer is thin (see
    `ocr_extractor.should_supplement`), which describes most small test
    fixtures, and it costs ~2 seconds per page of ONNX inference. Left enabled
    it would add minutes to a suite in which no test wants OCR at all.

    Disabled at the module switch rather than by mocking, so the tests in
    test_ocr_extractor.py that DO want it can re-enable it explicitly and get
    the real engine rather than a stub whose accuracy proves nothing.
    """
    import ocr_extractor

    original = ocr_extractor.ENABLED
    ocr_extractor.ENABLED = False
    yield
    ocr_extractor.ENABLED = original


@pytest.fixture(autouse=True)
def disable_groq_pacing():
    """Never sleep for a rate limiter in a test.

    groq_client.pace_for blocks to keep the pipeline inside the free tier's
    8,000 tokens/minute, which is correct in production and catastrophic in a
    suite: the tests mock the provider, so no tokens are actually spent, but the
    pacer still counts the estimate and starts inserting 60-second waits. The
    first run after pacing landed went from four minutes to a timeout.

    Reset the window too, so a test that does exercise the pacer directly starts
    from a clean budget rather than inheriting another test's spend.
    """
    import groq_client

    original = groq_client.PACING_ENABLED
    groq_client.PACING_ENABLED = False
    groq_client._pacer._window_start = 0.0
    groq_client._pacer._spent = 0
    yield
    groq_client.PACING_ENABLED = original


def _real_run_analysis_job():
    """The genuine implementation, captured once at import.

    Resolved here rather than inside the fixture because the fixture replaces
    the attribute: reading it at setup time would capture whatever the previous
    test left behind, which after the first test is the no-op.
    """
    import api

    return api._run_analysis_job


_REAL_RUN_ANALYSIS_JOB = _real_run_analysis_job()


@pytest.fixture(autouse=True)
def do_not_run_real_analyses():
    """Posting to /analyze in a test must not perform a full analysis.

    Fifth instance of the pattern this file exists to document, and the most
    expensive one yet.

    `/analyze` does two separate things: `create_analysis_job` writes the queue
    row, and `background_tasks.add_task(_run_analysis_job, ...)` runs the
    pipeline. Tests that wanted to assert something about the ENDPOINT --
    that the scope gate accepts a tech company, that a filename is cleaned
    before it reaches the queue -- mocked the first and left the second, which
    looks complete and is not: Starlette's TestClient executes background tasks
    inline, so every one of those tests quietly ran a real analysis.

    The cost was invisible because nothing failed. Each such test spent roughly
    30,000 Groq tokens -- about 15% of the free tier's entire daily budget, on a
    quota that is the binding constraint on this whole product -- took minutes
    of wall-clock time, and left a permanent report row in the production
    database. Three of them ran on every full suite invocation.

    Replaced with a no-op rather than left to fail, so the endpoint's own
    behaviour (202, the queue row, the returned job id) is unchanged and the
    tests asserting it keep passing. A test that genuinely wants the pipeline
    calls `run_due_diligence` directly, as tests/test_fusion_end_to_end.py and
    tests/test_extraction_fallback_is_visible.py already do, or overrides this
    fixture explicitly.
    """
    import api

    api._run_analysis_job = lambda job_id, payload: None
    yield
    api._run_analysis_job = _REAL_RUN_ANALYSIS_JOB


@pytest.fixture
def run_analyses_inline():
    """Opt back in to the background task disabled above.

    For the handful of tests that are ABOUT the queued job -- that it marks the
    row complete, that a persistence failure is recorded as failed. Those stub
    `run_due_diligence` and `persist_report` themselves, so nothing reaches
    Groq or the database; what they need is simply for the task to be invoked.

    Request this fixture BEFORE the assertions that depend on it. It restores
    the real function for the duration of the test.
    """
    import api

    api._run_analysis_job = _REAL_RUN_ANALYSIS_JOB
    yield
    api._run_analysis_job = lambda job_id, payload: None
