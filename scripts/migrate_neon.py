from __future__ import annotations

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db import connection


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply VentureFlow Neon migrations")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print migrations without changing the database"
    )
    args = parser.parse_args()
    migrations = sorted(
        migration
        for migration in Path(__file__).resolve().parents[1].joinpath("migrations").glob("*.sql")
        if not migration.name.endswith(".down.sql")
    )
    if args.dry_run:
        print("Would apply:")
        for migration in migrations:
            print(f"- {migration.name}")
        return
    with connection() as conn, conn.cursor() as cur:
        for migration in migrations:
            cur.execute(migration.read_text(encoding="utf-8"))
        conn.commit()
    print(f"Applied {len(migrations)} Neon migration(s).")


if __name__ == "__main__":
    main()
