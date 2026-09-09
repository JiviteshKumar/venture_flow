"""The deck's vintage must survive the whole live API path into the LLM prompt.

WHY THIS FILE EXISTS SEPARATELY FROM test_pipeline_argument_binding.py

That file checks the call site structurally -- that `api._perform_analysis`
binds pipeline arguments by keyword and that the year regex has no control
characters. Those are necessary and they are not sufficient, because the bug
they guard against was invisible to exactly that kind of check for weeks.

The failure was that the temporal grounding worked perfectly in
`ml/scripts/run_real_deck_corpus.py` -- an offline script that passes
`deck_date` by keyword -- and never once ran in production, where `api.py`
passed twelve positional arguments and put the stage callback into the
`deck_date` slot. Every offline measurement said the fix was working. No test
went through the route a user takes.

So these tests POST to `/analyze` and assert on what `verify_claim` actually
receives and on what reaches the prompt. Nothing here trusts an intermediate
layer to have passed the value along, because that is precisely the layer that
silently did not.

No Groq: the provider boundary is stubbed, but everything above it is the real
code path.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api
import ventureflow_agent
from agents import claim_verifier
from tests.test_worker_queue_integration import FakeJobStore


@pytest.fixture(autouse=True)
def _queue_tests_need_the_background_task(run_analyses_inline):
    """This file is ABOUT the queued job, so it opts back in to the background
    task that tests/conftest.py disables by default.

    Safe here because the pipeline itself is stubbed below -- nothing in this
    file reaches Groq or the database. The conftest default exists to stop
    tests that are about the ENDPOINT from silently running a real analysis;
    these tests are about what the endpoint queues, so they need it."""

DECK_TEXT = (
    "Northwind Robotics 2011 seed deck. Warehouse automation for mid-size "
    "logistics operators. We have 800 paying users and $310K in annual revenue."
)


@pytest.fixture
def wired(monkeypatch):
    """Real pipeline, stubbed provider boundary. Records every verify_claim call."""
    store = FakeJobStore()
    monkeypatch.setattr(api, "create_analysis_job", store.create)
    monkeypatch.setattr(api, "update_analysis_job", store.update)
    monkeypatch.setattr(api, "set_analysis_job_stage", store.set_stage)
    monkeypatch.setattr(api, "get_analysis_job", store.get)
    monkeypatch.setattr(api, "count_active_jobs", store.count_active)
    monkeypatch.setattr(api, "reclaim_orphaned_jobs", store.reclaim)
    monkeypatch.setattr(api, "record_analysed_company", lambda **k: None)
    monkeypatch.setattr(api, "persist_report", lambda **k: "report-1")
    monkeypatch.setattr(api, "find_similar_companies", lambda *a, **k: [])

    seen: list[dict] = []

    def fake_verify(claim_text, **kwargs):
        seen.append({"claim": claim_text, **kwargs})
        return {
            "claim": claim_text, "verdict": "NOT_ENOUGH_INFO", "confidence": 0.4,
            "reasoning": "stub", "key_evidence": "", "sources": [],
            "total_sources": 1, "full_pages_read": 0,
        }

    # Patched where it is USED, not where it is defined -- ventureflow_agent
    # imported the name at module load.
    monkeypatch.setattr(ventureflow_agent, "verify_claim", fake_verify)
    monkeypatch.setattr(ventureflow_agent, "score_risk", lambda *a, **k: {
        "risk_level": "LOW", "overall_score": 20, "key_concerns": [],
        "positive_factors": [], "red_flags": [], "total_signals": 0,
    })
    monkeypatch.setattr(ventureflow_agent, "run_investment_agents", lambda **k: {
        "market": {"confidence": 0.5, "signals": []},
    })
    monkeypatch.setattr(ventureflow_agent, "build_context", lambda *a: {"relevant_reports": []})
    monkeypatch.setattr(ventureflow_agent, "format_context_for_llm", lambda *a: "")

    from types import SimpleNamespace

    monkeypatch.setattr(ventureflow_agent, "get_client", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **_: SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="memo"))]
            )
        ))
    ))
    return store, seen


def _post(client, **extra):
    payload = {
        "company_name": "Northwind Robotics",
        "company_description": DECK_TEXT,
        "claims": ["We have 800 paying users."],
    }
    payload.update(extra)
    return client.post("/analyze", json=payload)


def test_an_explicit_deck_date_reaches_the_claim_verifier(wired, tmp_path, monkeypatch):
    """The exact assertion the missing test would have made.

    Before the fix, `as_of` here was `<function record_stage at 0x...>`.
    """
    monkeypatch.chdir(tmp_path)
    _store, seen = wired
    client = TestClient(api.app)
    assert _post(client, deck_date="2011").status_code == 202

    assert seen, "verify_claim was never called through the live API path"
    as_of = seen[0].get("as_of")
    assert as_of == "2011", f"as_of reached the verifier as {as_of!r}"
    assert not callable(as_of), "the stage callback landed in as_of -- the original bug"
    assert isinstance(as_of, str)


def test_without_an_explicit_date_the_year_is_inferred_from_the_deck(wired, tmp_path, monkeypatch):
    """The fallback path, which is what most real uploads take: the UI has no
    date field of its own yet, so inference is what actually runs."""
    monkeypatch.chdir(tmp_path)
    _store, seen = wired
    client = TestClient(api.app)
    assert _post(client).status_code == 202

    assert seen
    assert seen[0].get("as_of") == "2011", (
        "the year was not inferred from deck text -- this is the corrupted-regex bug"
    )


def test_a_deck_with_no_year_yields_an_empty_as_of_not_a_guess(wired, tmp_path, monkeypatch):
    """Empty is the honest answer. A fabricated year would be worse than none:
    the verifier's prompt branches on it and would anchor to a wrong period."""
    monkeypatch.chdir(tmp_path)
    _store, seen = wired
    client = TestClient(api.app)
    response = client.post("/analyze", json={
        "company_name": "Undated Co",
        "company_description": "A warehouse automation platform with paying users.",
        "claims": ["We have paying users."],
    })
    assert response.status_code == 202
    assert seen
    assert seen[0].get("as_of") == ""


