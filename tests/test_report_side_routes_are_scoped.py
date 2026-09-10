"""Every route that touches a report must apply the report's own access rule.

WHAT WAS WRONG

`GET /reports/{id}` has always enforced ownership: a report is reachable when it
is unowned (shared, written before accounts existed) or when it belongs to the
caller. Four routes that touch the same reports performed no check at all:

  GET  /companies/{name}/history   returned the score and verdict history of
                                   every user's private analyses of a company
  GET  /reports/{id}/comments      returned comments on private reports
  POST /reports/{id}/comments      wrote comments onto other users' reports
  POST /reports/{id}/decision      recorded invest/pass on other users' reports

The export routes had the mirror-image defect (they hid a user's own report from
them); these four failed in the dangerous direction, exposing private reports to
everyone. The last one was also a data-poisoning path: `investment_decisions` is
the training signal for ml/personalization.py.

All four now go through one helper, `_require_readable_report`, so they cannot
drift apart again. Denials are 404, never 403, because a 403 confirms the id is
real and report ids are sequential integers.

The frontend already treats a non-OK response from both fetches as "nothing
here" (comments -> [], history -> {history: []}), so a 404 cannot break the
report or dashboard page -- it only ever appears in the case it exists to stop.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PASSWORD = "a quiet herd of alpacas"


def _database_available() -> bool:
    try:
        from db import count_users
        count_users()
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(),
    reason="no database reachable; set DATABASE_URL to run the scoping tests",
)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    import api

    return TestClient(api.app)


@pytest.fixture
def rows_to_clean():
    """These tests write to the real database, so everything they create is
    removed afterwards. Deleting a report cascades to its comments and its
    decision (both ON DELETE CASCADE)."""
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


def _account(client, rows_to_clean, label):
    emails, _ = rows_to_clean
    email = f"{label}-{uuid.uuid4().hex[:10]}@example.test"
    emails.append(email)
    response = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    body = response.json()
    return body, {"Authorization": f"Bearer {body['token']}"}


def _report(rows_to_clean, owner_id, score=50):
    """Persist a report and confirm the stored owner, so a NULL owner (which is
    public by design) cannot masquerade as an authorization failure."""
    from db import connection, persist_report

    _, companies = rows_to_clean
    name = f"ScopeTest {uuid.uuid4().hex[:8]}"
    companies.append(name)
    report_id = persist_report(
        name=name, description="A private analysis.", sector=None, domain=None,
        report={"final_score": score, "recommendation": "PASS", "sections": {}},
        owner_user_id=owner_id,
    )
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT owner_user_id::text AS owner FROM dd_reports WHERE id::text = %s",
                    (str(report_id),))
        assert cur.fetchone()["owner"] == owner_id
    return name, report_id


def _count(table, report_id):
    from db import connection
    with connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) AS n FROM {table} WHERE report_id::text = %s",
                    (str(report_id),))
        return int(cur.fetchone()["n"])


@requires_db
class TestTheOwnerKeepsFullAccess:
    """The regression direction. An over-eager check that locked owners out of
    their own comments would be the export bug all over again."""

    def test_the_owner_can_comment_and_read_comments(self, client, rows_to_clean):
        owner, headers = _account(client, rows_to_clean, "owner")
        _, report_id = _report(rows_to_clean, owner["user"]["id"])

        posted = client.post(f"/reports/{report_id}/comments", headers=headers,
                             json={"author_name": "Me", "body": "Follow up on churn."})
        assert posted.status_code == 200, posted.text

        listed = client.get(f"/reports/{report_id}/comments", headers=headers)
        assert listed.status_code == 200
        assert [c["body"] for c in listed.json()] == ["Follow up on churn."]

    def test_the_owner_can_record_a_decision(self, client, rows_to_clean):
        owner, headers = _account(client, rows_to_clean, "owner")
        _, report_id = _report(rows_to_clean, owner["user"]["id"])

        response = client.post(f"/reports/{report_id}/decision", headers=headers,
                               json={"decision": "invest", "notes": ""})
        assert response.status_code == 200, response.text
        assert _count("investment_decisions", report_id) == 1

    def test_the_owner_sees_their_private_report_in_history(self, client, rows_to_clean):
        owner, headers = _account(client, rows_to_clean, "owner")
        name, _ = _report(rows_to_clean, owner["user"]["id"], score=77)

        response = client.get(f"/companies/{quote(name)}/history", headers=headers)
        assert response.status_code == 200
        assert [row["score"] for row in response.json()["history"]] == [77.0]


@requires_db
class TestAStrangerIsShutOut:
    def test_a_stranger_cannot_read_comments(self, client, rows_to_clean):
        owner, owner_headers = _account(client, rows_to_clean, "owner")
        _, report_id = _report(rows_to_clean, owner["user"]["id"])
        client.post(f"/reports/{report_id}/comments", headers=owner_headers,
                    json={"author_name": "Me", "body": "Confidential: term sheet at $40M."})

        _, stranger = _account(client, rows_to_clean, "stranger")
        response = client.get(f"/reports/{report_id}/comments", headers=stranger)

        assert response.status_code == 404, (
            "another user read the comments on a private report"
        )
        assert "term sheet" not in response.text

    def test_a_stranger_cannot_comment(self, client, rows_to_clean):
        owner, _ = _account(client, rows_to_clean, "owner")
        _, report_id = _report(rows_to_clean, owner["user"]["id"])
        _, stranger = _account(client, rows_to_clean, "stranger")

        response = client.post(f"/reports/{report_id}/comments", headers=stranger,
                               json={"author_name": "x", "body": "injected"})

        assert response.status_code == 404
        assert _count("report_comments", report_id) == 0, (
            "the request was refused but the comment was written anyway"
        )

    def test_a_stranger_cannot_record_a_decision(self, client, rows_to_clean):
        """This one is training data. An unchecked write here let any caller
        steer what the personalization model learns."""
        owner, _ = _account(client, rows_to_clean, "owner")
        _, report_id = _report(rows_to_clean, owner["user"]["id"])
        _, stranger = _account(client, rows_to_clean, "stranger")

        response = client.post(f"/reports/{report_id}/decision", headers=stranger,
                               json={"decision": "pass", "notes": ""})

        assert response.status_code == 404
        assert _count("investment_decisions", report_id) == 0

    def test_a_stranger_cannot_see_private_scores_in_history(self, client, rows_to_clean):
        owner, _ = _account(client, rows_to_clean, "owner")
        name, _ = _report(rows_to_clean, owner["user"]["id"], score=77)
        _, stranger = _account(client, rows_to_clean, "stranger")

        response = client.get(f"/companies/{quote(name)}/history", headers=stranger)

        assert response.status_code == 200
        assert response.json()["history"] == [], (
            "the score history of another user's private analysis was returned"
        )

    @pytest.mark.parametrize("method,path_tail,payload", [
        ("get", "comments", None),
        ("post", "comments", {"author_name": "x", "body": "y"}),
        ("post", "decision", {"decision": "invest", "notes": ""}),
    ])
    def test_an_anonymous_caller_is_shut_out(
        self, client, rows_to_clean, method, path_tail, payload
    ):
        owner, _ = _account(client, rows_to_clean, "owner")
        _, report_id = _report(rows_to_clean, owner["user"]["id"])

        call = getattr(client, method)
        kwargs = {"json": payload} if payload is not None else {}
        assert call(f"/reports/{report_id}/{path_tail}", **kwargs).status_code == 404

    def test_a_nonexistent_report_is_indistinguishable_from_a_private_one(
        self, client, rows_to_clean
    ):
        """Both must be 404. If one were 403 the difference would confirm which
        sequential ids are real."""
        owner, _ = _account(client, rows_to_clean, "owner")
        _, report_id = _report(rows_to_clean, owner["user"]["id"])
        _, stranger = _account(client, rows_to_clean, "stranger")

        private = client.get(f"/reports/{report_id}/comments", headers=stranger)
        missing = client.get("/reports/999999999/comments", headers=stranger)
        assert private.status_code == missing.status_code == 404


@requires_db
class TestSharedReportsStayShared:
    """Reports written before accounts existed have no owner and remain readable
    by everyone -- that behaviour must not regress while closing the rest."""

    def test_anyone_can_comment_on_an_unowned_report(self, client, rows_to_clean):
        _, report_id = _report(rows_to_clean, None)

        posted = client.post(f"/reports/{report_id}/comments",
                             json={"author_name": "Anon", "body": "Looks early."})
        assert posted.status_code == 200, posted.text
        assert client.get(f"/reports/{report_id}/comments").status_code == 200

    def test_an_unowned_report_appears_in_everyones_history(self, client, rows_to_clean):
        name, _ = _report(rows_to_clean, None, score=61)
        response = client.get(f"/companies/{quote(name)}/history")
        assert [row["score"] for row in response.json()["history"]] == [61.0]
