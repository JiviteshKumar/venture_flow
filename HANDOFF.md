# VentureFlow — Handoff

Written 29 Aug 2026, at the end of a correctness pass on the extraction
pipeline. This is what the next team needs to know that is not obvious from
reading the code.

`FIELD_NOTES.md` is the long-form engineering log and stays the source of
truth for history. This document is the short version: how extraction works,
what can be turned off, what is known to be broken or unverifiable, and what
not to undo.

---

## 1. The extraction pipeline

A deck arrives as a PDF/DOCX/PPTX upload, is converted to text, and then has
structured facts pulled out of it. Everything downstream — claim verification,
risk detection, the specialist agents, the score — consumes those structured
facts. **If extraction is wrong, nothing downstream can be right**, and that is
why this pass focused there.

```
upload -> document_extractor.extract_document  (text + per-page text)
       -> structured_extractor.extract_structured
            |
            +-- PRIMARY:  "llm_schema"      schema-validated LLM extraction
            +-- FALLBACK: "regex_fallback"  pdf_extractor regexes
            +-- EMPTY:    "empty"           no text at all
       -> extraction_coverage.compute        how much of the deck got mapped
       -> ventureflow_agent.run_due_diligence
```

### The two paths, and why the fallback matters

**`llm_schema` is the primary path.** It asks the model for a fixed JSON schema
and validates it with Pydantic before anything is allowed to trust it. It
classifies by *content*, so it handles a deck whose solution slide is titled
"1-Click Car Service" rather than "Solution".

**`regex_fallback` is materially worse.** It exists so a provider outage
degrades the product instead of breaking it. On the real 2008 UberCab deck the
two paths give 3 claims versus 14.

**The fallback firing should now be rare, and is always visible.** This is the
important part of this handoff.

The bug that motivated this entire pass was one line: `extract_structured`
called `pace_for(len(prompt), 1200)` where `prompt` did not exist. Every call
raised `NameError`; a bare `except Exception` caught it; extraction silently
fell back to regex. **Every analysis for an unknown length of time was produced
by the worse path, and nothing anywhere said so.** It was found by a human
comparing a report against the original PDF by hand.

So the fallback is now visible in four places at once:

| Where | What you see |
|---|---|
| Logs | `ERROR` with `BROKEN` for a code defect; `WARNING` for a provider outage. These are deliberately different — one needs a code change, one needs waiting. |
| Return value | `_method` and `_fallback_reason` on the extraction result. |
| Report | `report["extraction_provenance"]` with `is_fallback`, `method`, `fallback_reason` and a plain-English `warning`. |
| UI | A red "Degraded extraction" panel above the score on the Summary tab. |

Guarded by `tests/test_extraction_fallback_is_visible.py` (8 tests). Those tests
break the LLM path deliberately and assert the degradation is observable. They
were verified to *fail* when the original bare-except shape is restored — 3 of
8 fail — so they guard the property, not one typo.

### Extraction coverage

`extraction_coverage.py` answers one question: **of the text we were given, how
much can be found again in the structured output?**

It exists because "we found nothing in this deck" and "there was nothing in
this deck to find" used to produce byte-identical output — an empty claims
table and an `INSUFFICIENT DATA` verdict. Those are opposite situations. The
first is a parsing bug and the report is wrong; the second is an honest reading
and the report is right.

- **Headline number is slide coverage**: the share of content slides that put at
  least one line into a structured field. Slides are the unit because the
  failure mode is *whole slides contributing nothing*.
- Line coverage is reported as a secondary detail.
- The report names the slides that contributed nothing, which is checkable
  against the PDF in about ten seconds.
- Verdicts: `HIGH` >= 80%, `PARTIAL` >= 50%, `LOW` below that, `EMPTY` for no
  extractable text.

**Read a high number carefully on a short deck.** Coverage is a *coverage*
signal, never a *quality* signal. The Coinbase corpus deck holds 635 characters
across 12 slides and scores 100% — correctly, because nearly every line was
captured, but 6 of its 10 "claims" are slide headings. The metric now sets
`thin_text: true` and appends a caveat below 900 characters, but the general
rule stands: read the captured items, not just the percentage.

