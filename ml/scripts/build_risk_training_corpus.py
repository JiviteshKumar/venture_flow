"""Build an in-domain risk-detection training corpus from SEC EDGAR.

WHY A NEW CORPUS, AND WHY NOT MORE SENTIMENT DATA

The shipped Risk/Tone model (`ml/models/risk_tone_model.txt`) was trained on
15,376 financial-sentiment examples -- Financial PhraseBank (Malo et al., 2014)
and TFNS. It reaches **0.767 accuracy on its own held-out test set** and
**ranking AUC 0.333 on the actual task**, which is below chance: it ordered
genuine going-concern disclosures *below* risk-free boilerplate. It predicted
`neutral` on all 28 benchmark excerpts.

That gap is the whole argument for this file. It is not underfitting, not a
threshold that needs tuning, and not a shortage of sentiment data. It is a task
mismatch: "is this headline bullish or bearish" and "does this paragraph
disclose a material risk" are different problems over different text, exactly as
Loughran & McDonald (2011) argued when they showed general-purpose sentiment
lexicons misclassify financial disclosure language. Training on more
out-of-domain sentiment would move the first number and not the second.

So the training distribution has to become the target distribution: risk
disclosure prose from real filings.

METHOD: WEAK SUPERVISION, HONESTLY LABELLED

Hand-labelling thousands of filing paragraphs is not available here, so labels
come from *labelling functions* -- the retrieval phrase that surfaced each
paragraph (Ratner et al., "Data Programming", NeurIPS 2016). A paragraph
retrieved by "substantial doubt about our ability to continue as a going
concern" is a positive; one retrieved by "revenue is recognized when control of
the promised goods" is a negative.

This is a NOISY label and is recorded as one. `label_source` is `weak_phrase` on
every row, and the confusion it can cause is real: a boilerplate query can
surface a paragraph that also happens to disclose a genuine risk. That is
acceptable for training and unacceptable for evaluation, which is why:

**THE 28 HAND-LABELLED EXCERPTS ARE NEVER TRAINED ON.** They are the disjoint
eval set. This script excludes them three ways -- by normalised text hash, by
containment (an eval excerpt appearing inside a longer candidate), and by EDGAR
accession number, so a *different* paragraph from a document the benchmark
already used is dropped too. The last one matters most and is the easiest to
forget: two paragraphs from one 10-K are not independent samples.

The negative queries deliberately target the phrases a keyword detector fires
on -- safe-harbour statements, ASC 606 policies, generic competition and
macro-risk factors. Easy negatives would inflate every metric. The headline
number for a risk detector is its false-positive rate on hedged legal prose,
because filings are mostly hedged legal prose.

PROVENANCE

Every row carries its source URL, EDGAR accession, form type, filing date, the
phrase that retrieved it, and the retrieval timestamp. Nothing enters the corpus
without a traceable origin.

    python ml/scripts/build_risk_training_corpus.py --per-query 40
    python ml/scripts/build_risk_training_corpus.py --resume
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: E402,F401  (Windows cp1252 guard)

OUT_PATH = ROOT / "ml" / "data" / "risk_training_corpus.jsonl"
EVAL_PATH = ROOT / "ml" / "eval" / "risk_benchmark.jsonl"
PROVENANCE_PATH = ROOT / "ml" / "data" / "risk_training_corpus.provenance.json"

# SEC's fair-access policy requires a real contact address.
UA = "VentureFlow research (contact jiviteshkumar54@gmail.com)"
HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
FTS_URL = "https://efts.sec.gov/LATEST/search-index"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data"

MIN_CHARS, MAX_CHARS = 320, 1400

# Labelling functions. `label` is the weak supervision signal, not a judgement
# about any specific paragraph.
#
# Positives span the categories a diligence tool must catch: going concern,
# control failures, regulatory action, restatement, concentration, covenant
# breach, delisting, key-person loss, litigation, liquidity.
#
# Negatives are deliberately HARD. Every one is a phrase that a keyword detector
# matches or nearly matches, so the model has to learn the difference between
# disclosing a risk and discussing risk in the abstract. A corpus of easy
# negatives would produce a model that looks excellent and flags every filing.
QUERIES: list[tuple[int, str, str]] = [
    # ── positives ──────────────────────────────────────────────────────────
    (1, "substantial doubt about our ability to continue as a going concern", "10-K"),
    (1, "substantial doubt about the Company's ability to continue as a going concern", "10-Q"),
    (1, "identified a material weakness in our internal control over financial reporting", "10-K"),
    (1, "our disclosure controls and procedures were not effective", "10-K"),
    (1, "received a subpoena from the Securities and Exchange Commission", "10-K"),
    (1, "received a Wells Notice from the staff of the Securities and Exchange Commission", "8-K"),
    (1, "restatement of our previously issued financial statements", "10-K"),
    (1, "should no longer be relied upon", "8-K"),
    (1, "one customer accounted for more than 50% of our revenue", "10-K"),
    (1, "a single customer accounted for approximately", "10-K"),
    (1, "we are not in compliance with the financial covenants", "10-K"),
    (1, "an event of default under our credit agreement", "8-K"),
    (1, "notified us of its intention to delist our common stock", "8-K"),
    (1, "we do not currently satisfy the continued listing requirements", "8-K"),
    (1, "resigned as Chief Financial Officer effective immediately", "8-K"),
    (1, "terminated the employment of our Chief Executive Officer", "8-K"),
    (1, "we have incurred significant losses since inception and expect", "10-K"),
    (1, "our existing cash and cash equivalents will not be sufficient", "10-K"),
    (1, "we may be required to curtail or cease operations", "10-K"),
    (1, "a class action lawsuit was filed against us alleging", "10-K"),
    # ── hard negatives ─────────────────────────────────────────────────────
    (0, "this report contains forward-looking statements within the meaning", "10-K"),
    (0, "we may require additional capital to support our growth", "10-K"),
    (0, "revenue is recognized when control of the promised goods", "10-K"),
    (0, "the preparation of financial statements in conformity with", "10-K"),
    (0, "furnished pursuant to Item 2.02 of Form 8-K", "8-K"),
    (0, "appointed to the board of directors effective", "8-K"),
    (0, "our business could be adversely affected by general economic conditions", "10-K"),
    (0, "we face intense competition in the markets in which we operate", "10-K"),
    (0, "critical audit matter is a matter arising from the audit", "10-K"),
    (0, "we determine revenue recognition through the following steps", "10-K"),
    (0, "actual results could differ materially from those anticipated", "10-K"),
    (0, "the following discussion should be read in conjunction with", "10-K"),
    (0, "our management, with the participation of our Chief Executive Officer", "10-K"),
    (0, "we use estimates and assumptions that affect the reported amounts", "10-K"),
    (0, "leases are classified as operating or finance leases", "10-K"),
    (0, "declared a quarterly cash dividend of", "8-K"),
    (0, "entered into an underwriting agreement with", "8-K"),
    (0, "the fair value of our stock options is estimated using", "10-K"),
]


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _text_hash(text: str) -> str:
    return hashlib.sha256(_normalise(text).encode("utf-8")).hexdigest()


# Counted, not swallowed. The first full run collected 100 excerpts where ~950
# were expected, and the cause was INVISIBLE: every failed fetch hit a bare
# `continue`, so whatever went wrong was recorded as "these filings contain no
# risk language". That is the same defect -- infrastructure failure reported as
# a finding -- that this codebase has now hit in three separate places.
#
# Being precise about what is and is not established: the shortfall was fixed by
# halving the request rate (0.15s -> 0.3s) and adding backoff, after which the
# same command collected 941 excerpts. SEC throttling is the obvious
# explanation, but it is NOT confirmed -- the re-run recorded zero 403s, and it
# also ran slower, so the counters cannot retroactively diagnose the original
# failure. What they guarantee is that the next one will be visible rather than
# silent, which was the actual problem.
FETCH_STATS = {"ok": 0, "http_403": 0, "http_other": 0, "exception": 0, "retried": 0}


def _get(url: str, **kwargs) -> requests.Response:
    """One GET, throttled under SEC's 10 requests/second ceiling, with backoff.

    0.3s rather than 0.15s: the tighter interval sat close enough to the
    published ceiling that sustained collection tripped it, and a 403 costs far
    more than the extra 150ms.
    """
    for attempt in range(4):
        time.sleep(0.3 * (attempt + 1))
        try:
            response = requests.get(url, headers=HEADERS, timeout=45, **kwargs)
        except Exception:  # noqa: BLE001
            FETCH_STATS["exception"] += 1
            if attempt == 3:
                raise
            FETCH_STATS["retried"] += 1
            continue
        if response.status_code == 403:
            FETCH_STATS["http_403"] += 1
            if attempt < 3:
                FETCH_STATS["retried"] += 1
                time.sleep(2.0 * (attempt + 1))
                continue
        if response.status_code == 200:
            FETCH_STATS["ok"] += 1
        elif response.status_code != 403:
            FETCH_STATS["http_other"] += 1
        return response
    return response


def search(phrase: str, forms: str, limit: int, offset: int = 0) -> list[dict]:
    """EDGAR full-text hits, paginated.

    The API caps `from` at 9,900 and returns at most 10 hits per page, so
    scaling past a few dozen per phrase means paging rather than asking for a
    larger `size`.
    """
    hits: list[dict] = []
    while len(hits) < limit:
        response = _get(FTS_URL, params={
            "q": f'"{phrase}"', "forms": forms, "from": offset + len(hits),
        })
        if response.status_code != 200:
            print(f"    search HTTP {response.status_code} for {phrase[:50]!r}")
            break
        page = response.json().get("hits", {}).get("hits", [])
        if not page:
            break
        hits.extend(page)
    return hits[:limit]


def document_url(hit: dict) -> tuple[str, str] | None:
    """(url, accession) for a full-text hit, or None."""
    raw_id = hit.get("_id", "")
    if ":" not in raw_id:
        return None
    accession, filename = raw_id.split(":", 1)
    cik = (hit.get("_source", {}).get("ciks") or [None])[0]
    if not cik:
        return None
    return f"{ARCHIVE}/{int(cik)}/{accession.replace('-', '')}/{filename}", accession


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[\s ]+")


def _to_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "table"]):
        tag.decompose()
    return _WS_RE.sub(" ", soup.get_text(" ", strip=True))


def paragraphs_containing(text: str, phrase: str) -> list[str]:
    """Sentence-window excerpts around each occurrence of `phrase`."""
    lowered = text.lower()
    needle = phrase.lower()
    out: list[str] = []
    start = 0
    while True:
        index = lowered.find(needle, start)
        if index == -1:
            break
        start = index + len(needle)
        left = max(0, index - 500)
        right = min(len(text), index + 900)
        excerpt = text[left:right].strip()
        # Trim to sentence boundaries so an excerpt does not begin mid-word.
        first_stop = excerpt.find(". ")
        if 0 < first_stop < 200:
            excerpt = excerpt[first_stop + 2:]
        last_stop = excerpt.rfind(". ")
        if last_stop > MIN_CHARS:
            excerpt = excerpt[: last_stop + 1]
        if MIN_CHARS <= len(excerpt) <= MAX_CHARS:
            out.append(excerpt)
    return out


def load_eval_guards() -> tuple[set[str], set[str], list[str]]:
    """Hashes, accessions and normalised texts of the hand-labelled eval set.

    Three guards rather than one, because a single hash check is not enough:
    an eval excerpt may appear as a substring of a longer candidate, and a
    different paragraph from the same filing is not an independent sample.
    """
    hashes: set[str] = set()
    accessions: set[str] = set()
    texts: list[str] = []
    if not EVAL_PATH.exists():
        raise SystemExit(f"{EVAL_PATH} not found -- the disjoint eval set is required.")
    for line in EVAL_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        text = row.get("text", "")
        hashes.add(_text_hash(text))
        texts.append(_normalise(text))
        url = row.get("url") or ""
        found = re.search(r"(\d{10}-?\d{2}-?\d{6})", url)
        if found:
            accessions.add(found.group(1).replace("-", ""))
    return hashes, accessions, texts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-query", type=int, default=40,
                        help="EDGAR documents to pull per labelling phrase")
    parser.add_argument("--max-excerpts-per-doc", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    eval_hashes, eval_accessions, eval_texts = load_eval_guards()
    print(f"Disjoint eval guard: {len(eval_hashes)} excerpts, "
          f"{len(eval_accessions)} accessions excluded from training.")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    seen_hashes: set[str] = set()
    if args.resume and OUT_PATH.exists():
        for line in OUT_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows.append(row)
                seen_hashes.add(row["text_sha256"])
        print(f"Resuming from {len(rows)} existing excerpts.")

    dropped = {"eval_hash": 0, "eval_contained": 0, "eval_accession": 0, "duplicate": 0}

    for label, phrase, forms in QUERIES:
        kind = "positive" if label == 1 else "hard negative"
        print(f"\n[{kind}] {phrase[:70]!r} ({forms})")
        hits = search(phrase, forms, limit=args.per_query)
        print(f"  {len(hits)} hits")
        kept_here = 0

        for hit in hits:
            resolved = document_url(hit)
            if resolved is None:
                continue
            url, accession = resolved
            if accession.replace("-", "") in eval_accessions:
                dropped["eval_accession"] += 1
                continue

            try:
                response = _get(url)
                if response.status_code != 200:
                    continue
                text = _to_text(response.text)
            except Exception:  # noqa: BLE001
                continue

            source = hit.get("_source", {})
            for excerpt in paragraphs_containing(text, phrase)[: args.max_excerpts_per_doc]:
                digest = _text_hash(excerpt)
                if digest in eval_hashes:
                    dropped["eval_hash"] += 1
                    continue
                normalised = _normalise(excerpt)
                if any(t in normalised or normalised in t for t in eval_texts):
                    dropped["eval_contained"] += 1
                    continue
                if digest in seen_hashes:
                    dropped["duplicate"] += 1
                    continue
                seen_hashes.add(digest)
                rows.append({
                    "text": excerpt,
                    "label": label,
                    "label_source": "weak_phrase",
                    "retrieval_phrase": phrase,
                    "form": forms,
                    "accession": accession,
                    "cik": (source.get("ciks") or [None])[0],
                    "filing_date": source.get("file_date"),
                    "url": url,
                    "text_sha256": digest,
                    "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                })
                kept_here += 1

        print(f"  kept {kept_here} excerpt(s); corpus now {len(rows)}")
        with OUT_PATH.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    positives = sum(1 for r in rows if r["label"] == 1)
    provenance = {
        "source": "SEC EDGAR full-text search (efts.sec.gov) and EDGAR Archives",
        "source_kind": "primary regulatory filings, public domain",
        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": "weak supervision by retrieval phrase (Ratner et al., NeurIPS 2016)",
        "label_noise": "labels are the retrieval phrase's bucket, NOT human judgement",
        "n_excerpts": len(rows),
        "n_positive": positives,
        "n_negative": len(rows) - positives,
        "n_labelling_functions": len(QUERIES),
        "unique_filings": len({r["accession"] for r in rows}),
        "eval_disjointness": {
            "eval_set": str(EVAL_PATH.relative_to(ROOT)),
            "excluded_by_text_hash": dropped["eval_hash"],
            "excluded_by_containment": dropped["eval_contained"],
            "excluded_by_accession": dropped["eval_accession"],
            "duplicates_dropped": dropped["duplicate"],
        },
        "user_agent": UA,
        "fetch_stats": dict(FETCH_STATS),
    }
    PROVENANCE_PATH.write_text(json.dumps(provenance, indent=2), encoding="utf-8")

    print(f"\n{len(rows)} excerpts ({positives} positive, {len(rows) - positives} negative) "
          f"from {provenance['unique_filings']} filings")
    print(f"Dropped: {dropped}")
    print(f"Wrote {OUT_PATH} and {PROVENANCE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
