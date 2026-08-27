"""The startup configuration gate.

`ALLOWED_ORIGIN_REGEX` and `DEMO_ACCESS_TOKEN` were unset on Render for an
unknown period. The frontend actually in use was CORS-blocked, and
`curl https://.../reports` returned every stored report to any anonymous caller.
Both failures were silent: the server logged healthy 200s for responses browsers
discarded, and an ungated database looks exactly like a working one.

These tests pin the properties that make that impossible to repeat quietly.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config_check import ConfigProblem, ConfigReport, check_configuration, enforce

LOCAL = ["http://localhost:5173", "http://127.0.0.1:5173"]
DEPLOYED = ["https://venture-flow-livid.vercel.app"]


@pytest.fixture
def credentials(monkeypatch):
    """The always-required variables, present, so tests can isolate one concern."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")


# ── What counts as deployed ────────────────────────────────────────────────


def test_localhost_only_is_not_treated_as_deployed(credentials):
    report = check_configuration(
        origins=LOCAL, allowed_origin_regex=None, demo_access_token=None,
    )
    assert report.looks_deployed is False
    assert report.ok, "a local dev clone must not be told it is misconfigured"


def test_a_real_origin_means_deployed_even_without_an_environment_variable(credentials):
    """Inferred rather than declared: a deployment that forgets ENVIRONMENT is
    exactly the deployment that forgets everything else."""
    report = check_configuration(
        origins=DEPLOYED, allowed_origin_regex=None, demo_access_token=None,
    )
    assert report.looks_deployed is True


def test_an_origin_regex_alone_means_deployed(credentials):
    report = check_configuration(
        origins=LOCAL, allowed_origin_regex=r"^https://x\.vercel\.app$",
        demo_access_token="secret",
    )
    assert report.looks_deployed is True


# ── The actual production failure ──────────────────────────────────────────


def test_the_exact_live_misconfiguration_is_flagged_critical(credentials):
    """Reproduces the deployed state: real origin, no token, no regex."""
    report = check_configuration(
        origins=DEPLOYED, allowed_origin_regex=None, demo_access_token=None,
    )
    assert not report.ok
    variables = {p.variable: p for p in report.problems}
    assert variables["DEMO_ACCESS_TOKEN"].severity == "critical"
    assert "OPEN" in variables["DEMO_ACCESS_TOKEN"].consequence.upper()
    assert "ALLOWED_ORIGIN_REGEX" in variables


def test_a_fully_configured_deployment_passes(credentials):
    report = check_configuration(
        origins=DEPLOYED,
        allowed_origin_regex=r"^https://venture-flow-[a-z0-9-]+\.vercel\.app$",
        demo_access_token="a-long-random-passphrase",
    )
    assert report.ok
    assert not report.critical


# ── Always-required credentials ────────────────────────────────────────────


def test_a_missing_groq_key_is_critical_everywhere(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    report = check_configuration(
        origins=LOCAL, allowed_origin_regex=None, demo_access_token=None,
    )
    problem = next(p for p in report.problems if p.variable == "GROQ_API_KEY")
    assert problem.severity == "critical"
    # The consequence must name the confusing symptom, not just "it breaks".
    assert "provider unreachable" in problem.consequence


def test_a_missing_database_url_is_critical(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    report = check_configuration(
        origins=LOCAL, allowed_origin_regex=None, demo_access_token=None,
    )
    assert any(p.variable == "DATABASE_URL" and p.severity == "critical"
               for p in report.problems)


# ── Enforcement behaviour ──────────────────────────────────────────────────


def test_by_default_a_critical_problem_logs_but_does_not_stop_the_boot(monkeypatch, caplog):
    """On a single-instance free tier, refusing to boot turns a security gap
    into a total outage. The default is to run, serve, and shout."""
    monkeypatch.delenv("STRICT_CONFIG", raising=False)
    report = ConfigReport(looks_deployed=True, problems=[
        ConfigProblem("DEMO_ACCESS_TOKEN", "critical", "the API is open"),
    ])
    with caplog.at_level("CRITICAL"):
        enforce(report)          # must not raise
    assert any(r.levelname == "CRITICAL" for r in caplog.records)
    assert any("DEMO_ACCESS_TOKEN" in r.getMessage() for r in caplog.records)


def test_strict_config_refuses_to_start(monkeypatch):
    """Fail-closed is available for anyone who wants it, and named in the log."""
    monkeypatch.setenv("STRICT_CONFIG", "true")
    report = ConfigReport(looks_deployed=True, problems=[
        ConfigProblem("DEMO_ACCESS_TOKEN", "critical", "the API is open"),
    ])
    with pytest.raises(RuntimeError, match="Refusing to start"):
        enforce(report)


def test_warnings_alone_never_block_startup(monkeypatch):
    monkeypatch.setenv("STRICT_CONFIG", "true")
    report = ConfigReport(looks_deployed=True, problems=[
        ConfigProblem("TRUST_PROXY_HEADERS", "warning", "shared rate-limit bucket"),
    ])
    enforce(report)  # must not raise: warnings are not critical
    assert report.ok


def test_a_clean_report_is_silent_about_problems(caplog):
    report = ConfigReport(looks_deployed=False, problems=[])
    with caplog.at_level("INFO"):
        enforce(report)
    assert not any(r.levelname in ("WARNING", "CRITICAL") for r in caplog.records)


# ── The health endpoint surfaces it ────────────────────────────────────────


def test_health_reports_misconfiguration_without_returning_an_error_status(monkeypatch):
    """A CRITICAL log is only seen by someone already reading logs -- which is
    how this went unnoticed. /health is what an uptime check watches.

    It must still return 200: the service is genuinely running, and a 5xx would
    turn a security gap into an outage.
    """
    import importlib

    import api

    monkeypatch.setenv("ALLOWED_ORIGINS", "https://venture-flow-livid.vercel.app")
    monkeypatch.delenv("DEMO_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("ALLOWED_ORIGIN_REGEX", raising=False)
    importlib.reload(api)
    try:
        from fastapi.testclient import TestClient

        response = TestClient(api.app).get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "misconfigured"
        assert body["config"]["status"] == "misconfigured"
        assert any(p["variable"] == "DEMO_ACCESS_TOKEN"
                   for p in body["config"]["problems"])
    finally:
        # Restore module state -- the leak class this suite already got bitten by.
        monkeypatch.undo()
        importlib.reload(api)
