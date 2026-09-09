"""Remove test fixtures and filename-derived rows from `companies`.

WHY

`db.find_similar_companies` offers comparables from any company that has a
report attached, so every row in `companies` is a candidate to be shown to a
real user as a peer of the deck they just uploaded. The table had accumulated
two kinds of row that are not companies:

  * upload filenames, from before the name was cleaned at the API boundary --
    "02 uber", "05 dropbox", "claritycare health pitch deck". A real Uber
    analysis returned exactly one comparable, "02 uber", matched back to
    "Uber" by trigram similarity on its own filename.
  * fixture companies left behind by tests/test_auth.py -- `ScopeTest <hex>`,
    `ListScope <hex>`, `Legacy <hex>`.

Both causes are fixed (names are cleaned before storage, tests clean up after
themselves, and the comparables query filters its results). This removes the
rows that are already there.

SAFETY

Dry run by default: it prints exactly what it would delete and changes
nothing. `--apply` performs the deletion. The classifier is
`db._is_a_real_company_name`, the same one the comparables query uses, so this
deletes exactly the rows that are already being withheld from users -- nothing
that is currently visible to anyone is removed.

Order matters: dd_reports.company_id is ON DELETE NO ACTION, so reports go
first. investment_decisions and report_comments cascade from the report;
analysed_companies nulls its reference.

    python scripts/clean_junk_companies.py            # show what would go
    python scripts/clean_junk_companies.py --apply    # actually delete
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import console_safety  # noqa: F401,E402
import db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="perform the deletion (default is a dry run)")
    args = parser.parse_args()

    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT c.id, c.name, count(dr.id) AS reports "
            "FROM companies c LEFT JOIN dd_reports dr ON dr.company_id = c.id "
            "GROUP BY c.id, c.name ORDER BY c.name"
        )
        rows = cur.fetchall()

    junk = [r for r in rows if not db._is_a_real_company_name(r["name"])]
    keep = [r for r in rows if db._is_a_real_company_name(r["name"])]

    print(f"{len(rows)} companies: {len(keep)} real, {len(junk)} junk\n")
    print("WOULD DELETE:" if not args.apply else "DELETING:")
    for r in junk:
        print(f"   {r['reports']:3d} report(s)   {r['name']}")
    print("\nKEEPING:")
    for r in keep:
        print(f"   {r['reports']:3d} report(s)   {r['name']}")

    if not junk:
        print("\nNothing to do.")
        return 0
    if not args.apply:
        print(f"\nDry run. {len(junk)} companies and "
              f"{sum(r['reports'] for r in junk)} reports would be deleted.")
        print("Re-run with --apply to perform the deletion.")
        return 0

    deleted_reports = 0
    with db.connection() as conn, conn.cursor() as cur:
        for r in junk:
            cur.execute("DELETE FROM dd_reports WHERE company_id = %s", (r["id"],))
            deleted_reports += cur.rowcount
            cur.execute("DELETE FROM companies WHERE id = %s", (r["id"],))
    print(f"\nDeleted {len(junk)} companies and {deleted_reports} reports.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
