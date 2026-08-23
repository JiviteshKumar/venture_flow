"""Pull real 10-K / 8-K paragraphs from SEC EDGAR to seed the risk-detection
benchmark (`ml/eval/risk_benchmark.jsonl`).

Why a collector rather than writing the excerpts by hand: the whole point of
the risk benchmark is to measure the false-positive rate on *boilerplate*, and
boilerplate written from memory is not boilerplate -- it is a caricature of it,
usually cleaner and more obviously innocuous than the real thing. Real filing
prose is hedged, long, and full of risk vocabulary that means nothing
("adversely affect", "no assurance", "material"), which is precisely what makes
it a hard negative for a keyword detector. The genuine red flags are pulled the
same way so both halves come from the same register.

This script only *retrieves and slices* text. Every label in
`ml/eval/risk_benchmark.jsonl` was assigned by hand afterwards by reading the
excerpt -- nothing here infers a label, and a phrase appearing in the query
below is not treated as evidence of the answer.

    python ml/scripts/collect_risk_excerpts.py

Writes `ml/eval/risk_excerpts_raw.jsonl` (one candidate paragraph per line,
with the accession number and source URL so any excerpt can be traced back to
the filing it came from). Re-running is safe; the file is rewritten.

SEC requires a descriptive User-Agent with contact details and rate-limits to
10 requests/second; both are honoured below.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from html import unescape as html_unescape

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: E402,F401  (imported for side effect)

OUT_PATH = ROOT / "ml" / "eval" / "risk_excerpts_raw.jsonl"

# SEC's fair-access policy requires a real contact address here.
UA = "VentureFlow research (contact jiviteshkumar54@gmail.com)"
HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
FTS_URL = "https://efts.sec.gov/LATEST/search-index"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data"

# Two groups of search phrases. The `bucket` is a retrieval hint for the human
# labeller -- which pile to read the candidate in -- NOT a label. Several
# "boilerplate" queries deliberately target phrases a naive keyword detector
# fires on, because those are the hard negatives worth measuring.
QUERIES: list[tuple[str, str, str]] = [
    # (bucket, phrase, forms)
    ("red_flag", "substantial doubt about our ability to continue as a going concern", "10-K"),
    ("red_flag", "identified a material weakness in our internal control over financial reporting", "10-K"),
    ("red_flag", "received a subpoena from the Securities and Exchange Commission", "10-K"),
    ("red_flag", "restatement of our previously issued financial statements", "10-K"),
    ("red_flag", "one customer accounted for more than 50% of our revenue", "10-K"),
    ("red_flag", "we are not in compliance with the financial covenants", "10-K"),
    ("red_flag", "notified us of its intention to delist our common stock", "8-K"),
    ("red_flag", "resigned as Chief Financial Officer effective immediately", "8-K"),
    ("boilerplate", "this report contains forward-looking statements within the meaning", "10-K"),
    ("boilerplate", "we may require additional capital to support our growth", "10-K"),
    ("boilerplate", "revenue is recognized when control of the promised goods", "10-K"),
    ("boilerplate", "the preparation of financial statements in conformity with", "10-K"),
    ("boilerplate", "furnished pursuant to Item 2.02 of Form 8-K", "8-K"),
    ("boilerplate", "appointed to the board of directors effective", "8-K"),
    ("boilerplate", "our business could be adversely affected by general economic conditions", "10-K"),
    ("boilerplate", "we face intense competition in the markets in which we operate", "10-K"),
]

MIN_CHARS, MAX_CHARS = 320, 1400


def _get(url: str, **kwargs) -> requests.Response:
    """One GET, throttled well under SEC's 10 requests/second ceiling."""
    time.sleep(0.25)
    return requests.get(url, headers=HEADERS, timeout=45, **kwargs)


def search(phrase: str, forms: str, limit: int = 3) -> list[dict]:
    response = _get(FTS_URL, params={"q": f'"{phrase}"', "forms": forms})
    if response.status_code != 200:
        print(f"  search failed ({response.status_code}) for {phrase!r}")
        return []
    return response.json().get("hits", {}).get("hits", [])[:limit]


