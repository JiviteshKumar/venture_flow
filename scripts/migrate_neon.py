from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db import connection


def main() -> None:
    migrations = sorted(
        Path(__file__).resolve().parents[1].joinpath("migrations").glob("*.sql")
    )
    with connection() as conn, conn.cursor() as cur:
        for migration in migrations:
            cur.execute(migration.read_text(encoding="utf-8"))
        conn.commit()
    print(f"Applied {len(migrations)} Neon migration(s).")


if __name__ == "__main__":
    main()
