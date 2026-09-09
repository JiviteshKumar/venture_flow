"""Every download button on a report must work for the person who owns it.

WHAT WENT WRONG

`GET /reports/{id}` scopes the lookup to the caller:

    get_report(report_id, str(user["id"]) if user else None)

`GET /reports/{id}/pdf` and `GET /reports/{id}/export/{fmt}` did not. They
called `get_report(report_id)` with no user at all.

The bug that produces is the reverse of the obvious one. `get_report` returns a
row only when it is unowned OR owned by the id it is given, so passing nothing
never leaked a private report -- it hid every private report from the person it
belongs to. A signed-in user could open their own analysis (200) and got 404
from Download PDF, Export Word and Export Markdown, on their own report.

Found by smoke-testing the endpoints the deck audit does not touch. Both
directions are pinned below, because the natural fix for the 404 -- dropping
the scoping from GET /reports/{id} too -- would turn a broken button into an
enumeration hole over sequential integer report ids.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def _database_available() -> bool:
    """Probe the database rather than reading DATABASE_URL from the process
    environment: it lives in .env, which `db` loads on import, so checking
    os.environ at collection time skips every test in this file."""
    try:
        from db import count_users
        count_users()
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(),
    reason="no database reachable; set DATABASE_URL to run the export scoping tests",
)

PASSWORD = "a quiet herd of alpacas"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    import api

    return TestClient(api.app)


@pytest.fixture
def rows_to_clean():
    """These tests write to the real database (there is no fixture one), so
    every row they create is registered here and removed afterwards."""
    emails: list[str] = []
    companies: list[str] = []
    yield emails, companies
    try:
        from db import connection
        with connection() as conn, conn.cursor() as cur:
            for name in companies:
                cur.execute(
                    "DELETE FROM dd_reports WHERE company_id IN "
                    "(SELECT id FROM companies WHERE name = %s)", (name,))
                cur.execute("DELETE FROM companies WHERE name = %s", (name,))
            for email in emails:
                cur.execute("DELETE FROM users WHERE email = %s", (email,))
    except Exception:
        pass


def _owned_report(client, rows_to_clean, prefix="ScopeTest"):
    """Create an account and a report that account owns.

    Every step is checked, because the failure mode this guards against is
    silent. An unowned report is readable by ANYONE by design -- that is what
    `dd_reports.owner_user_id IS NULL` means for reports written before accounts
    existed. So if registration quietly fails, or `persist_report` stores a NULL
    owner, the report becomes public and a scoping test fails while nothing
    about the authorization logic is wrong.

    Written after `test_a_stranger_cannot_download_someone_elses_report`
    [export/md] failed once in a full suite run and could not be reproduced --
    40 isolated runs of the identical scenario all returned 404. Rather than
    guess, the setup now proves its own preconditions, so a recurrence says
    which of the two very different things went wrong.
    """
    from db import connection, persist_report

    emails, companies = rows_to_clean
    email = f"export-{uuid.uuid4().hex[:10]}@example.test"
    emails.append(email)

    response = client.post("/auth/register",
                           json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, (
        f"could not create the owner account ({response.status_code}: "
        f"{response.text[:200]}). Without an owner the report is unowned, and "
        f"an unowned report is public by design -- so a scoping assertion "
        f"downstream would fail for a reason that has nothing to do with "
        f"authorization."
    )
    account = response.json()
    owner_id = (account.get("user") or {}).get("id")
    assert owner_id, f"registration returned no user id: {account}"

    name = f"{prefix} {uuid.uuid4().hex[:8]}"
    companies.append(name)
    report_id = persist_report(
        name=name, description="An owned analysis.", sector=None, domain=None,
        report={"final_score": 50, "recommendation": "PASS", "sections": {}},
        owner_user_id=owner_id,
    )

    # What the database actually stored, not what we asked it to store.
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT owner_user_id::text AS owner FROM dd_reports WHERE id::text = %s",
            (str(report_id),))
        row = cur.fetchone()
    assert row is not None, f"report {report_id} was not persisted"
    assert row["owner"] == owner_id, (
        f"the report was stored with owner {row['owner']!r}, not {owner_id!r}. "
        f"A NULL owner here makes the report public by design, which would "
        f"look exactly like an authorization failure in the tests below."
    )

    return account, report_id


@requires_db
class TestTheOwnerCanDownloadTheirOwnReport:
    @pytest.mark.parametrize("path", ["pdf", "export/pdf", "export/md", "export/docx"])
    def test_every_download_route_works_for_the_owner(
        self, client, rows_to_clean, path
    ):
        account, report_id = _owned_report(client, rows_to_clean)
        headers = {"Authorization": f"Bearer {account['token']}"}

        readable = client.get(f"/reports/{report_id}", headers=headers)
        assert readable.status_code == 200, "precondition: the owner can read it"

        response = client.get(f"/reports/{report_id}/{path}", headers=headers)
        assert response.status_code == 200, (
            f"the owner got {response.status_code} from /{path} on their own "
            f"report; every download button on the report page was dead"
        )
        assert response.content, "an empty document is not a working download"


@requires_db
class TestScopingIsNotSimplyRemoved:
    """The cheap fix for the 404 above is to stop scoping the lookup. Report
    ids are sequential integers, so that trades a broken button for an
    enumeration hole."""

    @pytest.mark.parametrize("path", ["pdf", "export/md"])
    def test_a_stranger_cannot_download_someone_elses_report(
        self, client, rows_to_clean, path
    ):
        _, report_id = _owned_report(client, rows_to_clean)

        emails, _ = rows_to_clean
        other_email = f"stranger-{uuid.uuid4().hex[:10]}@example.test"
        emails.append(other_email)
        stranger = client.post(
            "/auth/register",
            json={"email": other_email, "password": PASSWORD},
        ).json()

        response = client.get(
            f"/reports/{report_id}/{path}",
            headers={"Authorization": f"Bearer {stranger['token']}"},
        )
        assert response.status_code == 404, (
            "another user downloaded this report. 404 rather than 403 on "
            "purpose: a 403 confirms the id is real."
        )

    @pytest.mark.parametrize("path", ["pdf", "export/md"])
    def test_an_anonymous_caller_cannot_download_it(
        self, client, rows_to_clean, path
    ):
        _, report_id = _owned_report(client, rows_to_clean)
        assert client.get(f"/reports/{report_id}/{path}").status_code == 404


@requires_db
class TestUnownedReportsStayDownloadable:
    def test_a_pre_authentication_report_can_still_be_exported(
        self, client, rows_to_clean
    ):
        """Reports written before accounts existed have no owner and stay
        readable by anyone; their downloads must not regress either."""
        from db import persist_report

        _, companies = rows_to_clean
        name = f"Legacy {uuid.uuid4().hex[:8]}"
        companies.append(name)
        report_id = persist_report(
            name=name, description="Pre-authentication.", sector=None,
            domain=None,
            report={"final_score": 50, "recommendation": "PASS", "sections": {}},
            owner_user_id=None,
        )

        assert client.get(f"/reports/{report_id}/pdf").status_code == 200


@requires_db
def test_an_unsupported_format_is_refused_clearly(client, rows_to_clean):
    """Not every 400 here is a bug -- json/csv/html are genuinely not offered,
    and the message should say what is."""
    account, report_id = _owned_report(client, rows_to_clean)
    response = client.get(
        f"/reports/{report_id}/export/csv",
        headers={"Authorization": f"Bearer {account['token']}"},
    )
    assert response.status_code == 400
    assert "Supported" in response.json()["detail"]