### Input Completeness is not extraction coverage

`data_quality` in the report is labelled **"Input Completeness"**. It measures
whether the analysis *inputs arrived* — description length, claim count,
whether revenue was supplied. It has never measured whether the deck was parsed
correctly.

It was previously labelled "Data Quality", and a report read
`HIGH data quality (100/100)` directly above a claims table holding a fraction
of the deck. The score was not wrong; its name was answering a different
question than the one it appeared to answer.

**The number itself is unchanged.** `data_quality.score` feeds
`_evidence_components`, so changing what it measures would move every
VentureFlow Score in the product. Only the label, the warnings and the adjacent
coverage context are new. Pinned by
`tests/test_founder_research_and_labels.py::test_the_quality_score_is_unchanged_by_the_coverage_rework`.

---

## 2. Founder research

When a deck names no team — most decks — `agents/founder_research.py` searches
public sources for who founded the company, then `agents/founder_verifier.py`
does the background check. The UI distinguishes deck-sourced from
research-sourced founders, because a name the founder put in writing and a name
this tool went and found are different grades of evidence.

### The grounding guard — do not weaken this

A model asked "who founded X" will answer from memory whether or not the search
returned anything, and a plausible wrong name then gets a full background check
written about it. Two mechanical guards, neither of which the model influences:

1. **Whole-name match.** The name must appear in the source as a maximal
   capitalised run, so a truncated name cannot ground itself inside a longer
   one ("Charles Samuelian" inside "Jean-Charles Samuelian-Werve").
2. **Grammatical attribution.** Founding must be attributed to the person in
   one of `_ATTRIBUTION_PATTERNS` (`founded by X`, `X, co-founder`,
   `X founded`). Mere presence on the page is not enough — aggregator profiles
   list founders, executives, investors and board members in identical markup,
   so presence-only grounding invents a *relationship* rather than a name.

A proximity window was tried first and is not sufficient: any window wide
enough for "founded in 2013 by ⟨name⟩" also swallows the next sentence.

Punctuation is normalised on both sides before matching, because it was
otherwise possible to *drop* a real founder over a hyphen.

### Duplicate name variants

Names are merged **only** when identical after punctuation normalisation —
"Jean-Charles Samuelian-Werve" and "Jean Charles Samuelian Werve" are one
string, so no judgement is exercised. Both spellings are kept on the merged
entry as `name_variants`.

Anything weaker is **flagged, never merged**, in `possible_same_person`. This is
deliberate and should stay that way: Alan's two genuine founders are Charles
Gorintin and Jean-Charles Samuelian-Werve, who share a forename token. Any
similarity threshold tuned to catch a spelling variant is also tuned to collapse
two real people, and silently losing a founder is far worse than showing a
visible duplicate.

### Three states that must stay distinct

Only one of these is evidence about the company. They render in three different
colours in the Founder Analysis tab, on purpose:

| State | Meaning |
|---|---|
| `searched: false, search_failed: true` | Every query errored. **Nothing was established.** Not evidence. |
| `searched: false` (no `search_failed`) | Research disabled by env var. Not attempted. |
| `searched: true, found: false` | We looked and found nothing. *This* is a finding. |

### Cost and latency — read this before shipping to more users

Measured on this account, for a deck with **no** team slide:

| Stage | Wall clock | Web searches | Page fetches | LLM calls |
|---|---|---|---|---|
| Discovery | 22–38 s | 4–6 | up to 6 | 1 |
| Verification (3 founders) | ~77 s | 9 | 0 | 3 |
| **Total added** | **~100–115 s** | **~15** | **~6** | **~4** |

A deck that already names its founders skips discovery entirely and pays only
the verification cost.

**This is inline in the analysis request.** For the current usage pattern —
a human uploading one deck and waiting minutes for a report anyway — that is
acceptable. It will not stay acceptable under batch or concurrent load:
there is **no caching and no rate limiting** on founder search, so N decks for
the same company do N identical searches. If this product starts processing
decks in bulk, cache discovery by company name before anything else.

