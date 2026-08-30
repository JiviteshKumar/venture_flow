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
