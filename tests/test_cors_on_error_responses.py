"""Every response must carry CORS headers, including the error ones.

This is a production-only bug class and it cost a real debugging session. Two
response paths in api.py are emitted outside CORSMiddleware -- the rate
limiter's 429 and the catch-all 500, the latter served by Starlette's
ServerErrorMiddleware, which sits outside anything `add_middleware` can wrap.
A browser discards a cross-origin response with no `Access-Control-Allow-Origin`
before JavaScript can read it, so axios reports a bare "Network Error" with no
status and no body.

The consequence is worse than one broken endpoint: *every* backend failure --
an exhausted rate limit, Neon dropping a connection, an unhandled bug --
reached the user as the same uninformative "Network Error", so the frontend
message could never point at the real cause.

None of it reproduces locally, which is why it survived. `vite.config.ts`
proxies /api to the backend, so local requests are same-origin and CORS never
applies at all. These tests set an Origin header explicitly to force the
cross-origin path that only production exercises.
"""
import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ORIGIN = "https://venture-flow-w8hf.vercel.app"


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose app allows ORIGIN, rebuilt so env vars take effect."""
    monkeypatch.setenv("ALLOWED_ORIGINS", ORIGIN)
    import api
    importlib.reload(api)
    # raise_server_exceptions=False so the catch-all 500 handler actually runs
    # instead of the exception propagating into the test.
    return TestClient(api.app, raise_server_exceptions=False)


def test_success_response_has_cors_headers(client):
    r = client.get("/", headers={"Origin": ORIGIN})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == ORIGIN


def test_404_has_cors_headers(client):
    r = client.get("/no-such-route", headers={"Origin": ORIGIN})
    assert r.status_code == 404
    assert r.headers.get("access-control-allow-origin") == ORIGIN


def test_rate_limited_429_has_cors_headers(client, monkeypatch):
    """The regression that was live in production.

    Without CORS headers on this response the browser drops it, and a user who
    simply ran an analysis -- whose status polling alone issues 20 requests a
    minute -- saw "Network Error" instead of "Too many requests".
    """
    import api
    monkeypatch.setattr(api, "rate_limit_is_allowed", lambda *_a, **_k: False)

    r = client.get("/reports", headers={"Origin": ORIGIN})
    assert r.status_code == 429
    assert r.headers.get("access-control-allow-origin") == ORIGIN, (
        "the 429 reached the browser with no ACAO header, so it was discarded "
        "and surfaced as a generic Network Error"
    )
    assert "Too many requests" in r.json()["detail"]


def test_unhandled_500_has_cors_headers(client, monkeypatch):
    """An unhandled backend error must still be readable by the frontend.

    Otherwise a transient Neon failure mid-request is indistinguishable, from
    the browser, from the backend being entirely down.
    """
    import api

    def _boom(*_a, **_k):
        raise RuntimeError("simulated unhandled failure, e.g. Neon unreachable")

    monkeypatch.setattr(api, "list_reports", _boom)
    monkeypatch.setattr(api, "rate_limit_is_allowed", lambda *_a, **_k: True)

    r = client.get("/reports", headers={"Origin": ORIGIN})
    assert r.status_code in (500, 503)
    assert r.headers.get("access-control-allow-origin") == ORIGIN, (
        "the error response carried no ACAO header, so the browser discarded "
        "it and the frontend could only report a generic Network Error"
    )


def test_disallowed_origin_is_still_refused_on_error_paths(client, monkeypatch):
    """Widening error paths must not turn into reflecting any origin back."""
    import api
    monkeypatch.setattr(api, "rate_limit_is_allowed", lambda *_a, **_k: False)

    r = client.get("/reports", headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 429
    assert "access-control-allow-origin" not in r.headers


def test_client_key_prefers_forwarded_header_only_when_trusted(monkeypatch):
    """Behind Render's load balancer request.client.host is the proxy, so
    without this every visitor shares one rate-limit bucket."""
    import api
    from starlette.datastructures import Headers

    class _Req:
        def __init__(self, headers, host):
            self.headers = Headers(headers)
            self.client = type("C", (), {"host": host})()

    request = _Req({"x-forwarded-for": "203.0.113.9, 10.0.0.1"}, "10.0.0.1")

    monkeypatch.setattr(api, "TRUST_PROXY_HEADERS", True)
    assert api._client_key(request) == "203.0.113.9"

    # Untrusted: the spoofable header must be ignored entirely.
    monkeypatch.setattr(api, "TRUST_PROXY_HEADERS", False)
    assert api._client_key(request) == "10.0.0.1"


def test_origin_regex_allows_a_matching_vercel_deployment(monkeypatch):
    """Vercel mints a new hostname per deployment.

    This app has had two live frontends at once --
    venture-flow-w8hf.vercel.app and venture-flow-livid.vercel.app -- and only
    the first was in ALLOWED_ORIGINS. Every request from the second failed
    CORS, which the browser reported as "Network Error" while the server
    logged a healthy 200 for a response the browser then discarded.
    """
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://venture-flow-w8hf.vercel.app")
    monkeypatch.setenv("ALLOWED_ORIGIN_REGEX", r"^https://venture-flow-[a-z0-9-]+\.vercel\.app$")
    import api
    importlib.reload(api)
    c = TestClient(api.app, raise_server_exceptions=False)

    other = "https://venture-flow-livid.vercel.app"
    r = c.get("/", headers={"Origin": other})
    assert r.headers.get("access-control-allow-origin") == other

    # And on the error paths that bypass CORSMiddleware.
    monkeypatch.setattr(api, "rate_limit_is_allowed", lambda *_a, **_k: False)
    r = c.get("/reports", headers={"Origin": other})
    assert r.status_code == 429
    assert r.headers.get("access-control-allow-origin") == other


def test_origin_regex_is_anchored_and_refuses_lookalikes(monkeypatch):
    """An unanchored pattern would let evil-venture-flow-x.vercel.app.attacker.com
    through. The API has no auth, so CORS is the only gate on someone else's
    page spending the owner's Groq quota."""
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://venture-flow-w8hf.vercel.app")
    monkeypatch.setenv("ALLOWED_ORIGIN_REGEX", r"^https://venture-flow-[a-z0-9-]+\.vercel\.app$")
    import api
    importlib.reload(api)
    c = TestClient(api.app, raise_server_exceptions=False)

    for bad in ("https://venture-flow-x.vercel.app.attacker.com",
                "https://evil.com",
                "http://venture-flow-x.vercel.app"):
        r = c.get("/", headers={"Origin": bad})
        assert r.headers.get("access-control-allow-origin") is None, bad
