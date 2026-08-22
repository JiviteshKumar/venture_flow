"""
Build the labeled outcome dataset for the VentureFlow Outcome Model.

Source: yc-oss/api (github.com/yc-oss/api), a continuously-updated public
mirror of Y Combinator's own company directory. No scraping was done here —
this pulls the maintained JSON directly. Free, public, no API key.

Why filter by company age: YC's directory marks a company "Active" the
moment it launches, which tells you nothing about whether it will
eventually succeed or fail — a company from the Fall 2026 batch is
"Active" by definition, not because it beat the odds. Including those
would make the model look artificially confident. We only use companies
old enough that "Active" vs "Inactive" vs "Acquired"/"Public" reflects a
real, mostly-settled outcome, and we treat still-"Active" companies as
right-censored (excluded from training/eval, not treated as failures).

Label:
  1 (positive outcome) — status in {Acquired, Public}
  0 (negative outcome) — status == Inactive
  dropped — status == Active (outcome not yet resolved)

This is a coarse, weak proxy label — not a return multiple, not an IRR, not
anything a real fund would use to size a check. It is a defensible signal
for "did this company survive/exit vs. shut down," and it's the only
outcome signal available without a paid data source or a fund's own deal
history. That limitation belongs in the model card, not hidden.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_PATH = DATA_DIR / "yc_companies_raw.json"
OUT_PATH = DATA_DIR / "outcome_dataset.jsonl"

MIN_AGE_YEARS = 3.5  # a company needs real runway to have resolved its outcome either way


def main() -> None:
    # encoding="utf-8" is load-bearing, not decorative: the raw yc-oss dump
    # contains 14,833 non-ASCII bytes (accented founder names, en-dashes,
    # smart quotes). Path.read_text() with no encoding uses the platform
    # default, which is cp1252 on Windows -- so this line raised
    # UnicodeDecodeError and the documented "reproduce from scratch" command
    # in ml/README.md simply did not work on Windows. Caught by running it,
    # not by reading it. Note the derived .jsonl files below are unaffected
    # either way, because json.dumps escapes non-ASCII to \uXXXX by default.
    companies = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    now = time.time()
    min_age_seconds = MIN_AGE_YEARS * 365.25 * 24 * 3600

    kept, dropped_young, dropped_active, dropped_no_text = 0, 0, 0, 0
    rows = []

    for c in companies:
        launched_at = c.get("launched_at")
        status = c.get("status")
        text = (c.get("long_description") or "").strip()
        one_liner = (c.get("one_liner") or "").strip()

        if not launched_at or (now - launched_at) < min_age_seconds:
            dropped_young += 1
            continue
        if status == "Active":
            dropped_active += 1
            continue
        if len(text) < 40:
            dropped_no_text += 1
            continue

        if status in ("Acquired", "Public"):
            label = 1
        elif status == "Inactive":
            label = 0
        else:
            continue  # unknown/unlabeled status value

        age_years = round((now - launched_at) / (365.25 * 24 * 3600), 2)
        rows.append({
            "id": c["id"],
            "name": c["name"],
            "text": (one_liner + ". " + text).strip(),
            "status": status,
            "label": label,
            "industry": c.get("industry") or "unknown",
            "stage": c.get("stage") or "unknown",
            "batch": c.get("batch") or "unknown",
            "team_size": c.get("team_size") or 0,
            "num_tags": len(c.get("tags") or []),
            "nonprofit": bool(c.get("nonprofit")),
            "age_years": age_years,
        })
        kept += 1

    OUT_PATH.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    pos = sum(r["label"] for r in rows)
    print(f"Kept: {kept}  (positive/exit-or-acquired: {pos}, negative/shut-down: {kept - pos})")
    print(f"Dropped — too young (<{MIN_AGE_YEARS}y): {dropped_young}")
    print(f"Dropped — still Active (censored): {dropped_active}")
    print(f"Dropped — no usable description: {dropped_no_text}")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
