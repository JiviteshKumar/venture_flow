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
