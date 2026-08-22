"""
Build the labeled dataset for the VentureFlow Score model.

This supersedes `prepare_outcome_dataset.py` (which stays, unchanged apart
from an encoding fix, because the existing Outcome Model is trained from it
and this repo does not silently break things other code depends on). The
difference is entirely in the feature set: the original kept six structured
features, and an audit of the raw yc-oss dump found a number of fields with
97-100% coverage that were never used, several of which are specifically
meaningful for *tech* startups rather than startups in general.

SOURCE. `ml/data/yc_companies_raw.json`, a snapshot of
https://github.com/yc-oss/api -- a continuously-updated public mirror of Y
Combinator's own company directory. MIT-licensed, no API key, no scraping.
The snapshot in this repo holds 6,189 companies. To refresh it, see the
"Reproducing" section of ml/README.md.

LABEL. Identical to the original, deliberately, so the two models remain
comparable: 1 = status in {Acquired, Public}, 0 = status == Inactive, and
still-"Active" companies are dropped as right-censored rather than being
treated as failures. Companies younger than 3.5 years are dropped because
"Active" for a company that launched last year carries no outcome
information. This is a coarse survived-or-exited proxy, not a return
multiple -- that limitation is real and belongs in the model card.

FEATURES ADDED IN THIS VERSION, and why each one is defensible for a
tech-startup-specific model:

  - subindustry (100% coverage, 59 distinct). YC's own second-level
    taxonomy, e.g. "B2B -> Infrastructure" vs "B2B -> Marketing". Far more
    informative for software companies than the 15-way top-level industry
    the original model used, and split here into its top and leaf halves so
    a tree can use either granularity.
  - Remote-work posture (derived from `regions`). The directory tags
    companies Remote / Fully Remote / Partly Remote. For tech startups
    specifically this is a real structural variable, not demographics.
  - Geography: is_bay_area, is_us (derived from `all_locations`).
    San Francisco alone accounts for 2,276 of 6,189 companies.
  - Tech tag indicators (from `tags`, 336 distinct). Binary flags for the
    most common technology categories -- SaaS, AI/ML, developer tools,
    fintech, marketplace, and so on. This is the most explicitly
    tech-specific block in the feature set: a generic startup-success model
    has no notion of "is this a developer-tools company."
  - has_former_name: whether the company ever operated under a different
    name, a weak rebrand/pivot signal. Legal-suffix-only variants ("Foo"
    vs "Foo Inc.") are normalised away first, because 91 of the raw
    former_names values are literally the string "Inc." and counting those
    as pivots would be measuring punctuation.
  - batch_year and batch_season, parsed from the batch label.
  - Text shape: description and one-liner lengths. How much a founder
    actually wrote about the company is cheap to measure and independent of
    what the TF-IDF features encode.

FIELDS DELIBERATELY EXCLUDED AS TARGET LEAKAGE. Each of these is available
in the raw data and would improve offline metrics while making the model
useless and dishonest in production, because none of them is knowable at
the time a VC would actually be scoring the company:

  - isHiring -- a shut-down company does not post jobs. This is an
    observation of the outcome, not a predictor of it.
  - top_company -- YC's own retrospective designation of its winners. This
    is very nearly the label wearing a different hat.
  - website liveness -- resolving each company's domain to see whether the
    site still loads would leak the outcome almost perfectly, for the same
    reason.
  - status, and anything derived from it other than the label itself.

Run:  python ml/scripts/prepare_venturescore_dataset.py
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_PATH = DATA_DIR / "yc_companies_raw.json"
OUT_PATH = DATA_DIR / "venturescore_dataset.jsonl"

MIN_AGE_YEARS = 3.5

# The technology categories flagged as individual binary features. Chosen by
# frequency in the raw dump (each appears on 150+ companies, so none is a
# near-constant column) and grouped where YC uses several labels for one
# concept -- "AI", "Artificial Intelligence", "Generative AI" and "Machine
# Learning" all describe the same sector to an investor.
TECH_TAG_GROUPS: dict[str, tuple[str, ...]] = {
    "tag_ai_ml": ("artificial intelligence", "ai", "machine learning", "generative ai", "aiops", "ai-powered"),
    "tag_saas": ("saas", "b2b saas"),
    "tag_b2b": ("b2b",),
    "tag_devtools": ("developer tools", "devops", "engineering", "open source", "api"),
    "tag_fintech": ("fintech", "payments", "banking as a service", "insurance", "crypto", "web3"),
    "tag_marketplace": ("marketplace", "e-commerce", "ecommerce", "retail"),
    "tag_healthcare": ("healthcare", "health tech", "digital health", "biotech", "medical devices"),
    "tag_infra": ("infrastructure", "cloud computing", "data engineering", "database", "security", "cybersecurity"),
    "tag_consumer": ("consumer", "social", "community", "consumer health services"),
    "tag_analytics": ("analytics", "data science", "business intelligence"),
    "tag_hardware": ("hardware", "robotics", "drones", "manufacturing", "iot"),
    "tag_productivity": ("productivity", "automation", "workflow", "collaboration"),
}

# Stripped before deciding whether a former name is a genuine rebrand.
LEGAL_SUFFIX_RE = re.compile(r"[\s,\.]*\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|gmbh|sa|bv|pbc)\b[\s,\.\)]*$", re.I)


def _normalise_company_name(name: str) -> str:
    prev = None
    out = (name or "").strip().lower()
    while prev != out:  # "Foo Inc, Ltd." needs more than one pass
        prev = out
        out = LEGAL_SUFFIX_RE.sub("", out).strip()
    return re.sub(r"[^a-z0-9]+", "", out)


def _has_real_former_name(company: dict) -> bool:
    """True only if some former name differs from the current one by more
    than legal suffixes/punctuation. 91 raw former_names entries are the
    bare string "Inc." -- counting those as pivots would be noise."""
    current = _normalise_company_name(company.get("name") or "")
    for former in company.get("former_names") or []:
        normalised = _normalise_company_name(str(former))
        if normalised and normalised != current:
            return True
    return False


def _parse_batch(batch: str) -> tuple[int, str]:
    """'Winter 2022' -> (2022, 'Winter'). Returns (0, 'unknown') if unparseable."""
    match = re.match(r"([A-Za-z]+)\s+(\d{4})", (batch or "").strip())
    if not match:
        return 0, "unknown"
    return int(match.group(2)), match.group(1)


def _tag_features(company: dict) -> dict[str, int]:
    tags = {str(t).strip().lower() for t in (company.get("tags") or [])}
    return {
        feature: int(any(keyword in tags for keyword in keywords))
        for feature, keywords in TECH_TAG_GROUPS.items()
    }


def _region_features(company: dict) -> dict[str, int]:
    regions = {str(r).strip().lower() for r in (company.get("regions") or [])}
    locations = (company.get("all_locations") or "").lower()
    return {
        "is_fully_remote": int("fully remote" in regions),
        "is_partly_remote": int("partly remote" in regions),
        "is_any_remote": int(any("remote" in r for r in regions)),
        "is_bay_area": int("san francisco" in locations or "palo alto" in locations
                           or "mountain view" in locations or "berkeley, ca" in locations),
        "is_us": int("usa" in locations or "united states" in locations),
    }


def main() -> None:
    companies = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    now = time.time()
    min_age_seconds = MIN_AGE_YEARS * 365.25 * 24 * 3600

    rows: list[dict] = []
    dropped_young = dropped_active = dropped_no_text = dropped_unknown_status = 0

    for c in companies:
        launched_at = c.get("launched_at")
        status = c.get("status")
        long_description = (c.get("long_description") or "").strip()
        one_liner = (c.get("one_liner") or "").strip()

        if not launched_at or (now - launched_at) < min_age_seconds:
            dropped_young += 1
            continue
        if status == "Active":
            dropped_active += 1
            continue
        if len(long_description) < 40:
            dropped_no_text += 1
            continue
        if status in ("Acquired", "Public"):
            label = 1
        elif status == "Inactive":
            label = 0
        else:
            dropped_unknown_status += 1
            continue

        subindustry = c.get("subindustry") or "unknown"
        subindustry_top, _, subindustry_leaf = subindustry.partition("->")
        batch_year, batch_season = _parse_batch(c.get("batch") or "")

        row = {
            "id": c["id"],
            "name": c["name"],
            "text": (one_liner + ". " + long_description).strip(),
            "label": label,
            # -- categorical --
            "industry": c.get("industry") or "unknown",
            "subindustry_top": subindustry_top.strip() or "unknown",
            "subindustry_leaf": (subindustry_leaf.strip() or subindustry_top.strip() or "unknown"),
            "stage": c.get("stage") or "unknown",
            "batch_season": batch_season,
            # -- numeric --
            "team_size": c.get("team_size") or 0,
            "num_tags": len(c.get("tags") or []),
            "nonprofit": int(bool(c.get("nonprofit"))),
            "age_years": round((now - launched_at) / (365.25 * 24 * 3600), 2),
            "batch_year": batch_year,
            "desc_len": len(long_description),
            "one_liner_len": len(one_liner),
            "has_former_name": int(_has_real_former_name(c)),
        }
        row.update(_tag_features(c))
        row.update(_region_features(c))
        rows.append(row)

    OUT_PATH.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    positives = sum(r["label"] for r in rows)
    print(f"Kept {len(rows)} companies "
          f"({positives} exited/acquired, {len(rows) - positives} shut down, "
          f"base rate {positives / len(rows):.3f})")
    print(f"Dropped -- younger than {MIN_AGE_YEARS}y:        {dropped_young}")
    print(f"Dropped -- still Active (right-censored): {dropped_active}")
    print(f"Dropped -- no usable description:         {dropped_no_text}")
    print(f"Dropped -- unrecognised status value:     {dropped_unknown_status}")

    feature_names = [k for k in rows[0] if k not in ("id", "name", "text", "label")]
    print(f"\n{len(feature_names)} non-text features: {', '.join(feature_names)}")
    print("\nCoverage of the binary features (guards against near-constant columns):")
    for name in feature_names:
        values = [r[name] for r in rows]
        if set(values) <= {0, 1}:
            print(f"  {name:22s} positive in {sum(values):4d}/{len(rows)} ({100 * sum(values) / len(rows):5.1f}%)")
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