def document_url(hit: dict) -> str | None:
    """EDGAR full-text hit ids are '<accession-with-dashes>:<filename>'."""
    raw_id = hit.get("_id", "")
    if ":" not in raw_id:
        return None
    accession, filename = raw_id.split(":", 1)
    cik = (hit.get("_source", {}).get("ciks") or [None])[0]
    if not cik:
        return None
    return f"{ARCHIVE}/{int(cik)}/{accession.replace('-', '')}/{filename}"


def _to_text(html: str, _rounds: int = 3) -> str:
    """Flatten filing HTML to plain text, repeatedly.

    One BeautifulSoup pass is not enough on EDGAR. Many filings -- especially
    older ones and anything prepared by a low-end filing agent -- are HTML
    documents whose *text nodes* contain HTML-escaped markup, so a single
    get_text() yields a string still full of literal `<div style="...">` tags.
    Unescaping and re-parsing until the text stops changing gets the real prose
    out; without it every excerpt in the benchmark would be mostly CSS, which
    would make the boilerplate false-positive rate measure tag soup rather than
    filing language.
    """
    text = html
    for _ in range(_rounds):
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        flattened = html_unescape(soup.get_text("\n", strip=True))
        if flattened == text or "<" not in flattened:
            text = flattened
            break
        text = flattened
    # Non-breaking spaces are pervasive in filings and survive get_text().
    return text.replace("\xa0", " ")


def paragraphs_containing(html: str, phrase: str) -> list[str]:
    """Return whole paragraphs from the filing that contain `phrase`.

    Filings are deeply nested tables and spans, so paragraph structure is
    recovered from the flattened text rather than from tags: split on blank
    lines, then normalise internal whitespace. Excerpts outside
    MIN_CHARS..MAX_CHARS are dropped -- shorter ones are usually a heading or a
    table cell with no context to judge, longer ones bundle several distinct
    disclosures into one example and make a single risk label meaningless.
    """
    text = _to_text(html)
    needle = phrase.lower()
    found = []
    for block in re.split(r"\n{2,}", text):
        flat = re.sub(r"\s+", " ", block).strip()
        if needle in flat.lower() and MIN_CHARS <= len(flat) <= MAX_CHARS:
            found.append(flat)
    if found:
        return found
    # Fall back to a fixed window around the phrase when the filing has no
    # usable paragraph breaks at all (single-blob HTML is common in small-cap
    # filings prepared by low-end filing agents).
    flat = re.sub(r"\s+", " ", text)
    position = flat.lower().find(needle)
    if position == -1:
        return []
    start = max(0, position - 400)
    return [flat[start:position + 700].strip()]


def main() -> None:
    rows: list[dict] = []
    seen: set[str] = set()
    for bucket, phrase, forms in QUERIES:
        print(f"[{bucket}] {phrase!r} ({forms})")
        for hit in search(phrase, forms):
            url = document_url(hit)
            if not url:
                continue
            try:
                response = _get(url)
            except requests.RequestException as exc:
                print(f"  fetch failed: {exc}")
                continue
            if response.status_code != 200:
                print(f"  fetch {response.status_code}: {url}")
                continue
            source = hit.get("_source", {})
            for excerpt in paragraphs_containing(response.text, phrase)[:1]:
                fingerprint = excerpt[:120].lower()
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                rows.append({
                    "retrieval_bucket": bucket,
                    "query_phrase": phrase,
                    "form": forms,
                    "company": (source.get("display_names") or [""])[0],
                    "file_date": source.get("file_date", ""),
                    "url": url,
                    "text": excerpt,
                })
                print(f"  + {len(excerpt)} chars from {(source.get('display_names') or [''])[0][:50]}")

    OUT_PATH.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    print(f"\nWrote {len(rows)} candidate excerpts to {OUT_PATH}")


if __name__ == "__main__":
    main()
