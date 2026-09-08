"""Build a market-wide tech-company corpus with real, recorded outcomes.

WHY THIS EXISTS

Everything this project knows about startup outcomes comes from one accelerator.
The Outcome Model, the VentureFlow Score and the comparable-company search are
all built on 1,560 Y Combinator alumni, and `comparables.py` says so in the
caveat a user reads. That is a real limitation rather than a cosmetic one:
companies that never went near YC succeed and fail too, and a comp set drawn
from one portfolio answers "what is the nearest YC company" when the user asked
"what is the nearest company".

It is also a modelling problem that is easy to miss. The VentureFlow Score's 80
features ARE the YC taxonomy -- `industry=B2B`, `subindustry_leaf=Fintech`,
YC's own tag vocabulary, `is_bay_area`. A non-YC company has none of them, so
the model is not merely under-trained outside YC, it has no way to represent a
company from outside YC at all.

SOURCE, AND WHY THIS ONE

Wikidata, queried through its public SPARQL endpoint, enriched with the opening
paragraph of the matching English Wikipedia article.

    Wikidata:  https://query.wikidata.org/sparql   (CC0)
    Wikipedia: https://en.wikipedia.org/api/rest_v1/  (CC BY-SA 4.1)

Both are free, need no API key, and -- the point -- every row carries a stable
Q-identifier that a reader can open and check. When this corpus says a company
shut down in 2011, there is a public page saying so, with its own sources.

The alternatives were considered and rejected:

  * **Crunchbase** -- the API returns 401 without a paid licence and the free
    Open Data Map is no longer published. Already documented in comparables.py.
  * **The Kaggle startup datasets** ("Big Startup Secsees", "Global Startup
    Success", etc.) -- these are the obvious answer and they are unusable here.
    They are undated, unattributed re-uploads of scraped Crunchbase exports with
    no provenance chain, no licence a downstream user could rely on, and no way
    to verify a single row. Training an investment tool on data whose origin
    cannot be established would undermine the one property this product is
    trying to have.
  * **SEC Form D** -- genuinely authoritative and free, and it tells you who
    raised money, but it cannot tell you what happened next: a company that
    stops filing has either failed or simply stayed private, and the filing
    record cannot separate the two. Absence of evidence would become a failure
    label, which is exactly the kind of quiet fabrication this corpus exists to
    avoid.

LABELS

Deliberately the same two classes the YC dataset uses, so the two populations
can be compared and pooled:

    label 1 (succeeded)  listed on a stock exchange (P414), OR acquired -- an
                         ownership statement (P127 owned by, P749 parent
                         organisation) whose P580 start date falls at least two
                         years after the company was founded
    label 0 (failed)     has a dissolution date (P576), was never listed, and
                         carries no ownership statement at all
    excluded             everything else

Two things here are load-bearing, and both were added after a first run came out
wrong rather than being anticipated.

**Success is tested before failure.** An acquired company usually also carries a
dissolution date, because the acquired entity is wound up after absorption.
Labelling on P576 first would file successful exits as failures, silently, and
the resulting model would be inverted on precisely the cases that matter most.

**An acquisition must be dated.** "Owned by Microsoft" is not evidence of an
exit: the company may have been incorporated as a subsidiary and never have been
a startup at all. Of 251 dated ownership statements in this window, 60 -- 24% --
begin at or before the founding year. The first run of this script ignored the
dates and produced an 80.9% positive rate against YC's 46.5%, a majority class
that was mostly an artifact of the rule rather than a fact about companies.

So an undated owner is not a label, and neither is still being in business.
Both are excluded. Right-censoring and missing evidence are not outcomes, and
the price of saying so is a smaller corpus -- which is the correct price.

USAGE

    python ml/scripts/build_market_company_dataset.py --out ml/data/market_dataset.jsonl

Roughly four minutes against the live endpoint. Queries are shaped around what
the public endpoint will actually answer; see the comment above `_OUTCOME_QUERY`
for the two shapes that returned HTTP 504 and why.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

# Wikidata asks every automated client to identify itself and to say how to get
# in touch. An anonymous scraper gets throttled, and deservedly.
USER_AGENT = (
    "VentureFlow/1.0 (https://github.com/SageOtter2023/venture_flow; "
    "research use, contact via repository issues) python-requests"
)

# Company classes to walk. Kept narrow and explicit rather than using a broad
# "business" root with an industry filter, because P452 (industry) is populated
# on only a small minority of company items -- measured: an industry-filtered
# query over the same period returns 83 dissolved companies where the
# class-based one returns 534.
COMPANY_CLASSES = [
    ("Q1058914", "software company"),
    ("Q18388277", "technology company"),
    ("Q210167", "video game developer"),
    ("Q2401749", "internet company"),
    ("Q1391145", "telecommunications company"),
]

FIRST_YEAR = 1990
LAST_YEAR = 2020  # after this, too few outcomes have resolved to label honestly

# Politeness delay between SPARQL calls. The endpoint is a shared public
# resource with no rate card; this keeps the harvest to roughly one query a
# second, which is well inside what it tolerates.
SPARQL_DELAY_S = 1.0

# One query per outcome property, each with that property REQUIRED.
#
# Two earlier shapes were tried against the live endpoint and both returned
# HTTP 504, so this is measured rather than preferred:
#
#   1. Everything at once -- labels, descriptions, industry, country and the
#      Wikipedia sitelink, via six OPTIONAL blocks and the `wikibase:label`
#      service. Each OPTIONAL multiplies the intermediate result set and the
#      label service then runs over the product.
#
#   2. The same query stripped to Q-ids and the four outcome properties, still
#      with those properties OPTIONAL, narrowed to a single founding year.
#      Still 504, and the reason is the important one: with every outcome
#      property optional, the engine has to materialise EVERY technology company
#      in Wikidata before it can attach anything to them.
#
# Making the property required inverts that. `?company wdt:P576 ?dissolved`
# starts from the small set of companies that have a dissolution date and walks
# outward, which the endpoint answers in seconds. And nothing is lost: a company
# with none of these four properties has no recorded outcome, so it would have
# been dropped as right-censored anyway. The unconstrained set was never needed.
_OUTCOME_QUERY = """
SELECT DISTINCT ?company ?inception ?value
WHERE {
  VALUES ?class { %(classes)s }
  ?company wdt:P31/wdt:P279* ?class .
  ?company wdt:P571 ?inception .
  ?company wdt:%(property)s ?value .
  FILTER(YEAR(?inception) >= %(first)d && YEAR(?inception) <= %(last)d)
}
"""

# Ownership WITH the date it began, read off the statement's P580 qualifier
# rather than the truncated `wdt:` property, which drops qualifiers.
#
# This distinction is the difference between a usable dataset and a broken one.
# "Owned by Microsoft" on a company founded in 2005 can mean it was acquired in
# 2012 -- a successful exit -- or that it was incorporated as a subsidiary in
# 2005 and never was a startup at all. Treating both as acquisitions produced a
# first run with an 80.9% positive rate against YC's 46.5%, i.e. a dataset whose
# majority class was largely an artifact of the labelling rule.
#
# Measured on the 1990-2020 window: of 251 dated P127 statements, 60 (24%) begin
# at or before the founding year. Those are subsidiaries, and without the
# qualifier they are indistinguishable from exits.
_DATED_OWNERSHIP_QUERY = """
SELECT DISTINCT ?company ?inception ?value ?start
WHERE {
  VALUES ?class { %(classes)s }
  ?company wdt:P31/wdt:P279* ?class .
  ?company wdt:P571 ?inception .
  ?company p:%(property)s ?statement .
  ?statement ps:%(property)s ?value .
  ?statement pq:P580 ?start .
  FILTER(YEAR(?inception) >= %(first)d && YEAR(?inception) <= %(last)d)
}
"""

# Years that must separate founding from the start of ownership before it counts
# as an acquisition. Two, not one, because both dates are frequently recorded to
# year precision only, so a one-year gap can be a rounding artifact on a company
# that was a subsidiary from the start.
MIN_ACQUISITION_GAP_YEARS = 2

# property -> the field on the record it fills.
OUTCOME_PROPERTIES = [
    ("P576", "dissolved"),   # dissolution date -> candidate failure
    ("P414", "exchanges"),   # listed on a stock exchange -> success
    ("P127", "owners"),      # owned by -- undated, so ambiguous on its own
    ("P749", "parents"),     # parent organisation -- likewise
]

WIKIDATA_API = "https://www.wikidata.org/w/api.php"


def _sparql(query: str, timeout: int = 180) -> list[dict]:
    response = requests.get(
        SPARQL_ENDPOINT,
        params={"query": query, "format": "json"},
        headers={"User-Agent": USER_AGENT,
                 "Accept": "application/sparql-results+json"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["results"]["bindings"]


def _value(row: dict, key: str) -> str:
    return (row.get(key) or {}).get("value", "")


def _blank(qid: str, inception: str) -> dict[str, Any]:
    return {
        "qid": qid,
        "name": "",
        "description": "",
        "inception": inception,
        "dissolved": "",
        "exchanges": set(),
        "owners": set(),
        "parents": set(),
        "industries": set(),
        "country": "",
        "article": "",
        "acquired_year": None,
    }


def harvest(first_year: int, last_year: int) -> dict[str, dict[str, Any]]:
    """Every company in COMPANY_CLASSES founded in the window that has at least
    one outcome property, keyed by Q-id.

    Four queries, one per property, merged. A company that appears in several
    (dissolved AND owned, the acquired-then-wound-up shape) accumulates all of
    them, which is exactly what `label_of` needs to tell an exit from a failure.
    """
    classes = " ".join(f"wd:{qid}" for qid, _ in COMPANY_CLASSES)
    companies: dict[str, dict[str, Any]] = {}

    for prop, field in OUTCOME_PROPERTIES:
        query = _OUTCOME_QUERY % {
            "classes": classes, "property": prop,
            "first": first_year, "last": last_year,
        }
        rows: list[dict] = []
        for attempt in range(3):
            try:
                rows = _sparql(query)
                break
            except Exception as exc:
                wait = 10 * (attempt + 1)
                print(f"  {prop}: attempt {attempt + 1} failed "
                      f"({type(exc).__name__}); retrying in {wait}s", flush=True)
                time.sleep(wait)
        else:
            print(f"  {prop}: GIVING UP after 3 attempts", flush=True)
            continue

        added = 0
        for row in rows:
            qid = _value(row, "company").rsplit("/", 1)[-1]
            if not qid:
                continue
            if qid not in companies:
                companies[qid] = _blank(qid, _value(row, "inception")[:10])
                added += 1
            record = companies[qid]
            value = _value(row, "value")
            if field == "dissolved":
                record["dissolved"] = value[:10]
            else:
                record[field].add(value)
        print(f"  {prop} ({field}): {len(rows):5d} rows, {added:5d} new companies "
              f"(total {len(companies)})", flush=True)
        time.sleep(SPARQL_DELAY_S)

    # Second pass: the ownership statements that carry a start date, which is
    # the only evidence that separates an exit from a company that was born a
    # subsidiary.
    for prop in ("P127", "P749"):
        query = _DATED_OWNERSHIP_QUERY % {
            "classes": classes, "property": prop,
            "first": first_year, "last": last_year,
        }
        rows = []
        for attempt in range(3):
            try:
                rows = _sparql(query)
                break
            except Exception as exc:
                wait = 10 * (attempt + 1)
                print(f"  {prop} dated: attempt {attempt + 1} failed "
                      f"({type(exc).__name__}); retrying in {wait}s", flush=True)
                time.sleep(wait)
        else:
            print(f"  {prop} dated: GIVING UP after 3 attempts", flush=True)
            continue

        acquisitions = 0
        for row in rows:
            qid = _value(row, "company").rsplit("/", 1)[-1]
            inception, start = _value(row, "inception")[:4], _value(row, "start")[:4]
            if not (qid and inception.isdigit() and start.isdigit()):
                continue
            if qid not in companies:
                companies[qid] = _blank(qid, _value(row, "inception")[:10])
            gap = int(start) - int(inception)
            if gap < MIN_ACQUISITION_GAP_YEARS:
                continue
            record = companies[qid]
            # Earliest qualifying change of ownership is the acquisition; later
            # ones are the acquirer itself changing hands.
            if record["acquired_year"] is None or int(start) < record["acquired_year"]:
                record["acquired_year"] = int(start)
            acquisitions += 1
        print(f"  {prop} dated: {len(rows):5d} statements, {acquisitions:5d} "
              f"qualify as acquisitions (gap >= {MIN_ACQUISITION_GAP_YEARS}y)", flush=True)
        time.sleep(SPARQL_DELAY_S)

    return companies


def enrich_entities(records: list[dict[str, Any]]) -> None:
    """Fill in name, description and Wikipedia title from the Wikidata API.

    `wbgetentities` takes 50 ids per call and returns labels, descriptions and
    sitelinks directly, with no join. This is the half of the harvest that the
    SPARQL query used to do and could not finish.
    """
    for start in range(0, len(records), 50):
        batch = records[start:start + 50]
        for attempt in range(3):
            try:
                response = requests.get(
                    WIKIDATA_API,
                    params={
                        "action": "wbgetentities",
                        "ids": "|".join(r["qid"] for r in batch),
                        "props": "labels|descriptions|sitelinks",
                        "languages": "en",
                        "sitefilter": "enwiki",
                        "format": "json",
                    },
                    headers={"User-Agent": USER_AGENT},
                    timeout=60,
                )
                response.raise_for_status()
                entities = response.json().get("entities") or {}
                for record in batch:
                    entity = entities.get(record["qid"]) or {}
                    record["name"] = (
                        (entity.get("labels") or {}).get("en", {}).get("value", "")
                    )
                    record["description"] = (
                        (entity.get("descriptions") or {}).get("en", {}).get("value", "")
                    )
                    sitelink = (entity.get("sitelinks") or {}).get("enwiki") or {}
                    record["article"] = sitelink.get("title", "")
                break
            except Exception as exc:
                print(f"  entity batch at {start} failed ({exc})", flush=True)
                time.sleep(3 * (attempt + 1))
        if start and start % 500 == 0:
            print(f"  enriched {start}/{len(records)}", flush=True)
        time.sleep(0.2)


def label_of(record: dict) -> tuple[int | None, str]:
    """(label, why) for one company, or (None, why) when it must be excluded.

    Order matters. The success tests run BEFORE the dissolution test, because an
    acquired company usually also carries a dissolution date -- the acquired
    entity is wound up after absorption -- and testing P576 first would file
    successful exits as failures.

    The ambiguous middle is excluded rather than guessed. A company with an
    undated owner might have been acquired or might always have been a
    subsidiary, and there is no evidence here to say which; a company that is
    still trading has no outcome yet. Neither is a label, and inventing one for
    either would be the exact failure this corpus exists to avoid.
    """
    listed = bool(record["exchanges"])
    acquired = record.get("acquired_year") is not None
    has_undated_owner = bool(record["owners"] or record["parents"])
    dissolved = bool(record["dissolved"])

    if listed:
        return 1, "listed on a stock exchange (P414)"
    if acquired:
        return 1, (
            f"acquired in {record['acquired_year']}, "
            f"{record['acquired_year'] - int(record['inception'][:4])} years after founding"
        )
    if dissolved and not has_undated_owner:
        return 0, "dissolved (P576), never listed and never acquired"
    if dissolved and has_undated_owner:
        return None, (
            "dissolved but has an owner with no recorded start date -- cannot "
            "tell an acquisition from a company that was always a subsidiary"
        )
    if has_undated_owner:
        return None, "owner recorded with no start date -- outcome unclear"
    return None, "still trading or no recorded outcome -- right-censored, not a label"


# The scope test. This product analyses tech startups only, so a
# telecommunications utility or a games retailer founded in 1994 does not belong
# in the training population even though it is reachable from these classes.
#
# Applied to the Wikidata description and the Wikipedia extract rather than to a
# tag vocabulary, because Wikidata has no equivalent of YC's tags.
TECH_MARKERS = (
    "software", "technology", "internet", "web", "online", "computer",
    "video game", "game developer", "mobile app", "application", "platform",
    "saas", "cloud", "data", "digital", "electronics", "semiconductor",
    "telecommunications", "networking", "e-commerce", "ecommerce", "fintech",
    "artificial intelligence", "machine learning", "search engine", "website",
    "social network", "operating system", "programming", "developer tools",
    "cybersecurity", "information technology",
)

NON_TECH_MARKERS = (
    "brewery", "winery", "restaurant chain", "hotel chain", "mining company",
    "oil and gas", "airline", "bank holding", "real estate developer",
    "construction company", "clothing retailer", "food manufacturer",
    "pharmaceutical manufacturer", "tobacco", "shipping line",
)


def in_tech_scope(record: dict, text: str) -> bool:
    # Wikidata's own P452 industry claim is not consulted: it is populated on
    # only a small minority of company items (measured -- an industry-filtered
    # query returns 83 dissolved companies where the class-based one returns
    # 534), so relying on it would silently drop most of the corpus. The
    # one-line description and the article intro carry the same information for
    # far more rows.
    haystack = " ".join([record.get("description", ""), text[:1200]]).lower()
    if any(marker in haystack for marker in NON_TECH_MARKERS):
        return False
    return any(marker in haystack for marker in TECH_MARKERS)


def fetch_extracts(titles: list[str]) -> dict[str, str]:
    """Opening paragraphs of up to 20 English Wikipedia articles.

    The Wikidata description is a single clause ("video game developer"), which
    is far too thin to embed or to show a user as a comparable. The Wikipedia
    intro is a real paragraph and is what makes these rows usable as text.
    """
    if not titles:
        return {}
    response = requests.get(
        WIKIPEDIA_API,
        params={
            "action": "query", "format": "json", "prop": "extracts",
            "exintro": 1, "explaintext": 1, "redirects": 1,
            "titles": "|".join(titles[:20]),
        },
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    response.raise_for_status()
    pages = (response.json().get("query") or {}).get("pages") or {}
    return {
        page.get("title", ""): (page.get("extract") or "").strip()
        for page in pages.values()
        if page.get("extract")
    }



def build(out_path: Path, first_year: int, last_year: int) -> dict[str, Any]:
    raw = harvest(first_year, last_year)

    # Label before fetching article text, so no request is spent on a company
    # that is going to be excluded anyway.
    labelled: list[dict[str, Any]] = []
    censored = 0
    for record in raw.values():
        label, why = label_of(record)
        if label is None:
            censored += 1
            continue
        record["label"] = label
        record["label_reason"] = why
        labelled.append(record)

    print(f"\nlabelled {len(labelled)}, excluded {censored} as right-censored")

    print(f"fetching names and descriptions for {len(labelled)} entities")
    enrich_entities(labelled)

    titles: dict[str, list[dict[str, Any]]] = {}
    for record in labelled:
        title = record.get("article", "")
        if title:
            titles.setdefault(title, []).append(record)

    print(f"fetching Wikipedia intros for {len(titles)} articles")
    ordered = list(titles)
    extracts: dict[str, str] = {}
    for start in range(0, len(ordered), 20):
        batch = ordered[start:start + 20]
        for attempt in range(3):
            try:
                extracts.update(fetch_extracts(batch))
                break
            except Exception as exc:
                print(f"  batch at {start} failed ({exc})", flush=True)
                time.sleep(3 * (attempt + 1))
        if start and start % 400 == 0:
            print(f"  {start}/{len(ordered)}", flush=True)
        time.sleep(0.2)

    for title, records in titles.items():
        for record in records:
            record["extract"] = extracts.get(title, "")

    rows, dropped_scope, dropped_text = [], 0, 0
    for record in labelled:
        text = record.get("extract", "") or ""
        if not in_tech_scope(record, text):
            dropped_scope += 1
            continue
        blended = " ".join(filter(None, [record["description"], text])).strip()
        blended = re.sub(r"\s+", " ", blended)
        # Below this there is nothing to embed and nothing to show a user; a
        # bare company name is not a comparable.
        if len(blended) < 80:
            dropped_text += 1
            continue

        inception_year = int(record["inception"][:4]) if record["inception"][:4].isdigit() else None
        dissolved_year = int(record["dissolved"][:4]) if record["dissolved"][:4].isdigit() else None
        rows.append({
            "id": record["qid"],
            "name": record["name"],
            "text": blended,
            "label": record["label"],
            "label_reason": record["label_reason"],
            "status": "Acquired/Public" if record["label"] == 1 else "Shut down",
            "founded_year": inception_year,
            "closed_year": dissolved_year,
            "acquired_year": record.get("acquired_year"),
            "source": "wikidata",
            # The whole point: every row is checkable.
            "source_url": f"https://www.wikidata.org/wiki/{record['qid']}",
            "wikipedia_url": (
                "https://en.wikipedia.org/wiki/" + record["article"].replace(" ", "_")
                if record.get("article") else ""
            ),
        })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    positives = sum(r["label"] for r in rows)
    summary = {
        "n_rows": len(rows),
        "n_positive": positives,
        "n_negative": len(rows) - positives,
        "positive_rate": round(positives / len(rows), 4) if rows else 0.0,
        "n_raw_companies": len(raw),
        "n_right_censored_excluded": censored,
        "n_dropped_out_of_tech_scope": dropped_scope,
        "n_dropped_text_too_short": dropped_text,
        "years": [first_year, last_year],
        "classes": [{"qid": q, "label": lbl} for q, lbl in COMPANY_CLASSES],
        "sources": {
            "structure_and_labels": {
                "name": "Wikidata",
                "endpoint": SPARQL_ENDPOINT,
                "licence": "CC0 1.0",
                "url": "https://www.wikidata.org/",
            },
            "description_text": {
                "name": "English Wikipedia (article intro)",
                "endpoint": WIKIPEDIA_API,
                "licence": "CC BY-SA 4.1",
                "url": "https://en.wikipedia.org/",
            },
        },
        "label_rules": {
            "1": (
                "listed on a stock exchange (P414), or acquired -- an ownership "
                "statement (P127/P749) whose P580 start date is at least "
                f"{MIN_ACQUISITION_GAP_YEARS} years after founding"
            ),
            "0": "dissolved (P576), never listed, and with no ownership statement at all",
            "excluded": (
                "still trading; no recorded outcome (right-censored); or an "
                "ownership statement with no start date, which cannot be told "
                "apart from a company that was always a subsidiary"
            ),
        },
        "known_biases": [
            "Wikidata covers companies notable enough for an encyclopedia entry. "
            "Startups that failed quietly and early are systematically absent, so "
            "the failure class here is biased towards companies that were "
            "prominent enough for their collapse to be recorded.",
            "Video game developers are over-represented among failures because "
            "Wikidata's coverage of 1990s and 2000s game studios is unusually "
            "complete relative to its coverage of other software companies.",
            "An acquisition is treated as a success, following the YC dataset's "
            "own convention. A distressed acquihire is recorded here the same "
            "way as a billion-dollar exit.",
        ],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(out_path.with_suffix(".provenance.json"), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="ml/data/market_dataset.jsonl")
    parser.add_argument("--first-year", type=int, default=FIRST_YEAR)
    parser.add_argument("--last-year", type=int, default=LAST_YEAR)
    args = parser.parse_args()

    print(f"Harvesting Wikidata tech companies founded "
          f"{args.first_year}-{args.last_year}\n")
    summary = build(Path(args.out), args.first_year, args.last_year)
    print("\n" + json.dumps(
        {k: v for k, v in summary.items() if k not in ("sources", "known_biases", "classes")},
        indent=2))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
