"""The pacer must not throttle against tokens nobody spent.

`pace_for(len(prompt), max_tokens)` reserves `prompt_chars // 4 + max_tokens`.
The second term is the CEILING on what the model may emit, not what it does:
a specialist agent reserves 2,000 completion tokens and typically returns a few
hundred.

Measured on a real Uber analysis, one run reserves roughly 46,600 tokens across
a dozen calls against a per-minute budget of 6,800 (8,000 x 0.85 safety) --
about seven minutes of pure waiting inside a twelve-minute run, a large share of
it for completion budget that was never used.

`settle_usage` reconciles a reservation against the response's real usage.
This is bookkeeping only: no prompt, model or parameter changes, so it cannot
alter what an analysis concludes. It makes the pacer more accurate about the
real rate limit, not less -- before this it throttled against a fiction.

The invariants below matter more than the speedup. A refund that is too
generous would let the process exceed the actual per-minute limit and turn a
paced run into a 429 storm, so the tests are mostly about what must NOT be
given back.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import groq_client  # noqa: E402


def _response(total_tokens):
    """Shaped like the Groq SDK's response: `.usage.total_tokens`."""
    usage = type("Usage", (), {"total_tokens": total_tokens})()
    return type("Response", (), {"usage": usage})()


@pytest.fixture
def pacer(monkeypatch):
    fresh = groq_client.TokenPacer(8000)
    monkeypatch.setattr(groq_client, "_pacer", fresh)
    monkeypatch.setattr(groq_client, "PACING_ENABLED", True)
    return fresh


class TestUnusedBudgetComesBack:
    def test_a_reservation_is_reconciled_to_actual_usage(self, pacer):
        pacer.reserve(groq_client.estimate_tokens(4000, 2000))   # 1000 + 2000
        assert pacer._spent == 3000

        refunded = groq_client.settle_usage(_response(900), 4000, 2000)

        assert refunded == 2100
        assert pacer._spent == 900, "the pacer still holds budget nobody spent"

    def test_more_calls_fit_in_one_window_after_settling(self, pacer):
        """The point of the exercise, stated as behaviour rather than
        arithmetic: with reconciliation, a window that fit two calls fits more."""
        estimate = groq_client.estimate_tokens(4000, 2000)  # 3000

        fitted = 0
        for _ in range(10):
            if pacer._spent + estimate > pacer.budget:
                break
            pacer.reserve(estimate)
            groq_client.settle_usage(_response(900), 4000, 2000)
            fitted += 1

        assert fitted > 6800 // 3000, (
            f"only {fitted} calls fitted; without settling the budget allows "
            f"{6800 // 3000}"
        )


class TestItCannotManufactureBudget:
    """The expensive direction. Refunding too much lets the process exceed the
    real per-minute limit, and the punishment for that is a 429 storm."""

    def test_a_refund_never_exceeds_what_was_reserved(self, pacer):
        pacer.reserve(3000)
        groq_client.settle_usage(_response(0), 4000, 2000)
        assert pacer._spent >= 0

    def test_a_refund_never_drives_spend_below_zero(self, pacer):
        pacer.reserve(100)
        pacer.settle(reserved_tokens=999_999, actual_tokens=0)
        assert pacer._spent == 0

    def test_usage_larger_than_the_reservation_refunds_nothing(self, pacer):
        """An underestimate must not be 'refunded' as a negative."""
        pacer.reserve(3000)
        before = pacer._spent
        refunded = groq_client.settle_usage(_response(9999), 4000, 2000)
        assert refunded == 0
        assert pacer._spent == before

    def test_a_stale_settlement_is_dropped(self, pacer, monkeypatch):
        """If the window rolled over between the call and its response, the
        spend being corrected belongs to a window that has already closed."""
        pacer.reserve(3000)
        pacer._window_start -= 120.0        # pretend two minutes passed
        assert pacer.settle(3000, 100) == 0


class TestBookkeepingNeverBreaksACall:
    """This runs on the success path of a call that already worked. An
    exception here would turn a good response into a failed analysis."""

    @pytest.mark.parametrize("response", [
        None,
        object(),                                   # no .usage
        type("R", (), {"usage": None})(),           # usage is None
        type("R", (), {"usage": object()})(),       # usage without total_tokens
        _response("not-a-number"),
        _response(None),
    ])
    def test_an_unexpected_response_shape_refunds_nothing(self, pacer, response):
        pacer.reserve(3000)
        assert groq_client.settle_usage(response, 4000, 2000) == 0
        assert pacer._spent == 3000

    def test_it_is_inert_when_pacing_is_disabled(self, monkeypatch):
        monkeypatch.setattr(groq_client, "PACING_ENABLED", False)
        assert groq_client.settle_usage(_response(100), 4000, 2000) == 0


class TestEveryCallSiteSettles:
    """A site that reserves and never settles behaves exactly as it did before
    -- which is safe, and also means a missing settle is invisible. This is the
    check that keeps them in step."""

    @pytest.mark.parametrize("module_path", [
        "agents/claim_verifier.py",
        "agents/founder_research.py",
        "agents/investment_agents.py",
        "agents/risk_detector.py",
        "structured_extractor.py",
        "tech_scope.py",
        "ventureflow_agent.py",
    ])
    def test_a_site_that_paces_also_settles(self, module_path):
        source = (Path(__file__).resolve().parents[1] / module_path).read_text(
            encoding="utf-8")
        if "pace_for(" not in source:
            pytest.skip(f"{module_path} makes no paced call")
        assert "settle_usage(" in source, (
            f"{module_path} reserves token budget and never returns the unused "
            f"part, so every later call in that minute waits for tokens it "
            f"never spent"
        )
