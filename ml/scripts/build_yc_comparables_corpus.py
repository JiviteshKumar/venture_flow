"""A comparable-company corpus with graded outcomes, including quiet survivors.

WHY THIS IS SEPARATE FROM THE TRAINING DATASET

`ml/data/outcome_dataset.jsonl` exists to train a binary classifier, so it keeps
only companies with a resolved binary outcome: exited (1) or shut down (0).
Every company still trading is dropped, because "still going" is not one of the
two classes.

That is defensible for training and misleading for display. Of 5,132 technology
companies in YC's directory:

    shut down                     792   15.4%
    still operating, no exit    3,593   70.0%
    ordinary exit                 672   13.1%
    outsized (YC "top company")    75    1.5%

A comparables table built from the training dataset shows only the first, third
and fourth rows -- 30% of the population -- and so implies that a company like
yours either exits or dies, when the overwhelmingly most likely outcome is that
it keeps operating without either. It also renders a modest acquihire and a
fund-returning IPO with the same two words, "Acquired/Public".

This corpus fixes both, for display only. It is never used to fit a model.

THE GRADED TIER, AND WHAT IT IS WORTH

`top_company` is Y Combinator's own flag for its standout companies -- Stripe,
Gusto, Segment, PagerDuty. It is a good outcome proxy and a terrible feature:
20 of 23 IPOs carry it and 1 of 1,069 failures does, so it tracks the outcome
closely, which is exactly why using it as an input would be leakage. Here it is
used only as a LABEL, to grade what happened.

It is YC's editorial judgement rather than a financial fact, and this file says
so wherever the tier is surfaced. There is no free source of exit VALUES.

WHETHER THE TIER CAN BE PREDICTED -- MEASURED, AND MOSTLY NO

Before building this it was worth asking whether the product could predict an
outsized outcome rather than merely report one. Ranking companies within a
single YC batch, so that age cannot inflate the result:

    outsized vs everything else            0.5388 AUC [0.4338, 0.6595]
    outsized vs survivors + ordinary exits  0.5892 AUC [0.5079, 0.6867]
    outsized exit vs ordinary exit          0.6482 AUC [0.5918, 0.7085]

The first two straddle chance. The third looks usable until you notice that
description LENGTH alone scores 0.6354 on it, and that outsized companies have a
median 607-character YC profile against 420 for ordinary exits -- a company that
became famous gets a longer, better-tended directory entry, written after it
became famous. That is the profile-maintenance bias `ml/README.md` already warns
about, not a property of the company at seed stage.

So the tier is reported, never predicted. Showing a VC that three of their five
comparables quietly kept operating is useful; telling them their company has a
1.5% chance of being the next Stripe would be a number we cannot support.

USAGE

    python ml/scripts/build_yc_comparables_corpus.py --out ml/data/yc_comparables.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ml" / "scripts"))

from prepare_venturescore_dataset import _is_tech_startup, _parse_batch  # noqa: E402

RAW_PATH = ROOT / "ml" / "data" / "yc_companies_raw.json"

# Below this there is nothing to embed and nothing worth showing a reader.
MIN_TEXT_CHARS = 40

# Tier -> (machine key, what a reader sees, one-line meaning).
TIERS: dict[int, tuple[str, str, str]] = {
    0: ("shut_down", "Shut down",
        "No longer operating."),
    1: ("operating", "Still operating",
        "Independent and still trading, with no exit recorded. The most common "
        "outcome by a wide margin."),
    2: ("exit", "Exit",
        "Acquired or went public. The size of the exit is not recorded and is "
        "not knowable from free sources -- this covers everything from an "
        "acquihire to a large sale."),
    3: ("outsized", "Outsized outcome",
        "Flagged by Y Combinator as one of its top companies. YC's editorial "
        "judgement, not a financial figure, and the closest free proxy for "
        "'returned a fund'."),
}


def tier_of(status: str, top_company: bool) -> int:
    """Graded outcome for one company.

    `top_company` is checked before status so that an outsized company still
    trading (Stripe has not exited) is not filed as an ordinary survivor.
    """
    if status == "Inactive":
        # One company is flagged top_company and Inactive. Dead is dead; the
        # flag does not override a shutdown.
        return 0
    if top_company:
        return 3
    return 2 if status in ("Acquired", "Public") else 1


def build(out_path: Path) -> dict[str, Any]:
    companies = json.loads(RAW_PATH.read_text(encoding="utf-8"))

    rows: list[dict[str, Any]] = []
    dropped_not_tech = dropped_no_text = dropped_status = 0
    for company in companies:
        status = company.get("status")
        if status not in ("Active", "Inactive", "Acquired", "Public"):
            dropped_status += 1
            continue
        if not _is_tech_startup(company):
            dropped_not_tech += 1
            continue
        text = " ".join(filter(None, [
            (company.get("one_liner") or "").strip(),
            (company.get("long_description") or "").strip(),
        ])).strip()
        if len(text) < MIN_TEXT_CHARS:
            dropped_no_text += 1
            continue

        top = bool(company.get("top_company"))
        tier = tier_of(status, top)
        key, label, _meaning = TIERS[tier]
        batch_year, _season = _parse_batch(company.get("batch") or "")

        rows.append({
            "id": company["id"],
            "name": company["name"],
            "text": re.sub(r"\s+", " ", text),
            "industry": company.get("industry") or "",
            "subindustry": company.get("subindustry") or "",
            "stage": company.get("stage") or "",
            "batch": company.get("batch") or "",
            "batch_year": batch_year or None,
            "outcome_tier": tier,
            "outcome_key": key,
            "outcome": label,
            # Kept so a reader can see the raw fact behind the tier.
            "yc_status": status,
            "yc_top_company": top,
            "source": "yc",
            "source_url": (
                f"https://www.ycombinator.com/companies/{company['slug']}"
                if company.get("slug") else ""
            ),
        })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    counts = {key: 0 for key, _label, _m in TIERS.values()}
    for row in rows:
        counts[row["outcome_key"]] += 1
    total = len(rows) or 1

    summary = {
        "n_rows": len(rows),
        "tier_counts": counts,
        "tier_rates": {k: round(v / total, 4) for k, v in counts.items()},
        "exit_rate_including_outsized": round(
            (counts["exit"] + counts["outsized"]) / total, 4),
        "dropped": {
            "not_tech": dropped_not_tech,
            "text_too_short": dropped_no_text,
            "unrecognised_status": dropped_status,
        },
        "tier_meanings": {
            key: {"label": label, "meaning": meaning}
            for key, label, meaning in TIERS.values()
        },
        "source": {
            "name": "yc-oss/api (Y Combinator's public company directory)",
            "url": "https://github.com/yc-oss/api",
            "licence": "public directory data",
        },
        "display_only": (
            "This corpus is for comparable-company display. It is never used to "
            "fit a model: the outsized tier is not predictable from pre-outcome "
            "features (within-batch AUC 0.5892 [0.5079, 0.6867] against "
            "survivors and ordinary exits), and what separability there is among "
            "exits is largely profile-maintenance bias -- description length "
            "alone scores 0.6354."
        ),
        "why_the_headline_base_rate_differs": (
            "The VentureFlow Score model reports a base rate of 48.9%. That is "
            "the share of exits among companies that had ALREADY either exited "
            "or shut down, because the training set excludes companies still "
            f"operating. Across this full population the exit rate is "
            f"{round((counts['exit'] + counts['outsized']) / total * 100, 1)}% "
            f"and the outsized rate is "
            f"{round(counts['outsized'] / total * 100, 1)}%. Both numbers are "
            "correct about different questions, and only the second answers "
            "'how often does a company like this exit'."
        ),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(out_path.with_suffix(".provenance.json"), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="ml/data/yc_comparables.jsonl")
    args = parser.parse_args()

    summary = build(Path(args.out))
    print(json.dumps({k: v for k, v in summary.items()
                      if k in ("n_rows", "tier_counts", "tier_rates",
                               "exit_rate_including_outsized", "dropped")}, indent=2))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