DuckDuckGo also rate-limits this hard. Sustained use produces
`DDGSException: No results found` or `ConnectTimeout`, which now correctly
reports as *search failed*, not as *no founders found*.

---

## 3. Environment variables and kill switches

| Variable | Default | What it does |
|---|---|---|
| `GROQ_API_KEY` | — | Required. Without it the SDK builds an illegal auth header and the failure is reported as "provider unreachable", which historically sent someone hunting the wrong bug. |
| `DATABASE_URL` | — | Neon Postgres. All persistence. |
| `VENTUREFLOW_FOUNDER_RESEARCH` | `on` | `off` disables founder web search. Returns an explicit *"not attempted"* — never confusable with "searched, found nothing". Use for offline/air-gapped runs, or to cut ~100 s and ~15 web requests per deck. **The test suite sets this off via `tests/conftest.py`**; without it, every full-pipeline test acquires a live network dependency and the suite hangs. |
| `GROQ_MAX_RETRIES` | `6` | The SDK honours `Retry-After`, which after a daily-quota 429 can be **26 minutes**. Set to `0` when running tests, or a hung suite is indistinguishable from a slow one. |
| `GROQ_TIMEOUT_S` | `90` | Per-request timeout. |
| `GROQ_TOKENS_PER_MINUTE` | `8000` | Free-tier ceiling the pacer targets. |
| `GROQ_PACING` | `on` | `off` disables the token pacer. Only safe on a paid tier with real headroom. |
| `GROQ_AGENT_CONCURRENCY` | see code | Specialist agent parallelism. |
| `ALLOWED_ORIGINS` | — | CORS. List both `localhost` and `127.0.0.1`; a browser treats them as different origins and Vite serves on both. |
| `RATE_LIMIT_PER_MINUTE` | — | API rate limit. |
| `REDIS_URL` | unset | Optional; in-memory limiting without it. |
| `GITHUB_TOKEN` | unset | Optional; technical scoring. |
| `SENTRY_DSN` | unset | Optional; structured JSON logs without it. |
| `DEMO_ACCESS_TOKEN` | unset | Demo gate. `tests/conftest.py` asserts it is not left set — a leak 401s every API test after it. |

### The Groq quota, which will bite you

The free tier has a **200,000 tokens/day** ceiling that **appears in no
response header**. The headers expose only per-minute tokens and per-day
*requests*. A capacity check that reads headers will report ample headroom that
does not exist; the ceiling is discoverable only by hitting it, as a 429 naming
`tokens per day (TPD)`.

A full deck analysis costs roughly 24,000–50,000 tokens, so **the daily budget
is four to eight decks**. Plan evaluation passes accordingly, and expect a
multi-deck run to fall back to regex partway through if you do not.

---

## 4. Known limitations

Stated plainly, because each of these will otherwise look like a bug you have
introduced.

### Image-only PDFs need OCR, which does not exist here

**8 of 13 well-known decks tested extract to exactly zero characters.** Every
page is a slide image with no text layer. Confirmed image-only: Dropbox (2007),
LinkedIn (2004), YouTube (2005), Facebook (2004), WeWork, BuzzFeed, **Brex
(2018, 18 pages)** and **Alan (Series A, 42 pages)**.

These are valid, human-legible PDFs. VentureFlow now HAS an OCR path
(`ocr_extractor.py`, offline RapidOCR), so these decks are readable; the
note below describes the state before it existed. Nothing
can be analysed from them. The upload endpoint returns a 422 that names the
cause rather than saying "could not extract readable text", because the two
need different actions from the user. `agents/slide_vision.py` is the
integration point if OCR is ever added. **Out of scope for this pass.**

### Three Set-2 decks are confirmed unobtainable

As of 29 Aug 2026, real decks for **Oscar Health, Nutanix and Canva/Fusion
Books** could not be obtained. This is an evidenced negative, not a timeout:
search returned 12 candidates for Oscar Health and the corpus validator
rejected every one (a generic healthcare template, a blank `Pitch_Deck.pdf`, a
WeWork deck). Nutanix and Canva return no results at all. Given Brex's and
Alan's real decks both proved image-only, the likely outcome even on success is
another image-only PDF.

