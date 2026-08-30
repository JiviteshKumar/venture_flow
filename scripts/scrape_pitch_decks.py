"""Fetch real, public tech-startup pitch decks so the pipeline can be tested on
input it did not author.

Why this exists. Every deck this product has been evaluated on so far was
written for the purpose -- PetVoice AI, CarbonLoop, AgroPulse, ClaimFlow and the
rest of the register in ml/eval/. Synthetic decks are useful for testing
plumbing and useless for testing judgement, because the person who wrote the
deck also knew what the analyser should say about it. A real deck was written to
persuade an investor, contains claims its author wanted believed, and -- for the
famous ones -- has a publicly known outcome that the tool's verdict can be
checked against.

Selection is deliberately biased toward decks whose claims are *checkable*:
well-documented companies where an independent reader can establish whether the
tool's claim verification got the right answer. That is the only way to answer
"is this output actually true" rather than "is this output plausible".

Downloads only what the HTTP response actually says is a PDF, records the source
URL and SHA-256 of every file, and refuses to keep a file the project's own
extractor cannot read. Nothing about the deck is inferred here -- the tool is
supposed to do that.

    python scripts/scrape_pitch_decks.py --out ml/eval/decks
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: F401  (Windows cp1252 guard)
from document_extractor import extract_document

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Search terms, one per target company. Kept as searches rather than hardcoded
# URLs because deck mirrors rot constantly; a term that finds nothing is
# reported as "not found" rather than silently producing an empty corpus.
TARGETS = [
    ("Airbnb", "Airbnb 2008 original seed pitch deck pdf"),
    ("Uber", "Uber 2008 first pitch deck pdf UberCab"),
    ("Buffer", "Buffer seed round pitch deck pdf Joel Gascoigne"),
    ("Front", "Front app Series A pitch deck pdf"),
    ("Intercom", "Intercom first pitch deck pdf"),
    ("Dropbox", "Dropbox 2007 pitch deck pdf Houston"),
    ("LinkedIn", "LinkedIn Series B pitch deck 2004 pdf"),
    ("Mattermark", "Mattermark Series A pitch deck pdf"),
    ("Coinbase", "Coinbase seed pitch deck pdf 2012"),
    ("Mint", "Mint.com pitch deck pdf 2007 Aaron Patzer"),
    ("Square", "Square pitch deck pdf 2011 Jack Dorsey"),
    ("Foursquare", "Foursquare pitch deck pdf 2009"),
    ("Yelp", "Yelp pitch deck pdf series"),
    ("BuzzFeed", "BuzzFeed pitch deck pdf 2008"),
    ("WeWork", "WeWork pitch deck pdf series a"),
    ("Tinder", "Tinder pitch deck pdf original"),
    ("Shopify", "Shopify pitch deck pdf early"),
    ("Revolut", "Revolut pitch deck pdf seed"),
    ("Monzo", "Monzo pitch deck pdf seed round"),
    ("Wise", "TransferWise pitch deck pdf seed"),
    # Second, independent evaluation set. Added so the extraction fix could be
    # checked against decks it was not developed against -- a fix validated
    # only on the decks that exposed the bug tells you nothing about whether it
    # generalises or was fitted to them.
    ("Oscar Health", "Oscar Health 2014 pitch deck pdf Series"),
    ("Nutanix", "Nutanix pitch deck pdf 2011 series b"),
    ("Canva", "Canva Fusion Books pitch deck pdf Melanie Perkins"),
    ("Brex", "Brex Series C pitch deck pdf 2018"),
    ("Alan", "Alan health insurance France Series A pitch deck pdf"),
]

# Direct URLs, tried before search, for decks confirmed to be served as real
# text PDFs at these locations. Search is unreliable for this task -- DuckDuckGo
# rate-limits hard after a few queries and returns "No results found" for most
# of the list -- so the known-good URLs are recorded rather than rediscovered
# every run. Search remains as the fallback for everything not listed here.
DIRECT_URLS = {
    "Airbnb": ["https://media.genppt.com/pitch-decks/airbnb/airbnb-pitch-deck-2009.pdf"],
    "Uber": ["https://media.genppt.com/pitch-decks/uber/uber-pitch-deck-2008.pdf"],
    "Buffer": ["https://media.genppt.com/pitch-decks/buffer/buffer-pitch-deck-2011.pdf"],
    "Front": ["https://media.genppt.com/pitch-decks/front-series-a/"
              "front-series-a-pitch-deck-2016.pdf"],
    "Coinbase": ["https://media.genppt.com/pitch-decks/coinbase/coinbase-pitch-deck-2012.pdf"],
    "Mint": ["https://media.genppt.com/pitch-decks/mint/mint-pitch-deck-2007.pdf"],
    "Intercom": ["https://media.genppt.com/pitch-decks/intercom/intercom-pitch-deck-2011.pdf"],
    # Confirmed by HEAD request on 29 Aug 2026: 200, application/pdf, 10.8MB.
    "Brex": ["https://media.genppt.com/pitch-decks/brex/brex-pitch-deck-2018.pdf"],
}

# Decks that exist at a reachable URL but extract to ZERO characters, because
# the PDF is a sequence of slide images with no text layer. Recorded because the
# absence is a real product finding, not a scraping failure: VentureFlow has no
# OCR path, so a user uploading any of these gets an empty analysis. Confirmed
# individually against media.genppt.com on 27 Aug 2026.
KNOWN_IMAGE_ONLY = ("Dropbox", "LinkedIn", "YouTube", "Facebook", "WeWork", "BuzzFeed")

MIN_CHARS = 400  # below this the "deck" is a cover page or a failed extraction

# Phrases that mark a document as writing *about* pitch decks rather than being
# one. This check exists because the first run of this script produced a corpus
# that was 60% wrong: the file kept as "Uber" was a "Marketing Strategy
# Template" that quoted Uber fourteen times, "Buffer" was a Foundersuite guide
# titled "How to Build the Ultimate Pitch Deck", and "Front" was a blank
# template beginning "Hello founder!". All three passed the original acceptance
# test, which only asked whether text could be extracted.
#
# That is the same class of error the product itself keeps hitting -- a name
# match mistaken for an identity match -- and it would have been far more
# damaging here, because the whole point of the corpus is to be ground truth. A
# tool evaluated against mislabeled input produces measurements that mean
# nothing, and they would have looked entirely reasonable.
TEMPLATE_MARKERS = (
    "template", "how to build", "hello founder", "this guide", "ultimate pitch",
    "pitch deck guide", "best practices", "step-by-step", "worksheet",
    "fill in", "your company name", "lorem ipsum", "insert your",
    "greatest pitch decks", "examples of", "tips for",
)

# The second false positive, caught only by reading the text: the file kept as
# "Yelp" was a university investment club's *equity* pitch -- "Yelp - Investment
# Thesis / Agenda / Valuation / Variant Perception" -- arguing that someone
# should buy Yelp stock. It names Yelp 62 times, names it in the first line, and
# is not a template, so it passed all three original checks.
#
# It is exactly the wrong input for this corpus. A sell-side style thesis about
# a listed company is written *after* the facts are public and contains none of
# the forward-looking founder claims a diligence tool exists to test. Feeding it
# in would have measured the tool against a genre it never sees.
ANALYST_MARKERS = (
    "investment thesis", "variant perception", "price target", "valuation",
    "equity research", "buy rating", "discounted cash flow", "dcf",
    "comparable company analysis", "ev/ebitda", "share price", "ticker",
    "investment recommendation", "bull case", "bear case",
)


def looks_like_the_companys_own_deck(company: str, text: str) -> tuple[bool, str]:
    """Whether `text` is plausibly `company`'s own pitch deck.

    Three cheap tests, all of which a genuine deck passes and the observed
    false positives fail:

    1. The company is named at all, and named more than once.
    2. It is named EARLY. A real deck leads with its own identity; a guide or a
       listicle mentions the company somewhere in the middle as an example.
    3. The opening does not read like a template or a how-to.
    4. It is not third-party analysis written about the company.

    Deliberately conservative: a rejected real deck costs one missing row in the
    corpus, an accepted wrong one silently corrupts every number downstream.
    """
    lowered = " ".join(text.split()).lower()
    name = company.lower()
    if name not in lowered:
        return False, f"never mentions {company}"

    # 2. Not a template or a how-to, judged on the first 300 characters only.
    #    The window is deliberately narrow. A faithful reproduction of a real
    #    deck may carry a vendor watermark ("Template by PitchDeckCoach.com")
    #    on every slide, which is a property of the mirror rather than of the
    #    document -- Airbnb's genuine AirBed&Breakfast deck was rejected by a
    #    1200-character window for exactly that reason. A document that really
    #    is a template announces it in its title, inside 300 characters.
    opening = lowered[:300]
    for marker in TEMPLATE_MARKERS:
        if marker in opening:
            return False, f"opening reads like a template/guide ({marker!r})"

    # 3. Named more than once. This is what separates a deck from SEO spam: the
    #    third false positive kept as "Revolut" was a scraped-content PDF from a
    #    Weebly site whose first line was literally "Revolut pitch deck pdf This
    #    site is not available in your country", followed by 20,000 characters
    #    about two entirely unrelated founders. It named Revolut exactly ONCE,
    #    in that title line, so a first-mention test passed it. No real deck
    #    mentions its own company a single time.
    mentions = lowered.count(name)
    if mentions < 2:
        return False, f"names {company} only {mentions}x in {len(lowered):,} chars -- not its own deck"

    if name not in lowered[:1500]:
        position = lowered.find(name)
        return False, f"{company} first mentioned at char {position}, not in the opening"

    # 4. Not an outsider's analysis of the company. Two independent markers are
    #    required because a real deck may legitimately use one in passing
    #    ("valuation" appears on plenty of founder asks); a document using two
    #    or more is writing about the company rather than as it.
    hits = [marker for marker in ANALYST_MARKERS if marker in lowered]
    if len(hits) >= 2:
        return False, f"reads as third-party investment analysis ({', '.join(hits[:4])})"

    return True, "names itself in the opening, not a template, not third-party analysis"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")


def search_pdf_urls(query: str, max_results: int = 12) -> list[str]:
    """DuckDuckGo results that look like PDFs. Free, no API key, no Groq."""
    from ddgs import DDGS

    urls: list[str] = []
    try:
        with DDGS() as ddgs:
            for result in ddgs.text(query, max_results=max_results):
                href = result.get("href") or ""
                if href and href.lower().split("?")[0].endswith(".pdf"):
                    urls.append(href)
        # A second pass with an explicit filetype hint: DDG honours it
        # inconsistently, so it is a supplement rather than a replacement.
        with DDGS() as ddgs:
            for result in ddgs.text(query + " filetype:pdf", max_results=max_results):
                href = result.get("href") or ""
                if href and href not in urls:
                    urls.append(href)
    except Exception as exc:
        print(f"    search failed: {type(exc).__name__}: {exc}")
    return urls


def download_pdf(url: str, timeout: int = 30) -> bytes | None:
    """Return PDF bytes, or None. Trusts the magic number, not the URL.

    A URL ending in .pdf that serves an HTML interstitial is the normal case on
    deck-mirror sites, and feeding that HTML to the extractor produces a
    plausible-looking blob of navigation text. Checking `%PDF` is what stops a
    cookie banner from being analysed as a pitch deck.
    """
    try:
        response = requests.get(
            url, timeout=timeout, headers={"User-Agent": USER_AGENT}, allow_redirects=True
        )
    except Exception as exc:
        print(f"    download failed: {type(exc).__name__}")
        return None
    if response.status_code != 200:
        print(f"    HTTP {response.status_code}")
        return None
    data = response.content
    if not data.startswith(b"%PDF"):
        print(f"    not a PDF (starts with {data[:12]!r})")
        return None
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="ml/eval/decks")
    parser.add_argument("--max-per-company", type=int, default=3,
                        help="candidate URLs to try before giving up on a company")
    parser.add_argument("--limit", type=int, default=0, help="stop after N decks")
    parser.add_argument(
        "--only",
        default="",
        help=(
            "comma-separated company names to fetch, e.g. 'Brex,Alan'. Without "
            "this every target is attempted, which re-downloads a corpus that "
            "is already on disk and burns the search rate limit for nothing."
        ),
    )
    args = parser.parse_args()

    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    have = {entry["company"] for entry in manifest}

    only = {c.strip().lower() for c in args.only.split(",") if c.strip()}

    for company, query in TARGETS:
        if only and company.lower() not in only:
            continue
        if args.limit and len(manifest) >= args.limit:
            break
        if company in have:
            print(f"{company}: already have it, skipping")
            continue

        print(f"\n{company}: {query}")
        candidates = list(DIRECT_URLS.get(company, []))
        if candidates:
            print(f"  {len(candidates)} known-good URL(s)")
        else:
            candidates = search_pdf_urls(query)
            print(f"  {len(candidates)} candidate PDF URLs from search")

        for url in candidates[: args.max_per_company]:
            print(f"  trying {url[:100]}")
            data = download_pdf(url)
            if data is None:
                continue

            # The project's own extractor is the acceptance test. If the
            # pipeline cannot read it, it is not a usable deck for this corpus
            # no matter how real the PDF is.
            try:
                extracted = extract_document(f"{_slug(company)}.pdf", data)
            except Exception as exc:
                print(f"    extractor rejected it: {type(exc).__name__}: {exc}")
                continue
            text = extracted.get("text", "") or ""
            if len(text.strip()) < MIN_CHARS:
                print(f"    only {len(text.strip())} chars of text -- likely image-only slides, skipping")
                continue

            # Identity check. See looks_like_the_companys_own_deck: extraction
            # succeeding says nothing about WHOSE deck this is.
            is_own, why = looks_like_the_companys_own_deck(company, text)
            if not is_own:
                print(f"    REJECTED: {why}")
                continue
            print(f"    identity check passed: {why}")

            path = out_dir / f"{_slug(company)}.pdf"
            path.write_bytes(data)
            entry = {
                "company": company,
                "file": path.name,
                "source_url": url,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "extracted_chars": len(text.strip()),
                "pages": extracted.get("pages"),
                # Parsed from the source URL, which names the deck's vintage
                # ("uber-pitch-deck-2008.pdf"). Recorded because the verifier
                # needs to know what period a claim is about: judging a 2008
                # metric against 2026 evidence produced four confidently wrong
                # REFUTES verdicts before this existed.
                "deck_year": (re.search(r"(19[89]\d|20[0-3]\d)", url).group(1)
                              if re.search(r"(19[89]\d|20[0-3]\d)", url) else ""),
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                # Automated acceptance is a NAME-MATCH heuristic, and a name
                # match is not an identity match -- that is the failure this
                # script's own docstring describes, and it recurred: the file
                # kept as "Mint" passes every check here (says "Mint", says it
                # early, says it often, is not a template) and is a business
                # school's investment case study about Mint rather than Mint's
                # own raise deck. Nothing automatable distinguishes those two.
                #
                # So a fresh fetch is marked unconfirmed until a human reads it,
                # rather than inheriting the credibility of a check that cannot
                # establish what it would need to.
                "provenance_confirmed": False,
                "trusted_regression_corpus": False,
                "provenance_note": (
                    "Automated name-match acceptance only; not yet reviewed by a "
                    "human. Read the deck and confirm it is the company's own "
                    "fundraising deck -- not an analyst report, case study or "
                    "template -- before setting provenance_confirmed to true."
                ),
            }
            manifest.append(entry)
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            print(f"    KEPT: {len(data):,} bytes, {len(text.strip()):,} chars of text")
            break
        else:
            print(f"  {company}: no usable PDF found")

    print(f"\n{len(manifest)} decks in {out_dir}")
    for entry in manifest:
        print(f"  {entry['company']:<12} {entry['extracted_chars']:>7,} chars  {entry['source_url'][:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
