"""The test suite must never read or write the production schema.

tests/conftest.py gives every run its own schema and points DATABASE_URL at
it. These tests fail if that ever stops being true -- for example if some
module starts calling `load_dotenv(override=True)`, which would quietly put
the production URL back and every database test would write to production
again while still passing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import TEST_SCHEMA_PREFIX, isolated_database_url

ROOT = Path(__file__).resolve().parents[1]


def _database_available() -> bool:
    try:
        from db import count_users
        count_users()
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not _database_available(), reason="no database reachable")


class TestTheUrlRewrite:
    def test_moves_to_the_direct_endpoint_and_sets_the_search_path(self):
        url = "postgresql://u:p@ep-x-pooler.region.aws.neon.tech/neondb?sslmode=require"
        out = isolated_database_url(url, "vf_test_1_2")
        assert "-pooler" not in out
        assert "sslmode=require" in out
        assert "options=-csearch_path%3Dvf_test_1_2%2Cpublic" in out

    def test_keeps_an_existing_options_parameter(self):
        url = "postgresql://u:p@host/db?options=endpoint%3Dep-x"
        out = isolated_database_url(url, "vf_test_1_2")
        assert out.count("options=") == 1
        assert "endpoint%3Dep-x%20-csearch_path%3Dvf_test_1_2%2Cpublic" in out


@requires_db
class TestTheRunIsIsolated:
    def test_this_process_writes_to_a_test_schema(self):
        from db import connection

        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT current_schema() AS s")
            schema = cur.fetchone()["s"]
        assert schema.startswith(TEST_SCHEMA_PREFIX), (
            f"the suite is connected to schema {schema!r}; database tests would "
            f"be reading and writing production data"
        )

    def test_the_test_schema_has_every_table(self):
        """ensure_schema() ran against the test schema: a table from the
        newest migration exists there, not only in public."""
        from db import connection

        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = ANY(%s)",
                (["users", "dd_reports", "companies", "claim_verdict_cache"],),
            )
            assert cur.fetchone()["n"] == 4

    def test_a_subprocess_that_loads_dotenv_stays_isolated(self):
        """Scripts run from tests (the artifact check, the evals) call
        load_dotenv on start. It must not override the inherited URL."""
        program = (
            "import sys; sys.path.insert(0, %r)\n"
            "from dotenv import load_dotenv; load_dotenv(%r)\n"
            "import db\n"
            "with db.connection() as c, c.cursor() as cur:\n"
            "    cur.execute('SELECT current_schema() AS s'); print(cur.fetchone()['s'])\n"
            "db.close_pool()\n"
        ) % (str(ROOT), str(ROOT / ".env"))
        result = subprocess.run([sys.executable, "-c", program], capture_output=True,
                                text=True, cwd=str(ROOT), timeout=120, env=os.environ.copy())
        assert result.returncode == 0, result.stderr[-500:]
        assert result.stdout.strip().startswith(TEST_SCHEMA_PREFIX), result.stdout
