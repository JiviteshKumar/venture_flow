"""Build the adversarial slide-heading fixture from the real deck corpus.

Why a generator and not a hand-written fixture. The regression this guards
against is an extractor keyed to a fixed vocabulary of slide headings
("Problem", "Solution", "Team"). A fixture invented for the test would be
written by someone who already knows what the test is checking, and would
therefore contain exactly the headings the author thought to vary. Real decks
do not cooperate like that: the 2008 UberCab deck labels its solution slide
"1-Click Car Service", Coinbase never writes "Problem" once, and Intercom's
PDF loses its own ligatures so its headings arrive as "T probm" and "Lscape /
compers".

So the fixture is generated from `ml/eval/decks`, the corpus whose provenance
is recorded in `manifest.json` -- source URL, SHA-256, byte size and vintage
for every file. Each fixture entry carries that provenance with it, so the
test data is traceable to a real deck fetched from a named source and nothing
in it was authored for the test.

The PDFs themselves are deliberately not committed (see `.gitignore`); this
regenerates the fixture from them:

    python tests/fixtures/build_adversarial_headings.py

The committed JSON is what CI reads, so the suite runs without the corpus
present.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: F401,E402  (Windows cp1252 guard)
import pdf_extractor as pe  # noqa: E402

DECKS_DIR = ROOT / "ml" / "eval" / "decks"
OUT = Path(__file__).resolve().parent / "adversarial_headings.json"

# The five corpus decks with the least conventional heading vocabulary,
# measured rather than assumed: every one of Uber's 25 slide headings, all 12
# of Coinbase's, all 8 of Intercom's, 23 of Front's 24 and 15 of Mint's 16 are
# outside the standard Problem/Solution/Traction/Market/Team set. Airbnb and
# Buffer are excluded precisely because they DO use conventional headings --
# they cannot fail this test, so they cannot guard it.
ADVERSARIAL = ("Uber", "Intercom", "Coinbase", "Front", "Mint")

# The vocabulary a heading-keyed extractor would have been built around. Used
# only to record how far each deck departs from it -- never by the extractor.
STANDARD_HEADINGS = {
    "problem", "solution", "traction", "market", "team", "product",
    "financials", "the ask", "vision", "competition", "business model",
}


def main() -> int:
    manifest_path = DECKS_DIR / "manifest.json"
    if not manifest_path.exists():
        print(f"No corpus manifest at {manifest_path}.")
        print("Fetch the corpus first: python scripts/scrape_pitch_decks.py --out ml/eval/decks")
        return 1

    manifest = {m["company"]: m for m in json.loads(manifest_path.read_text())}
    entries = []

    for company in ADVERSARIAL:
        meta = manifest.get(company)
        if not meta:
            print(f"  SKIP {company}: not in manifest")
            continue
        pdf_path = DECKS_DIR / meta["file"]
        if not pdf_path.exists():
            print(f"  SKIP {company}: {pdf_path.name} not present")
            continue

        data = pdf_path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != meta["sha256"]:
            print(f"  SKIP {company}: sha256 does not match the manifest")
            continue

        pages = pe.extract_pages_from_pdf(data)
        slides = []
        for index, page in enumerate(pages, start=1):
            lines = [ln.strip() for ln in page.splitlines() if ln.strip()]
            if not lines:
                continue
            heading = lines[0]
            slides.append(
                {
                    "slide": index,
                    "heading": heading,
                    "heading_is_standard": heading.lower().strip() in STANDARD_HEADINGS,
                    "body_lines": lines[1:],
                }
            )

        nonstandard = sum(1 for s in slides if not s["heading_is_standard"])
        entries.append(
            {
                "company": company,
                "source_url": meta["source_url"],
                "sha256": meta["sha256"],
                "deck_year": meta.get("deck_year"),
                "fetched_at": meta.get("fetched_at"),
                # Carried through so nothing downstream mistakes a deck kept
                # for heading-robustness testing for a deck that is evidence
                # about the company. These fixtures exercise the PARSER; a
                # deck whose provenance is unconfirmed is still a real PDF
                # with real unconventional headings and is perfectly good for
                # that, but must never be cited as ground truth.
                "provenance_confirmed": meta.get("provenance_confirmed", False),
                "trusted_regression_corpus": meta.get("trusted_regression_corpus", False),
                "provenance_note": meta.get("provenance_note", ""),
                "slide_count": len(slides),
                "nonstandard_heading_count": nonstandard,
                "slides": slides,
            }
        )
        print(f"  {company}: {len(slides)} slides, {nonstandard} nonstandard headings")

    if not entries:
        print("No decks available; fixture not written.")
        return 1

    OUT.write_text(
        json.dumps(
            {
                "_README": (
                    "Generated by tests/fixtures/build_adversarial_headings.py from "
                    "the real pitch-deck corpus in ml/eval/decks. Every slide heading "
                    "and body line below is verbatim from a real deck fetched from the "
                    "recorded source_url, verified against the recorded sha256. "
                    "Nothing here was written for the test."
                ),
                "decks": entries,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {OUT} ({len(entries)} decks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
