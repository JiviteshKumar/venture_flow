"""Build the real-world validation harness: decks with known outcomes, split once.

THE QUESTION THIS IS FOR

Does the product's score correspond to what actually happened to the company?
Not "is the pipeline internally consistent" -- that is what every existing
benchmark measures -- but "would a VC following this have been directionally
right".

TWO POPULATIONS, AND ONLY ONE OF THEM CAN ANSWER IT

**Deck set (small, severely biased).** Real pitch decks from companies with a
recorded outcome. Two provenance facts are recorded per entry and kept apart,
because they are different claims with different reliability:

  - `deck_provenance`   -- where the deck file came from
  - `outcome_provenance` -- the citable source for what happened to the company

The deck set has a limitation so severe it has to lead rather than trail:
**every company in it succeeded.** Airbnb, Uber and Coinbase went public; Mint
was acquired; Buffer, Intercom and Front are still operating and funded. There
is not one shutdown in the set.

That is not an oversight, it is the selection mechanism. Decks become public
because the company became famous, and companies become famous by succeeding.
A dead startup's deck is not published by anyone.

The consequence is precise and worth stating rather than hedging: **a set with
no negative examples cannot measure discrimination at all.** No AUC, no
precision, no recall -- those all require both classes. A model that returns 95
for every input scores perfectly on this set. The most it can support is
"do known-good companies score above the population median", which is a weak
sanity check and not a validation.

**YC outcome set (larger, genuinely labelled).** 1,560 Y Combinator companies
with recorded Acquired/Public/Inactive outcomes -- 726 successes and 834
failures. This is the population that can actually answer the question, and it
is why the deck set is explicitly the secondary signal here rather than the
headline.

It has its own biases and they are stated too: YC-only, description text rather
than a real deck, and a base rate (46.5% success) far above the industry's.

THE SPLIT IS MADE ONCE, HERE, BEFORE ANY RESULT IS LOOKED AT

Assignment is deterministic -- SHA-256 of the company name, low bit -- so it is
reproducible, not re-rollable until it looks good. Written to SPLIT.lock.json
with a hash, and `verify_split_untouched()` fails if either file changed.

    python ml/scripts/build_validation_harness.py
    python ml/scripts/build_validation_harness.py --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: F401  (Windows cp1252 guard)

DECK_DIR = ROOT / "ml" / "eval" / "decks"
OUT_DIR = ROOT / "ml" / "eval" / "validation"
MANIFEST_PATH = OUT_DIR / "validation_manifest.json"
LOCK_PATH = OUT_DIR / "SPLIT.lock.json"

# Outcome labels. `success` mirrors the YC outcome dataset's definition exactly
# (acquired or public or still operating and funded = 1; shut down = 0) so the
# two populations are scored on one convention.
OUTCOMES: dict[str, dict] = {
    "Airbnb": {
        "outcome": "public",
        "success": 1,
        "outcome_detail": "IPO on NASDAQ (ABNB), 10 December 2020.",
        "outcome_provenance": "https://news.airbnb.com/airbnb-announces-pricing-of-initial-public-offering/",
        "outcome_source_kind": "company press release",
    },
    "Uber": {
        "outcome": "public",
        "success": 1,
        "outcome_detail": "IPO on NYSE (UBER), 10 May 2019.",
        "outcome_provenance": "https://investor.uber.com/news-events/news/press-release-details/2019/Uber-Announces-Pricing-of-Initial-Public-Offering/",
        "outcome_source_kind": "company investor relations",
    },
    "Coinbase": {
        "outcome": "public",
        "success": 1,
        "outcome_detail": "Direct listing on NASDAQ (COIN), 14 April 2021.",
        "outcome_provenance": "https://investor.coinbase.com/news/news-details/2021/Coinbase-Announces-Listing-of-Class-A-Common-Stock/",
        "outcome_source_kind": "company investor relations",
    },
    "Mint": {
        "outcome": "acquired",
        "success": 1,
        "outcome_detail": (
            "Acquired by Intuit for ~$170M, announced 13 September 2009. "
            "The product was later discontinued in January 2024, which does not "
            "change the investment outcome: the acquisition was the exit."
        ),
        "outcome_provenance": "https://investors.intuit.com/news-events/press-releases/detail/451/intuit-to-acquire-mint-com",
        "outcome_source_kind": "acquirer press release",
    },
    "Buffer": {
        "outcome": "operating",
        "success": 1,
        "outcome_detail": (
            "Still operating and profitable; publishes a public revenue "
            "dashboard. Took no further institutional capital after the seed and "
            "Series A, and bought out its main investors in 2018."
        ),
        "outcome_provenance": "https://buffer.com/resources/",
        "outcome_source_kind": "company website (open metrics)",
    },
    "Intercom": {
        "outcome": "operating",
        "success": 1,
        "outcome_detail": "Still operating; raised through Series D and remains independent.",
        "outcome_provenance": "https://www.intercom.com/blog",
        "outcome_source_kind": "company website",
    },
    "Front": {
        "outcome": "operating",
        "success": 1,
        "outcome_detail": "Still operating; raised a Series D in 2022 and remains independent.",
        "outcome_provenance": "https://front.com/blog",
        "outcome_source_kind": "company website",
    },
}

# Where the deck FILES came from, recorded separately from the outcome sources
# and deliberately not flattered.
DECK_PROVENANCE_NOTE = (
    "THIRD-PARTY AGGREGATOR, NOT FIRST-PARTY PUBLICATION. Every deck in this "
    "set was fetched from media.genppt.com, a site that re-hosts well-known "
    "pitch decks. That does not meet the standard applied to the SEC filing "
    "corpus, where each excerpt carries a primary-source URL on the regulator's "
    "own domain.\n\n"
    "A search for genuinely first-party publications -- a company hosting its "
    "own deck on its own blog -- was run and largely failed. Company blogs are "
    "reachable (buffer.com/resources, front.com/blog, baremetrics.com/blog all "
    "return 200), but the deck FILES are not served from them, and search "
    "results for these decks are dominated by aggregators and pitch-deck "
    "consultancies re-hosting the same files.\n\n"
    "Recorded rather than fixed, because the honest options were to report the "
    "weaker provenance or to pad the set, and the second is worse."
)



YC_HOLDOUT_PATH = OUT_DIR / "yc_holdout.jsonl"


def build_yc_holdout() -> dict:
    """Companies in the outcome dataset that the SCORE MODEL never saw.

    This exists because of a leakage finding. `ml/scripts/eval_score_baseline.py`
    draws its 300-company sample from `ml/data/venturescore_dataset.jsonl` --
    which is the file `train_venturescore_model.py` fits on. Measured directly:
    **300 of 300 evaluated companies are in the training file.** The published
    "VentureFlow Score 0.668 vs legacy formula 0.500" discrimination figure is
    therefore an IN-SAMPLE number.

    Two things are worth separating. The comparison's conclusion survives: the
    legacy formula scores exactly 0.500 because it reads no company feature at
    all, and no amount of leakage changes that. What does not survive is 0.668
    as an estimate of held-out performance.

    Mitigating, and relevant to how alarmed to be: the trainer's own
    cross-validated ROC-AUC is 0.67, essentially identical. That suggests the
    model is not badly overfit -- but a matching CV number is evidence, not a
    substitute for a clean holdout.

    So this builds one. outcome_dataset.jsonl has 1,560 labelled companies and
    the training file has 1,298; the difference is a set the score model has
    genuinely never been fitted on.
    """
    def _rows(path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    trained_on = {
        (r.get("name") or "").strip().lower()
        for r in _rows(ROOT / "ml" / "data" / "venturescore_dataset.jsonl")
    }
    holdout = [
        r for r in _rows(ROOT / "ml" / "data" / "outcome_dataset.jsonl")
        if (r.get("name") or "").strip().lower() not in trained_on
        and r.get("label") in (0, 1)
        and (r.get("description") or r.get("text"))
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with YC_HOLDOUT_PATH.open("w", encoding="utf-8") as handle:
        for row in sorted(holdout, key=lambda r: (r.get("name") or "").lower()):
            handle.write(json.dumps(row) + chr(10))

    successes = sum(1 for r in holdout if r["label"] == 1)
    return {
        "n": len(holdout),
        "n_success": successes,
        "n_failure": len(holdout) - successes,
        "base_rate": round(successes / len(holdout), 4) if holdout else None,
        "path": str(YC_HOLDOUT_PATH.relative_to(ROOT)),
        "why": (
            "Genuinely out-of-sample for the VentureFlow Score: every company "
            "here is absent from venturescore_dataset.jsonl, the file the model "
            "is fitted on."
        ),
        "note_on_base_rate": (
            "The holdout's success rate differs from the training file's, because "
            "the holdout is what was left over rather than a random draw. It is "
            "out-of-sample, not identically distributed, so a score calibrated on "
            "the training base rate will look mis-calibrated here even when its "
            "ranking is fine. Read AUC off it, not calibration."
        ),
    }


def _split_of(company: str) -> str:
    """Deterministic assignment from the company name.

    Deterministic on purpose. A random split can be re-rolled until the numbers
    look better, and nothing in the artifact would show that it had been.
    """
    digest = hashlib.sha256(company.strip().lower().encode("utf-8")).hexdigest()
    return "test" if int(digest, 16) & 1 else "train"


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    source = json.loads((DECK_DIR / "manifest.json").read_text(encoding="utf-8"))
    entries = []
    missing_outcome = []

    for row in source:
        company = row["company"]
        outcome = OUTCOMES.get(company)
        if outcome is None:
            missing_outcome.append(company)
            continue
        entries.append({
            "company": company,
            "deck_year": row.get("deck_year"),
            "file": row.get("file"),
            "deck_sha256": row.get("sha256"),
            "extracted_chars": row.get("extracted_chars"),
            "pages": row.get("pages"),
            "deck_source_url": row.get("source_url"),
            "deck_source_kind": "third-party aggregator (media.genppt.com)",
            "deck_is_first_party": False,
            "split": _split_of(company),
            **outcome,
        })

    entries.sort(key=lambda e: e["company"])
    successes = sum(e["success"] for e in entries)

    manifest = {
        "purpose": (
            "Validate the product's score against real company outcomes. Built "
            "before any result was inspected; the split is fixed here."
        ),
        "deck_provenance_note": DECK_PROVENANCE_NOTE,
        "critical_limitation": (
            f"ALL {len(entries)} companies in this set SUCCEEDED "
            f"({successes} of {len(entries)} labelled success=1, zero shutdowns). "
            "This is the selection mechanism, not an oversight: decks become "
            "public because companies become famous, and companies become famous "
            "by succeeding. With no negative class, this set CANNOT produce an "
            "AUC, a precision or a recall -- a model returning a constant 95 "
            "would score perfectly. The most it supports is 'do known-good "
            "companies score above the population median', a sanity check rather "
            "than a validation. The YC outcome set below is the population that "
            "can actually answer the question."
        ),
        "secondary_population": {
            "name": "YC outcome dataset",
            "path": "ml/data/outcome_dataset.jsonl",
            "n": 1560,
            "n_success": 726,
            "n_failure": 834,
            "base_rate": 0.4654,
            "why_it_is_the_primary_signal": (
                "It has both classes, so discrimination is measurable. It is "
                "also larger by two orders of magnitude."
            ),
            "its_own_biases": (
                "Y Combinator only; company descriptions rather than real decks; "
                "a 46.5% success base rate far above the industry's."
            ),
        },
        "n_decks": len(entries),
        "n_success": successes,
        "n_failure": len(entries) - successes,
        "decks": entries,
    }
    if missing_outcome:
        manifest["decks_excluded_for_unknown_outcome"] = missing_outcome
    return manifest


def write_lock(manifest: dict) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    assignments = {e["company"]: e["split"] for e in manifest["decks"]}
    lock = {
        "locked_at_manifest_sha256": _sha256_of(MANIFEST_PATH),
        "assignment_rule": "sha256(company_name.lower()) low bit -> 1=test, 0=train",
        "why_deterministic": (
            "A random split can be re-rolled until the numbers look better and "
            "nothing in the artifact would show it had been. This one is "
            "reproducible from the company name alone."
        ),
        "rule": (
            "TEST-SPLIT COMPANIES ARE NOT TO BE INSPECTED until the final "
            "evaluation. Do not read their scores, tune against them, or use "
            "them to choose a threshold. Verify with --verify before reporting "
            "any test-split number."
        ),
        "train": sorted(c for c, s in assignments.items() if s == "train"),
        "test": sorted(c for c, s in assignments.items() if s == "test"),
    }
    LOCK_PATH.write_text(json.dumps(lock, indent=2), encoding="utf-8")
    return lock


def verify() -> int:
    if not (MANIFEST_PATH.exists() and LOCK_PATH.exists()):
        print("Harness not built yet. Run without --verify first.")
        return 2
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    actual = _sha256_of(MANIFEST_PATH)
    if actual != lock["locked_at_manifest_sha256"]:
        print("SPLIT VIOLATION: the manifest changed after the split was locked.")
        print(f"  locked: {lock['locked_at_manifest_sha256']}")
        print(f"  actual: {actual}")
        return 1

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for entry in manifest["decks"]:
        if entry["split"] != _split_of(entry["company"]):
            print(f"SPLIT VIOLATION: {entry['company']} reassigned.")
            return 1
    print(f"Split intact. train={len(lock['train'])} test={len(lock['test'])}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        return verify()

    if LOCK_PATH.exists():
        print(f"{LOCK_PATH.name} already exists -- refusing to re-split.")
        print("Re-splitting after seeing results is the failure this file prevents.")
        return verify()

    manifest = build()
    manifest["yc_holdout"] = build_yc_holdout()
    lock = write_lock(manifest)

    print(f"Decks with a recorded outcome : {manifest['n_decks']}")
    print(f"  success / failure           : {manifest['n_success']} / {manifest['n_failure']}")
    print(f"  train split                 : {len(lock['train'])}  {lock['train']}")
    print(f"  test split                  : {len(lock['test'])}  {lock['test']}")
    if manifest.get("decks_excluded_for_unknown_outcome"):
        print(f"  excluded (no outcome)       : {manifest['decks_excluded_for_unknown_outcome']}")
    print()
    print("!! " + manifest["critical_limitation"][:300])
    holdout = manifest["yc_holdout"]
    print(
        "\nYC holdout (never seen by the score model): "
        f"{holdout['n']} companies, "
        f"{holdout['n_success']} success / "
        f"{holdout['n_failure']} failure "
        f"(base rate {holdout['base_rate']:.1%})"
    )
    print(f"Wrote {YC_HOLDOUT_PATH}")
    print(f"\nWrote {MANIFEST_PATH}\nWrote {LOCK_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
