"""The public deployment must fail closed.

Two gaps stood between this backend and a public URL:

  * Reports with no owner were readable by anyone. owner_user_id IS NULL marks
    a report written before accounts existed, or by an anonymous caller, and
    the API treated it as shared. Every one of the 94 stored reports was
    unowned, and report ids are sequential integers.

  * Every analysis route accepted anonymous callers. The UI requires sign-in on
    every page, but the API did not, so anyone with curl could spend the free
    tier's 200,000 tokens a day -- the whole deployment's capacity.

VENTUREFLOW_ENV=production closes both: unowned reports are hidden (not
deleted), and every non-public route requires a valid session. These tests pin
production behaviour, and pin that development -- where the scripts and the
rest of this suite run anonymously -- is unchanged.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import api  # noqa: E402
import db  # noqa: E402

PASSWORD = "a quiet herd of alpacas"
ALLOWED_ORIGIN = "http://localhost:5173"


def _database_available() -> bool:
    try:
        db.count_users()
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not _database_available(),
                                 reason="no database reachable")


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(api, "REQUIRE_SIGNIN", True)
    monkeypatch.setattr(db, "SHARE_UNOWNED_REPORTS", False)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(api.app)


@pytest.fixture
def rows_to_clean():
    emails: list[str] = []
    companies: list[str] = []
    yield emails, companies
    try:
        with db.connection() as conn, conn.cursor() as cur:
            for name in companies:
                cur.execute("DELETE FROM dd_reports WHERE company_id IN "
                            "(SELECT id FROM companies WHERE name = %s)", (name,))
                cur.execute("DELETE FROM companies WHERE name = %s", (name,))
            for email in emails:
                cur.execute("DELETE FROM users WHERE email = %s", (email,))
    except Exception:
        pass


class TestTheSwitchIsDerivedFromOneSetting:
    """Checked in a subprocess, because the flags are read at import and
    reloading `api` inside the suite is the state leak conftest documents."""

    def _flags(self, **env):
        run_env = {**os.environ, **env}
        for key in ("VENTUREFLOW_ENV", "VENTUREFLOW_REQUIRE_SIGNIN",
                    "VENTUREFLOW_SHARE_UNOWNED_REPORTS"):
            if key not in env:
                run_env.pop(key, None)
        out = subprocess.run(
            [sys.executable, "-c",
             "import api, db; print(api.REQUIRE_SIGNIN, db.SHARE_UNOWNED_REPORTS)"],
            cwd=ROOT, env=run_env, capture_output=True, text=True, timeout=180,
        )
        assert out.returncode == 0, out.stderr[-800:]
        return out.stdout.strip().splitlines()[-1]

    def test_production_fails_closed(self):
        assert self._flags(VENTUREFLOW_ENV="production") == "True False"

    def test_development_is_unchanged(self):
        assert self._flags() == "False True"

    def test_each_setting_can_be_overridden(self):
        assert self._flags(VENTUREFLOW_ENV="production",
                           VENTUREFLOW_SHARE_UNOWNED_REPORTS="true",
                           VENTUREFLOW_REQUIRE_SIGNIN="false") == "False True"


class TestAnonymousCallersAreStopped:
    def test_an_anonymous_analysis_is_refused_before_it_is_queued(
        self, production, client, monkeypatch
    ):
        """The quota path: nothing reaches the job queue, let alone Groq."""
        queued = []
        monkeypatch.setattr(api, "create_analysis_job",
                            lambda payload: queued.append(payload) or "job-1")
        response = client.post("/analyze", json={"company_name": "Acme"})

        assert response.status_code == 401
        assert response.json()["code"] == "signin_required"
        assert queued == [], "an anonymous request reached the analysis queue"

    @pytest.mark.parametrize("method,path", [
        ("get", "/reports"), ("get", "/reports/1"), ("get", "/reports/1/pdf"),
        ("get", "/companies/Uber/history"), ("post", "/chat"),
        ("post", "/upload-pdf"), ("get", "/analyze/status/x"),
        ("get", "/database/stats"), ("get", "/observability"),
    ])
    def test_every_data_route_requires_an_account(self, production, client, method, path):
        assert getattr(client, method)(path).status_code == 401

    def test_a_forged_token_is_refused(self, production, client):
        response = client.get("/reports", headers={"Authorization": "Bearer not-real"})
        assert response.status_code == 401

    @pytest.mark.parametrize("path", ["/", "/health", "/auth/me", "/docs", "/openapi.json"])
    def test_the_public_surface_stays_public(self, production, client, path):
        """Health checks, the docs, and the sign-in endpoints themselves -- a
        gate on /auth/* would lock out everyone trying to become a user."""
        assert client.get(path).status_code == 200

    def test_the_401_reaches_the_browser_with_cors(self, production, client):
        """Without CORS headers the browser discards the 401 and the frontend
        sees "Network Error" instead of a reason to show the sign-in page."""
        response = client.get("/reports", headers={"Origin": ALLOWED_ORIGIN})
        assert response.status_code == 401
        assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN

    def test_a_cors_preflight_is_not_refused(self, production, client):
        response = client.options("/analyze", headers={
            "Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        })
        assert response.status_code != 401


@requires_db
class TestSignedInUsersAndOldReports:
    def _account(self, client, rows_to_clean):
        emails, _ = rows_to_clean
        email = f"prod-{uuid.uuid4().hex[:10]}@example.test"
        emails.append(email)
        body = client.post("/auth/register",
                           json={"email": email, "password": PASSWORD}).json()
        return body, {"Authorization": f"Bearer {body['token']}"}

    def _report(self, rows_to_clean, owner_id, score=50):
        _, companies = rows_to_clean
        name = f"ScopeTest {uuid.uuid4().hex[:8]}"
        companies.append(name)
        rid = db.persist_report(
            name=name, description="x", sector=None, domain=None,
            report={"final_score": score, "recommendation": "PASS", "sections": {}},
            owner_user_id=owner_id,
        )
        return name, rid

    def test_a_signed_in_user_gets_through_and_sees_their_own_report(
        self, production, client, rows_to_clean
    ):
        user, headers = self._account(client, rows_to_clean)
        _, rid = self._report(rows_to_clean, user["user"]["id"])

        assert client.get(f"/reports/{rid}", headers=headers).status_code == 200
        listed = client.get("/reports", headers=headers).json()
        assert str(rid) in [row["report_id"] for row in listed]

    def test_an_old_unowned_report_is_hidden_from_everyone(
        self, production, client, rows_to_clean
    ):
        """The 94-report disclosure. Hidden, not deleted: the row survives."""
        user, headers = self._account(client, rows_to_clean)
        name, rid = self._report(rows_to_clean, None, score=61)

        assert client.get(f"/reports/{rid}", headers=headers).status_code == 404
        assert str(rid) not in [r["report_id"] for r in client.get("/reports", headers=headers).json()]
        assert client.get(f"/reports/{rid}/pdf", headers=headers).status_code == 404
        history = client.get(f"/companies/{quote(name)}/history", headers=headers).json()
        assert history["history"] == []

        with db.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM dd_reports WHERE id::text = %s", (str(rid),))
            assert cur.fetchone()["n"] == 1, "hiding must not delete"

    def test_development_still_shares_them(self, client, rows_to_clean):
        """No `production` fixture: the default the scripts rely on."""
        _, rid = self._report(rows_to_clean, None)
        assert client.get(f"/reports/{rid}").status_code == 200