def test_the_company_and_context_also_survive_the_trip(wired, tmp_path, monkeypatch):
    """Same class of bug, adjacent arguments. Company scoping is what took
    retrieval on-topic rate from 14% to 97%, so it is worth pinning too."""
    monkeypatch.chdir(tmp_path)
    _store, seen = wired
    client = TestClient(api.app)
    _post(client, deck_date="2011")

    assert seen[0].get("company") == "Northwind Robotics"
    assert "Northwind" in (seen[0].get("context") or "")


def test_the_stage_callback_still_reaches_its_own_parameter(wired, tmp_path, monkeypatch):
    """The other half of the same bug: `on_stage` fell back to None, so the
    progress column added in migration 008 was never written in production."""
    monkeypatch.chdir(tmp_path)
    store, _seen = wired
    client = TestClient(api.app)
    response = _post(client, deck_date="2011")
    job_id = response.json()["job_id"]

    assert store.jobs[job_id]["stage"], (
        "no stage was recorded -- on_stage did not reach the pipeline"
    )


# ── The prompt itself, which is where the value actually matters ───────────


def test_the_year_appears_in_the_judging_prompt():
    """End of the chain. A correct `as_of` that never reaches the prompt would
    still leave the verifier judging a 2011 metric against today's evidence."""
    captured = {}

    class FakeClient:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**kwargs):
                    captured["prompt"] = kwargs["messages"][-1]["content"]
                    raise RuntimeError("stop here")

    original = claim_verifier.get_client
    claim_verifier.get_client = lambda: FakeClient()
    try:
        claim_verifier.groq_judge(
            "We have 800 paying users.",
            {"snippets": [{"title": "t", "url": "u", "snippet": "s"}], "full_texts": []},
            as_of="2011",
        )
    except RuntimeError:
        pass
    finally:
        claim_verifier.get_client = original

    prompt = captured["prompt"]
    assert "2011" in prompt
    assert "dated or published around" in prompt
    assert "Judge it as a statement about that time" in prompt


def test_an_unknown_date_still_biases_the_prompt_away_from_present_day():
    """When the year is genuinely unknown the prompt must still stop the
    verifier reading a point-in-time metric as a claim about today -- which is
    how four true historical claims were called lies at 0.96 confidence."""
    captured = {}

    class FakeClient:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**kwargs):
                    captured["prompt"] = kwargs["messages"][-1]["content"]
                    raise RuntimeError("stop here")

    original = claim_verifier.get_client
    claim_verifier.get_client = lambda: FakeClient()
    try:
        claim_verifier.groq_judge(
            "We have 800 paying users.",
            {"snippets": [{"title": "t", "url": "u", "snippet": "s"}], "full_texts": []},
            as_of="",
        )
    except RuntimeError:
        pass
    finally:
        claim_verifier.get_client = original

    prompt = captured["prompt"]
    assert "date of this claim is UNKNOWN" in prompt
    # Measured: with the previous one-line hint, an undated Coinbase claim
    # returned REFUTES at 0.92 against present-day evidence. This wording is
    # what changed that to NOT_ENOUGH_INFO at 0.90.
    assert "growth looks like" in prompt
    assert "MUST answer NOT_ENOUGH_INFO" in prompt
