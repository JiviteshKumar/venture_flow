"""A failed analysis job must always carry a real, specific error message.

This is the gap that let a silent failure ship: `_run_analysis_job` caught
every exception and stored the fixed string "Analysis could not be completed.
Please retry." regardless of cause, so an exhausted API quota, an unreachable
database and a genuine pipeline bug were indistinguishable on screen -- and
"retry" was wrong advice for two of the three. Nothing in the existing suite
exercised the failure path at all.
"""

import asyncio
from typing import Any

import pytest

import api


class _Recorder:
    """Stands in for db.update_analysis_job and remembers what was written."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, job_id: str, status: str, result=None, error_message=None) -> None:
        self.calls.append((job_id, status, result, error_message))

    @property
    def failure(self) -> tuple[Any, ...] | None:
        return next((c for c in self.calls if c[1] == "failed"), None)


def _run_job_with_failure(monkeypatch, exc: BaseException) -> _Recorder:
    recorder = _Recorder()
    monkeypatch.setattr(api, "update_analysis_job", recorder)

    # Signature must mirror _perform_analysis, which takes the stage callback
    # and the owner of the report the analysis will produce. A stub that omits
    # a parameter fails with a TypeError before the exception under test is
    # ever raised, so the test then asserts against the wrong failure.
    async def boom(_request, on_stage=None, owner_user_id=None):
        raise exc

    monkeypatch.setattr(api, "_perform_analysis", boom)
    asyncio.run(api._run_analysis_job("job-1", {
        "company_name": "Test Co", "company_description": "x" * 60, "claims": [],
    }))
    return recorder


def test_failed_job_records_a_failure_row(monkeypatch):
    recorder = _run_job_with_failure(monkeypatch, RuntimeError("kaboom in the pipeline"))
    assert recorder.failure is not None, "a failing job must be marked failed, not left running"


def test_failed_job_message_is_specific_not_the_generic_fallback(monkeypatch):
    recorder = _run_job_with_failure(monkeypatch, RuntimeError("kaboom in the pipeline"))
    message = recorder.failure[3]
    assert message, "a failed job must carry an error message, never None or empty"
    # The frontend substitutes its own generic text when `error` is empty; the
    # backend must never *be* that generic text.
    assert message != "Analysis could not be completed. Please retry."
    assert "kaboom in the pipeline" in message, "the real cause must reach the user"


@pytest.mark.parametrize(
    "text,expected_hint",
    [
        # The exact shape Groq returns when the daily token budget is gone.
        ("Error code: 429 - rate_limit_exceeded ... on tokens per day (TPD): Limit 200000", "daily token quota"),
        ("Error code: 429 - rate_limit_exceeded on tokens per minute", "rate limit"),
        ("Error code: 404 - model_not_found", "groq model"),
        ("could not translate host name to address", "database"),
    ],
)
def test_known_failures_are_translated_into_actionable_advice(text, expected_hint):
    message = api._describe_failure(RuntimeError(text)).lower()
    assert expected_hint in message


def test_unknown_failures_still_produce_a_useful_message():
    """The translator must not swallow causes it does not recognise."""
    message = api._describe_failure(ValueError("something nobody anticipated"))
    assert "ValueError" in message
    assert "something nobody anticipated" in message


def test_describe_failure_never_raises_on_odd_exceptions():
    class Weird(Exception):
        def __str__(self) -> str:
            return "‑  unicode and a very long tail " + "x" * 5000

    message = api._describe_failure(Weird())
    assert isinstance(message, str) and message
