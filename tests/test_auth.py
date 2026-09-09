"""Email/password accounts, and the report scoping they exist to enable.

WHAT THIS GUARDS

Before accounts, `GET /reports` returned every stored report -- company names,
scores, the full investment memo -- to any caller holding a shared passphrase,
over sequential integer ids that made the whole table enumerable. For a product
whose premise is confidential diligence on other people's companies, that was
the most severe defect in the system.

The tests below are split accordingly: the ones under `TestPasswordHashing` and
`TestValidation` need no database, and the endpoint tests skip when Postgres is
not reachable rather than failing, because a missing local database is not a
code regression.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

import api
import auth


# ── Pure functions: no database, always run ────────────────────────────────


class TestPasswordHashing:
    def test_a_hash_is_not_the_password(self):
        encoded = auth.hash_password("correct horse battery staple")
        assert "correct horse" not in encoded
        assert encoded.startswith("scrypt$")

    def test_the_right_password_verifies(self):
        encoded = auth.hash_password("correct horse battery staple")
        assert auth.verify_password("correct horse battery staple", encoded) is True

    def test_the_wrong_password_does_not(self):
        encoded = auth.hash_password("correct horse battery staple")
        assert auth.verify_password("correct horse battery stapl", encoded) is False

    def test_the_same_password_hashes_differently_every_time(self):
        """A per-hash salt. Without it, identical passwords produce identical
        hashes and one cracked hash cracks every account that shares it."""
        a = auth.hash_password("correct horse battery staple")
        b = auth.hash_password("correct horse battery staple")
        assert a != b
        assert auth.verify_password("correct horse battery staple", a)
        assert auth.verify_password("correct horse battery staple", b)

    def test_the_cost_parameters_travel_with_the_hash(self):
        """So the cost can be raised later without invalidating what is stored.
        A hash that does not carry its parameters can never be upgraded."""
        encoded = auth.hash_password("correct horse battery staple")
        scheme, n, r, p, _salt, _hash = encoded.split("$")
        assert scheme == "scrypt"
        assert int(n) >= 2 ** 14 and int(r) >= 8 and int(p) >= 1

    def test_a_hash_made_with_weaker_parameters_still_verifies(self):
        """The upgrade path, exercised rather than assumed."""
        import base64
        import hashlib
        import secrets as _secrets

        salt = _secrets.token_bytes(16)
        derived = hashlib.scrypt(b"legacy password here", salt=salt,
                                 n=2 ** 12, r=8, p=1, dklen=32)
        legacy = "$".join(["scrypt", "4096", "8", "1",
                           base64.b64encode(salt).decode(),
                           base64.b64encode(derived).decode()])
        assert auth.verify_password("legacy password here", legacy) is True

    def test_a_corrupt_hash_is_a_failed_login_not_a_crash(self):
        for broken in ("", "not-a-hash", "scrypt$x$y$z$q$w", "bcrypt$1$2$3$4"):
            assert auth.verify_password("anything", broken) is False


class TestValidation:
    @pytest.mark.parametrize("email", [
        "ada@example.com", "ada+vc@example.co.uk", "a.b-c@sub.example.io",
    ])
    def test_real_addresses_are_accepted(self, email):
        assert auth.validate_email(email) == email.lower()

    @pytest.mark.parametrize("email", ["", "ada", "ada@", "@example.com", "a b@c.com"])
    def test_obvious_non_addresses_are_rejected(self, email):
        with pytest.raises(auth.AuthError):
            auth.validate_email(email)

    def test_email_is_normalised_so_case_cannot_make_two_accounts(self):
        assert auth.validate_email("  Ada@Example.COM ") == "ada@example.com"

    def test_short_passwords_are_rejected_with_a_reason(self):
        with pytest.raises(auth.AuthError) as excinfo:
            auth.validate_password("short")
        assert str(auth.MIN_PASSWORD_LENGTH) in str(excinfo.value)

    def test_an_obvious_password_of_legal_length_is_still_rejected(self):
        with pytest.raises(auth.AuthError):
            auth.validate_password("password123")

    def test_a_long_ordinary_passphrase_is_accepted(self):
        """No composition rules, deliberately: forcing symbols pushes people to
        'Password1!' and NIST dropped the requirement for that reason."""
        assert auth.validate_password("two horses walked into a barn")

    def test_an_enormous_password_is_refused(self):
        """Unbounded input to a memory-hard KDF is a denial-of-service vector."""
        with pytest.raises(auth.AuthError):
            auth.validate_password("x" * 5000)


class TestSessionTokens:
    def test_only_the_hash_would_ever_be_stored(self):
        token, token_hash, _expires = auth.new_session_token()
        assert token != token_hash
        assert auth.hash_token(token) == token_hash
        assert len(token) >= 32

    def test_tokens_are_unique(self):
        assert len({auth.new_session_token()[0] for _ in range(50)}) == 50

    def test_public_user_cannot_leak_a_password_hash(self):
        """The only user shape that reaches a response is built here, so no
        endpoint can expose the hash by forgetting to strip it."""
        row = {
            "id": uuid.uuid4(), "email": "ada@example.com",
            "display_name": "Ada", "created_at": None,
            "password_hash": "scrypt$SECRET",
        }
        public = auth.public_user(row)
        assert "password_hash" not in public
        assert "SECRET" not in str(public)


# ── Endpoints: need a database ─────────────────────────────────────────────


def _database_available() -> bool:
    try:
        from db import count_users
        count_users()
        return True
    except Exception:
        return False


pytestmark_db = pytest.mark.skipif(
    not _database_available(),
    reason="no database reachable; set DATABASE_URL to run the account tests",
)


@pytest.fixture
def client():
    return TestClient(api.app)


# Every account these tests create is registered here and deleted afterwards.
#
# This is not tidiness. `DATABASE_URL` points at the real Neon database -- these
# tests have no fixture database of their own -- so without cleanup every run
# leaves permanent accounts behind. One run of this file did exactly that:
# 22 of the 23 rows in `users` were @example.test artifacts, sitting in
# production alongside the one real account.
#
# Deleting the user cascades to its sessions (user_sessions.user_id ON DELETE
# CASCADE) and nulls the owner on any report it made (dd_reports.owner_user_id
# ON DELETE SET NULL), so the reports survive as unowned rows rather than
# vanishing.
@pytest.fixture
def created_emails():
    emails: list[str] = []
    yield emails
    try:
        from db import connection
        with connection() as conn, conn.cursor() as cur:
            for email in emails:
                cur.execute("DELETE FROM users WHERE email = %s", (email,))
    except Exception:
        # Cleanup failing must not turn a passing test red; the assertion
        # already ran. It does leave a row behind, which the query in
        # `test_no_test_accounts_are_left_behind` will notice.
        pass


# The same problem one table over.
#
# Deleting a test user leaves its reports behind by design (dd_reports
# .owner_user_id is ON DELETE SET NULL, so the row survives unowned). Nothing
# then removed the report, or the `companies` row created alongside it.
#
# That is worse than clutter, because `db.find_similar_companies` selects from
# any company that has a report attached. Every `ScopeTest <hex>` fixture was
# therefore a live candidate to appear in a real user's report as a similar
# company -- which is exactly how "02 uber" came to be listed as a comparable
# for Uber.
#
# Order matters: dd_reports.company_id is ON DELETE NO ACTION, so the reports
# have to go first. investment_decisions and report_comments cascade from the
# report; analysed_companies nulls its reference.
@pytest.fixture
def created_companies():
    names: list[str] = []
    yield names
    try:
        from db import connection
        with connection() as conn, conn.cursor() as cur:
            for name in names:
                cur.execute(
                    "DELETE FROM dd_reports WHERE company_id IN "
                    "(SELECT id FROM companies WHERE name = %s)",
                    (name,),
                )
                cur.execute("DELETE FROM companies WHERE name = %s", (name,))
    except Exception:
        # As with created_emails: a failed cleanup must not fail a passing
        # test. The guard test below reports anything left behind.
        pass


def _track_company(created_companies, name):
    created_companies.append(name)
    return name


@pytest.fixture
def fresh_email(created_emails):
    email = f"test-{uuid.uuid4().hex[:12]}@example.test"
    created_emails.append(email)
    return email


PASSWORD = "a quiet herd of alpacas"


def _track(emails: list[str], email: str) -> str:
    """Register an address for deletion, and return it. Used inline so a test
    cannot create an account it forgot to clean up."""
    emails.append(email)
    return email


@pytestmark_db
class TestRegistrationAndLogin:
    def test_register_then_use_the_token(self, client, fresh_email):
        response = client.post("/auth/register", json={
            "email": fresh_email, "password": PASSWORD, "display_name": "Ada",
        })
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["token"]
        assert body["user"]["email"] == fresh_email
        assert "password" not in response.text.lower() or "password_hash" not in response.text

        me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
        assert me.status_code == 200
        assert me.json()["user"]["email"] == fresh_email

    def test_the_same_email_cannot_register_twice(self, client, fresh_email):
        first = client.post("/auth/register",
                            json={"email": fresh_email, "password": PASSWORD})
        assert first.status_code == 201
        again = client.post("/auth/register",
                            json={"email": fresh_email.upper(), "password": PASSWORD})
        assert again.status_code == 409, (
            "case alone must not create a second account for the same address"
        )

    def test_login_with_the_right_password(self, client, fresh_email):
        client.post("/auth/register", json={"email": fresh_email, "password": PASSWORD})
        response = client.post("/auth/login",
                               json={"email": fresh_email, "password": PASSWORD})
        assert response.status_code == 200
        assert response.json()["token"]

    def test_login_with_the_wrong_password_fails(self, client, fresh_email):
        client.post("/auth/register", json={"email": fresh_email, "password": PASSWORD})
        response = client.post("/auth/login",
                               json={"email": fresh_email, "password": PASSWORD + "!"})
        assert response.status_code == 401

    def test_an_unknown_email_gives_the_same_answer_as_a_wrong_password(self, client):
        """Identical status and wording, so a login response cannot be used to
        enumerate which addresses have accounts."""
        unknown = client.post("/auth/login", json={
            "email": f"nobody-{uuid.uuid4().hex}@example.test", "password": PASSWORD,
        })
        assert unknown.status_code == 401
        assert unknown.json()["detail"] == "Wrong email or password."

    def test_a_weak_password_is_refused_at_registration(self, client, fresh_email):
        response = client.post("/auth/register",
                               json={"email": fresh_email, "password": "short"})
        assert response.status_code == 400

    def test_logout_invalidates_the_token(self, client, fresh_email):
        token = client.post("/auth/register", json={
            "email": fresh_email, "password": PASSWORD,
        }).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        assert client.get("/auth/me", headers=headers).json()["user"] is not None
        assert client.post("/auth/logout", headers=headers).status_code == 204
        assert client.get("/auth/me", headers=headers).json()["user"] is None

    def test_logging_out_twice_is_not_an_error(self, client, fresh_email):
        token = client.post("/auth/register", json={
            "email": fresh_email, "password": PASSWORD,
        }).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.post("/auth/logout", headers=headers).status_code == 204
        assert client.post("/auth/logout", headers=headers).status_code == 204

    def test_a_made_up_token_is_simply_not_signed_in(self, client):
        me = client.get("/auth/me",
                        headers={"Authorization": "Bearer not-a-real-token"})
        assert me.status_code == 200
        assert me.json()["user"] is None

    def test_the_unverified_email_caveat_is_stated_not_implied(self, client):
        """This deployment has no email provider, so addresses are not verified
        and there is no password reset. Saying so is the honest thing; implying
        a verified address would not be."""
        body = client.get("/auth/me").json()
        assert "not verified" in body["email_verification_note"].lower()


@pytestmark_db
class TestReportScoping:
    """The defect accounts exist to close."""

    def test_a_users_report_is_invisible_to_another_user(
        self, client, created_emails, created_companies
    ):
        from db import persist_report

        owner = client.post("/auth/register", json={
            "email": _track(created_emails, f"owner-{uuid.uuid4().hex[:10]}@example.test"),
            "password": PASSWORD,
        }).json()
        stranger = client.post("/auth/register", json={
            "email": _track(created_emails, f"other-{uuid.uuid4().hex[:10]}@example.test"),
            "password": PASSWORD,
        }).json()

        report_id = persist_report(
            name=_track_company(created_companies, f"ScopeTest {uuid.uuid4().hex[:8]}"),
            description="A private analysis.", sector=None, domain=None,
            report={"final_score": 50, "recommendation": "PASS", "sections": {}},
            owner_user_id=owner["user"]["id"],
        )

        mine = client.get(f"/reports/{report_id}",
                          headers={"Authorization": f"Bearer {owner['token']}"})
        assert mine.status_code == 200, "the owner must be able to read their own report"

        theirs = client.get(f"/reports/{report_id}",
                            headers={"Authorization": f"Bearer {stranger['token']}"})
        assert theirs.status_code == 404, (
            "another user could read this report. 404 rather than 403 on purpose: "
            "a 403 confirms the id is real, which is the enumeration this closes."
        )

        anonymous = client.get(f"/reports/{report_id}")
        assert anonymous.status_code == 404

    def test_the_list_does_not_include_another_users_reports(
        self, client, created_emails, created_companies
    ):
        from db import persist_report

        owner = client.post("/auth/register", json={
            "email": _track(created_emails, f"owner2-{uuid.uuid4().hex[:10]}@example.test"),
            "password": PASSWORD,
        }).json()
        stranger = client.post("/auth/register", json={
            "email": _track(created_emails, f"other2-{uuid.uuid4().hex[:10]}@example.test"),
            "password": PASSWORD,
        }).json()

        name = _track_company(
            created_companies, f"ListScope {uuid.uuid4().hex[:8]}")
        persist_report(
            name=name, description="Private.", sector=None, domain=None,
            report={"final_score": 50, "recommendation": "PASS", "sections": {}},
            owner_user_id=owner["user"]["id"],
        )

        listed = client.get("/reports",
                            headers={"Authorization": f"Bearer {stranger['token']}"})
        assert listed.status_code == 200
        assert name not in [row["company"] for row in listed.json()]

    def test_an_unowned_report_stays_visible_and_is_flagged_as_shared(
        self, client, created_emails, created_companies
    ):
        """Reports written before accounts existed have no owner. They are not
        retro-assigned to whoever registers first -- inventing an owner is worse
        than admitting there is none -- so they stay visible and say why."""
        from db import persist_report

        user = client.post("/auth/register", json={
            "email": _track(created_emails, f"legacy-{uuid.uuid4().hex[:10]}@example.test"),
            "password": PASSWORD,
        }).json()
        name = _track_company(
            created_companies, f"Legacy {uuid.uuid4().hex[:8]}")
        persist_report(
            name=name, description="Pre-authentication.", sector=None, domain=None,
            report={"final_score": 50, "recommendation": "PASS", "sections": {}},
            owner_user_id=None,
        )

        listed = client.get(
            "/reports", headers={"Authorization": f"Bearer {user['token']}"}
        ).json()
        row = next((r for r in listed if r["company"] == name), None)
        assert row is not None, "an unowned report must remain readable"
        assert row["shared"] is True


@pytestmark_db
def test_no_test_accounts_are_left_behind():
    """The guard on the cleanup above.

    These tests run against the real database, so a leaked account is a real
    row in production. This asserts a ceiling rather than zero: it runs inside
    the same session as the tests that are mid-flight when pytest orders them
    that way, and a handful of live accounts is expected.
    """
    from db import connection

    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM users WHERE email LIKE %s",
                    ("%@example.test",))
        leaked = int(cur.fetchone()["n"])

    assert leaked <= 6, (
        f"{leaked} test accounts are sitting in the database. The cleanup "
        f"fixture is not covering every account these tests create; see "
        f"`created_emails`."
    )


@pytestmark_db
def test_no_test_companies_are_left_behind():
    """The same guard, for the table that reaches real users.

    A leaked `users` row is private clutter. A leaked `companies` row is not:
    `db.find_similar_companies` selects comparables from any company that has a
    report attached, so a fixture company is a live candidate to be shown to a
    real user as similar to the deck they just uploaded.

    That is not hypothetical. Before the `created_companies` fixture existed,
    Neon held 81 companies of which 33 were fixtures -- `ScopeTest <hex>` x11,
    `ListScope <hex>` x11, `Legacy <hex>` x11.

    A ceiling rather than zero, for the same reason as the accounts guard: this
    runs in the same session as tests that may be mid-flight.
    """
    from db import connection

    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM companies "
            "WHERE name LIKE 'ScopeTest %' OR name LIKE 'ListScope %' "
            "OR name LIKE 'Legacy %'"
        )
        leaked = int(cur.fetchone()["n"])

    assert leaked <= 3, (
        f"{leaked} fixture companies are sitting in the database, where "
        f"find_similar_companies can offer them to a real user as comparables. "
        f"The `created_companies` fixture is not covering every company these "
        f"tests create."
    )
