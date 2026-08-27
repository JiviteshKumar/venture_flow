"""Tests for structured logging and degradation tracking.

The events tracked here are the ones a crash-only error tracker sees NONE of.
Every bug found in the last three sessions -- the constant-30 score, the claim
verifier judging 2011 metrics against 2026 evidence, the degradation flag that
string-matched prose, the corpus collector recording fetch failures as "no risk
language" -- was a typed fallback, not an exception. The code caught the error,
degraded politely, logged a line, and returned a plausible answer.
"""

import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import observability


@pytest.fixture(autouse=True)
def clean_counters():
    observability.reset_for_tests()
    yield
    observability.reset_for_tests()


def test_degradation_events_aggregate_by_event_and_component():
    """The question this exists to answer: how often is the analysis actually
    degraded in practice. Nothing could answer it before."""
    observability.track_degradation("groq_rate_limited", component="market", reason="429")
    observability.track_degradation("groq_rate_limited", component="market", reason="429")
    observability.track_degradation("groq_rate_limited", component="team", reason="429")

    counts = observability.snapshot()["degradation_counts"]
    assert counts["groq_rate_limited:market"] == 2
    assert counts["groq_rate_limited:team"] == 1
    assert observability.snapshot()["total_degradation_events"] == 3


def test_tracking_never_raises_even_on_unserialisable_details():
    """Tracking a problem must not be able to cause one."""
    class Unserialisable:
        def __repr__(self):
            raise RuntimeError("cannot repr")

    observability.track_degradation(
        "weird", component="x", reason="y", payload=Unserialisable(),
    )
    # The call returning at all is the assertion.


def test_job_context_attaches_to_events():
    with observability.job_context(job_id="job-9", company="Northwind"):
        observability.track_degradation("extraction_empty", component="extractor")
    recent = observability.snapshot()["recent_events"]
    assert recent[-1]["job_id"] == "job-9"
    assert recent[-1]["company"] == "Northwind"


def test_job_context_is_restored_after_the_block():
    with observability.job_context(job_id="job-1"):
        pass
    observability.track_degradation("after", component="x")
    assert observability.snapshot()["recent_events"][-1]["job_id"] is None


def test_nested_job_contexts_do_not_leak():
    with observability.job_context(job_id="outer"):
        with observability.job_context(job_id="inner"):
            observability.track_degradation("a", component="x")
        observability.track_degradation("b", component="x")
    events = {e["event"]: e["job_id"] for e in observability.snapshot()["recent_events"]}
    assert events["a"] == "inner"
    assert events["b"] == "outer"


def test_json_formatter_emits_one_parseable_object_per_line():
    record = logging.LogRecord(
        name="test", level=logging.WARNING, pathname=__file__, lineno=1,
        msg="something %s", args=("happened",), exc_info=None,
    )
    line = observability.JsonFormatter().format(record)
    parsed = json.loads(line)
    assert parsed["level"] == "WARNING"
    assert parsed["message"] == "something happened"
    assert "ts" in parsed


def test_json_formatter_includes_extra_fields_prefixed_vf():
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname=__file__, lineno=1,
        msg="m", args=(), exc_info=None,
    )
    record.vf_event = "groq_rate_limited"
    record.vf_component = "market"
    parsed = json.loads(observability.JsonFormatter().format(record))
    assert parsed["event"] == "groq_rate_limited"
    assert parsed["component"] == "market"


def test_json_formatter_survives_an_unserialisable_message():
    class Bad:
        def __str__(self):
            return "ok-string"

    record = logging.LogRecord(
        name="t", level=logging.ERROR, pathname=__file__, lineno=1,
        msg="%s", args=(Bad(),), exc_info=None,
    )
    parsed = json.loads(observability.JsonFormatter().format(record))
    assert parsed["level"] == "ERROR"


def test_sentry_is_optional_and_reports_its_own_state(monkeypatch):
    """A fresh clone has no DSN. That must be a stated state, not a crash and
    not a silent no-op -- the same contract rate_limiter.py uses for Redis."""
    monkeypatch.setattr(observability, "SENTRY_DSN", "")
    state = observability.init_sentry()
    assert "disabled" in state
    assert "SENTRY_DSN" in state
    assert observability.snapshot()["sentry"] == state


def test_recent_events_are_bounded():
    for i in range(observability.MAX_RECENT_EVENTS + 50):
        observability.track_degradation("spam", component="x", reason=str(i))
    with observability._counter_lock:
        assert len(observability._recent_events) <= observability.MAX_RECENT_EVENTS
    # Counts are not bounded -- only the sample of recent records is.
    assert observability.snapshot()["degradation_counts"]["spam:x"] == \
        observability.MAX_RECENT_EVENTS + 50