Founder *research* for all of these works and is verified — it needs only the
company name, not the deck.

### Mint is in the corpus but is not Mint's deck

`ml/eval/decks/Mint.pdf` is flagged `provenance_confirmed: false` and
`trusted_regression_corpus: false` in `manifest.json`. It is almost certainly a
business-school investment case study:

- Slide 1 is four personal names and a date, not a company title.
- It contains *Exit Strategy*, *Exit Calculation*, *Competitive Response* and
  *Financial Assumptions* slides. A founder pitching does not compute their own
  exit.
- The body refers to the company in the third person ("Mint's Comp.
  Advantages").
- Aaron Patzer, who founded Mint, is not named anywhere in it.

It is retained **only** for heading-robustness testing, where it is valid input
— a real PDF with real unconventional headings, and the parser has no opinion
about who wrote it. **Do not cite it as evidence about Mint.** A replacement was
searched for and not found.

This is the same failure the scraper's own docstring warns about — a name match
mistaken for an identity match — and it survived the automated check because
nothing automatable distinguishes "a deck about X" from "X's deck". New fetches
are therefore written as `provenance_confirmed: false` until a human reads them.

### Smaller things

- **Intercom's PDF loses its own ligatures.** Headings extract as `"T probm"`,
  `"Lscape / compers"`. A font-encoding fault in `pdf_extractor.extract_page_text`.
  It still reached 75% coverage, so it has not been chased.
- **DuckDuckGo is the only search backend** and rate-limits aggressively. There
  is no API key and no paid fallback.
- **`market_data.py`'s Crunchbase and PitchBook providers are documented
  stubs**, gated behind unset API keys. They are inert by design, not
  half-finished.
- **Founder search results vary between runs.** DuckDuckGo returns different
  result sets for the same query minutes apart, so the founder list for a given
  company is not perfectly reproducible.

---

## 5. Running the eval suite

### Tests

```bash
GROQ_MAX_RETRIES=0 python -m pytest tests/ -q -p no:randomly
```

`GROQ_MAX_RETRIES=0` matters: with the daily quota spent, the SDK honours
`Retry-After` values up to 26 minutes and the suite appears to hang.

**A passing run is 406 tests, 0 failures, roughly 5 minutes.** Do not run
`pytest` from the repo root without a path — `legacy/supabase_ingestion/`
breaks collection and is quarantined on purpose.

Frontend:

```bash
cd frontend && npx tsc --noEmit -p tsconfig.json
```

Clean exit, no output.

### Deck corpus evaluation

```bash
python scripts/run_section_d.py --only "Uber,Intercom" --out ml/eval/section_d_set1.json
```

Runs the current extraction against the pre-fix extractors checked out of git,
so the before/after comparison is between two executables rather than between
an executable and a claim about one.

**What a good run looks like** (7 real corpus decks, all on `llm_schema`):

| Deck | Claims before → after | Coverage before → after |
|---|---|---|
| Coinbase | 0 → 10 | 0.0% → 100.0% |
| Intercom | 1 → 14 | 12.5% → 75.0% |
| Buffer | 3 → 14 | 66.7% → 75.0% |
| Airbnb | 2 → 13 | 18.2% → 72.7% |
| Front | 4 → 14 | 21.7% → 60.9% |
| Mint | 1 → 13 | 6.2% → 56.2% |
| Uber | 3 → 14 | 20.0% → 52.0% |

Aggregate: **claims 14 → 92, mean coverage 20.8% → 69.6%**.

**How to recognise a regression.** Any of these means something broke:

- `"method": "regex_fallback"` in a record when the quota is healthy — the
  primary path is failing, and `fallback_reason` says why.
- Mean coverage dropping below ~55%, or any deck falling back to its
  pre-fix number (Uber at 20%, Intercom at 12.5%).
- Total claims dropping toward 14.
- `tests/test_adversarial_headings.py` failing — extraction has reacquired a
  heading-vocabulary dependency. Verified to catch this: reintroducing the old
  closed verb list fails 10 of its 30 tests.

Regenerate the heading fixture after a corpus refresh:

```bash
python tests/fixtures/build_adversarial_headings.py
```

---

## 6. Known issues, not fixed

Found during the acceptance pass and deliberately left alone, either because
they were out of scope or because fixing them blind at handoff time is worse
than documenting them.

| # | Issue | Where | Why not fixed |
|---|---|---|---|
| 1 | **No caching or rate limiting on founder search.** N decks for the same company do N identical searches, ~15 web requests each. | `agents/founder_research.py` | Needs a cache keyed by company + a decision about TTL. Fine at current single-user volume; the first thing to fix before bulk processing. |
| 2 | **`founder_verifier._judge` `max_tokens` raised 400 → 1200 as a precaution.** The sibling call demonstrably overflowed at 400; this one was never *observed* to. | `agents/founder_verifier.py` | Raising it is safe and cheap, but the failures seen in testing were 429s, so the overflow here is unconfirmed. Flagged rather than claimed as a fix. |
| 3 | **Intercom's PDF loses its own ligatures** — headings extract as `"T probm"`, `"Lscape / compers"`. | `pdf_extractor.extract_page_text` | A font-encoding fault. The deck still reached 75% coverage, so the cost is low and the fix is a rabbit hole in pdfplumber's character mapping. |
| 4 | **Founder discovery is not reproducible run to run.** DuckDuckGo returns different result sets for the same query minutes apart, so the founder list for a company can differ between analyses. | search backend | Inherent to having one free, unkeyed search provider. Mitigated by every founder carrying its own cited sources. |
| 5 | **The "FOUND BY SEARCH" founder badge is verified in data but not visually.** | `frontend/src/pages/Analysis.tsx` | The daily Groq quota was exhausted before a live report with research-sourced founders could be produced. The sibling badge ("FROM DECK") renders correctly from the same conditional in the same component, and the backend is confirmed to emit `origin: "external_research"`. **Re-check this in the UI when quota resets.** |
| 6 | **Coverage counts a captured slide heading as coverage.** On a heading-dominated deck this inflates the percentage. | `extraction_coverage.py` | Mitigated with a `thin_text` caveat below 900 characters rather than fixed, because distinguishing a heading from a one-line assertion is the same judgement the extractor is already making. |
| 7 | **`legacy/supabase_ingestion/` breaks pytest collection** at the repo root. | `legacy/` | Quarantined on purpose and not wired into the app. Always run `pytest tests/`. |

## 7. What NOT to do

1. **Do not re-enable a scoring bypass.** The numeric score, the model prior and
   the base-rate comparison were explicitly out of scope for this pass and are
   unchanged. `data_quality.score` feeds `_evidence_components`; changing what
   it measures moves every score in the product.

2. **Do not weaken the grounding guard's grammatical-attribution requirement.**
   Dropping back to "the name appears somewhere in the source" reintroduces
   invented *relationships* — a real person attached to a claim no source made,
   which is harder to spot than a hallucinated name and just as wrong.

3. **Do not remove the fallback-visibility logging or
   `extraction_provenance`.** A silent regex fallback is the original defect.
   The `ERROR`-vs-`WARNING` split matters too: a `NameError` in the extractor
   and a 429 from Groq need completely different responses and must not be
   reported identically.

4. **Do not merge founder names on a similarity threshold.** Exact match after
   punctuation normalisation only; flag anything weaker. See §2.

5. **Do not turn `tests/conftest.py`'s `disable_founder_research` fixture off.**
   Without it the suite makes live web requests and hangs.

6. **Do not treat a deck as ground truth without checking
   `provenance_confirmed`.** A name match is not an identity match.

7. **Do not add company-specific special cases.** Nothing in the analysis
   pipeline branches on a company or founder name, and an AST sweep of runtime
   string literals confirms it. The corpus fetcher names companies because
   downloading named decks is its entire job; that is the only place they
   appear.
