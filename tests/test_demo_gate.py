"""The demo passphrase gate.

Context, because the distinction matters and is easy to lose: this is a gate,
not authentication. There is no user model and no per-account data isolation --
every report still lives in one shared pool. What it stops is an *anonymous*
caller reading that pool, which the deployed API previously allowed: a plain
curl with no credentials returned every stored report, over sequential integer
ids that make the table trivially enumerable.

The tests below pin the three properties that make it worth anything:
  * unset means open, so a fresh clone and local dev are unaffected;
  * set means every data route refuses an absent or wrong passphrase;
  * the 401 carries CORS headers, or the browser discards it and the frontend
    shows "Network Error" instead of prompting -- the exact failure this
    codebase already shipped once for the 429.
"""
import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TOKEN = "correct-horse-battery-staple"
ORIGIN = "https://venture-flow-livid.vercel.app"

# Routes that must never be reachable without the passphrase, because each one
# returns or creates report data.
GATED_ROUTES = ["/reports", "/database/stats", "/reports/1", "/reports/1/comments"]


def _client(monkeypatch, token: str | None):
    if token is None:
        monkeypatch.delenv("DEMO_ACCESS_TOKEN", raising=False)
    else:
        monkeypatch.setenv("DEMO_ACCESS_TOKEN", token)
    monkeypatch.setenv("ALLOWED_ORIGINS", ORIGIN)
    import api
    importlib.reload(api)
    return api, TestClient(api.app, raise_server_exceptions=False)


def test_unset_token_leaves_the_api_open(monkeypatch):
    """A fresh clone and local development must be unaffected."""
    api, client = _client(monkeypatch, None)
    assert api.DEMO_ACCESS_TOKEN is None
    # Not 401. (May be 503 if Neon is unreachable from the test env, which is
    # fine -- the point is that the gate did not reject it.)
    assert client.get("/reports").status_code != 401


@pytest.mark.parametrize("route", GATED_ROUTES)
def test_gated_routes_refuse_a_missing_passphrase(monkeypatch, route):
    _, client = _client(monkeypatch, TOKEN)
    assert client.get(route).status_code == 401


def test_gated_route_refuses_a_wrong_passphrase(monkeypatch):
    _, client = _client(monkeypatch, TOKEN)
    r = client.get("/reports", headers={"X-Demo-Token": "wrong"})
    assert r.status_code == 401
    assert "passphrase" in r.json()["detail"].lower()


def test_correct_passphrase_is_accepted_in_both_forms(monkeypatch):
    """Bearer is accepted so curl and the eval harnesses stay usable."""
    _, client = _client(monkeypatch, TOKEN)
    for headers in ({"X-Demo-Token": TOKEN}, {"Authorization": f"Bearer {TOKEN}"}):
        assert client.get("/reports", headers=headers).status_code != 401


def test_health_and_root_stay_public(monkeypatch):
    """A platform health check has no passphrase, and neither exposes report
    data. Gating them would make the service look down to Render."""
    _, client = _client(monkeypatch, TOKEN)
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200


def test_upload_is_gated(monkeypatch):
    """Not just reads. An ungated upload lets a stranger spend the owner's
    Groq quota and write rows to their database."""
    _, client = _client(monkeypatch, TOKEN)
    r = client.post("/upload-pdf", files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 401


def test_analyze_is_gated(monkeypatch):
    _, client = _client(monkeypatch, TOKEN)
    r = client.post("/analyze", json={"company_name": "X"})
    assert r.status_code == 401


def test_401_carries_cors_headers(monkeypatch):
    """Otherwise the browser discards the 401 and the frontend reports a bare
    "Network Error" instead of showing the passphrase prompt -- precisely the
    bug this codebase already shipped once, for the rate limiter's 429."""
    _, client = _client(monkeypatch, TOKEN)
    r = client.get("/reports", headers={"Origin": ORIGIN})
    assert r.status_code == 401
    assert r.headers.get("access-control-allow-origin") == ORIGIN


def test_preflight_is_not_gated(monkeypatch):
    """A CORS preflight cannot carry a custom header by definition. Rejecting
    it would surface as a CORS error rather than a 401, hiding the real reason
    from the user."""
    _, client = _client(monkeypatch, TOKEN)
    r = client.options("/analyze", headers={
        "Origin": ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-demo-token",
    })
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == ORIGIN


def test_comparison_is_constant_time(monkeypatch):
    """secrets.compare_digest, not ==, so the check does not leak the
    passphrase a character at a time through timing."""
    import inspect
    api, _ = _client(monkeypatch, TOKEN)
    source = inspect.getsource(api.require_demo_token)
    assert "compare_digest" in source
