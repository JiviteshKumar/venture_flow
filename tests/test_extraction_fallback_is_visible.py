"""The fallback must never be silent again.

This is a regression guard for the specific defect that started this whole
body of work, described exactly:

    `structured_extractor.extract_structured` called
    `pace_for(len(prompt), 1200)` where `prompt` did not exist. Every call
    raised NameError. A bare `except Exception` caught it. Extraction fell
    back to regex. Nothing anywhere said so -- not an error, not a
    low-confidence flag, not a field in the report. Every analysis produced
    for an unknown length of time came from the materially worse path, and
    the only reason anyone found out was a human comparing a report against
    the original PDF by hand.

The bug was one line. What made it expensive was that it was invisible. So
these tests do not check that the NameError is gone -- that would guard one
typo. They check the property that would have surfaced ANY version of it:

  1. A raising LLM path is logged loudly, not swallowed.
  2. The fallback reason travels in the return value.
  3. A programming error is distinguishable from a provider outage, because
     the response to each is completely different.
  4. The finished report says which path produced it, so the person reading
     the claims table can tell whether to trust it.

Every test breaks the LLM path deliberately and asserts the degradation is
observable. None of them require a live provider.
"""
from __future__ import annotations

import logging

import pytest

import structured_extractor
import ventureflow_agent


DECK = (
    "Acme Robotics\n"
    "Warehouse automation for mid-market distributors\n"
    "Problem\n"
    "Manual picking costs $18 per hour and error rates run at 4%\n"
    "Traction\n"
    "12 paying customers and $480,000 in annual recurring revenue\n"
)


def _break_llm(monkeypatch, exc):
    """Make the schema extractor's provider call raise `exc`."""
    def boom(*_a, **_k):
        raise exc
    monkeypatch.setattr(structured_extractor, "get_client", boom)


def test_a_broken_llm_path_still_returns_usable_output(monkeypatch):
    """Degrading is correct. Degrading silently is not -- see the tests below."""
    _break_llm(monkeypatch, RuntimeError("provider exploded"))
    result = structured_extractor.extract_structured(DECK, "Acme Robotics")
    assert result["_method"] == "regex_fallback"
    assert "claims" in result


def test_the_fallback_reason_travels_in_the_return_value(monkeypatch):
    """The report needs to be able to say WHY, not just that it happened."""
    _break_llm(monkeypatch, RuntimeError("provider exploded"))
    result = structured_extractor.extract_structured(DECK, "Acme Robotics")
    assert result.get("_fallback_reason"), "the fallback gave no reason at all"
    assert "provider exploded" in result["_fallback_reason"]


def test_a_programming_error_is_logged_as_an_error_not_a_warning(monkeypatch, caplog):
    """The original bug, in its own right.

    A NameError in this module and a 429 from Groq are not the same event: one
    needs a code change and one needs waiting. They were reported identically,
    at warning level, which is how a typo that disabled the entire schema path
    survived a full manual audit of the output it degraded.
    """
    _break_llm(monkeypatch, NameError("name 'prompt' is not defined"))
    with caplog.at_level(logging.DEBUG, logger="structured_extractor"):
        result = structured_extractor.extract_structured(DECK, "Acme Robotics")

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a bug in this module was not logged at ERROR level"
    assert any("BROKEN" in r.getMessage() for r in errors), (
        "the log does not distinguish a bug from a degraded provider"
    )
    assert "extraction bug" in result["_fallback_reason"]
    assert "NameError" in result["_fallback_reason"]


def test_a_provider_outage_is_not_reported_as_a_bug(monkeypatch, caplog):
    """The converse: a rate limit must not page someone about a code defect."""
    _break_llm(monkeypatch, RuntimeError("429 rate limit"))
    with caplog.at_level(logging.DEBUG, logger="structured_extractor"):
        result = structured_extractor.extract_structured(DECK, "Acme Robotics")

    assert "provider call failed" in result["_fallback_reason"]
    assert not any(
        "BROKEN" in r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.ERROR
    )


def test_the_report_states_that_it_was_built_by_the_fallback(caplog):
    """The half that matters to a human reading the output.

    Logging alone would have left the person reading the claims table with no
    way to know the table came from the worse extractor. The report has to
    carry its own provenance.
    """
    with caplog.at_level(logging.DEBUG, logger="ventureflow_agent"):
        report = ventureflow_agent.run_due_diligence(
            company_name="Acme Robotics",
            company_description=DECK,
            claims_to_verify=[],
            filing_text=DECK,
            extraction_method="regex_fallback",
            extraction_fallback_reason="provider call failed: RuntimeError: 429",
        )

    prov = report["extraction_provenance"]
    assert prov["is_fallback"] is True
    assert prov["method"] == "regex_fallback"
    assert "429" in prov["fallback_reason"]
    assert "REGEX FALLBACK" in prov["warning"]
    assert prov is report["sections"]["extraction_provenance"]

    assert any(
        r.levelno >= logging.ERROR and "EXTRACTION DEGRADED" in r.getMessage()
        for r in caplog.records
    ), "a degraded extraction did not log at ERROR level"


def test_a_healthy_run_is_not_labelled_degraded():
    """The flag has to mean something, so it must not fire on a good run."""
    report = ventureflow_agent.run_due_diligence(
        company_name="Acme Robotics",
        company_description=DECK,
        claims_to_verify=[],
        filing_text=DECK,
        extraction_method="llm_schema",
    )
    prov = report["extraction_provenance"]
    assert prov["is_fallback"] is False
    assert "warning" not in prov


@pytest.mark.parametrize("method", ["regex_fallback", "empty"])
def test_every_non_schema_path_counts_as_a_fallback(method):
    """`empty` degrades for a different reason and must be just as visible."""
    report = ventureflow_agent.run_due_diligence(
        company_name="Acme Robotics",
        company_description=DECK,
        claims_to_verify=[],
        filing_text=DECK,
        extraction_method=method,
    )
    assert report["extraction_provenance"]["is_fallback"] is True
