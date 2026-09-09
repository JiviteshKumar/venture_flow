# VentureFlow — What It Is, How It Works, What Was Trained

A from-scratch explanation of the whole system. Every number below is read from
a committed artifact in this repository, not from memory — the file that holds
each one is named so you can check it.

---

## 1. The problem

A venture investor receives far more pitch decks than they can read carefully.
The expensive part is not reading them; it is **checking them**. A deck asserts
a market size, a growth rate, a set of customers, a founding team. Verifying
any one of those means searching, reading sources, and forming a judgement.

VentureFlow automates the checking pass. You upload a deck; it extracts the
claims, checks them against live web sources, looks up the founders, scores the
company against a model trained on real startup outcomes, and writes an
investment memo — with every number traceable to either the deck or a cited
source.

**The design constraint that shapes everything else:** a tool that quietly
invents a number is worse than no tool, because a plausible fabrication is
indistinguishable from a finding. Most of the engineering effort here went into
making the system's own failures visible rather than into adding features.

---

## 2. The stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13, FastAPI, uvicorn |
| LLM | Groq — `openai/gpt-oss-120b` |
| Database | Neon (serverless Postgres) + pgvector |
| ML | LightGBM, scikit-learn, TF-IDF + SVD |
| Search | DuckDuckGo (`ddgs`) -> Wikipedia -> Brave -> Tavily, with failover |
| Parsing | pdfplumber, python-pptx, python-docx |
| Frontend | Vite + React + TypeScript, Tailwind, recharts, framer-motion |
| Hosting | Vercel (frontend), Neon (data) |

---

## 3. How an analysis actually runs

```
PDF/PPTX/DOCX upload
   │
   ├─ document_extractor      → raw text + per-page text
   │
   ├─ structured_extractor    → claims, founders, financials, metadata
   │     ├─ PRIMARY:  "llm_schema"     LLM + Pydantic-validated JSON schema
   │     └─ FALLBACK: "regex_fallback" pdf_extractor regexes
   │
   ├─ extraction_coverage     → what % of the deck reached a structured field
   │
   └─ run_due_diligence
         ├─ claim_verifier      web search → LLM adjudication per claim
         ├─ founder_research    finds founders when the deck names none
         ├─ founder_verifier    background check against public evidence
         ├─ risk_detector       + risk_disclosure model (trained)
         ├─ investment_agents   Bull / Bear / Market / Team specialists
         ├─ venturescore        the trained score  ← the headline number
         └─ memo synthesis      the written report
```

### The two extraction paths, and why it matters

The **primary** path asks the LLM for a fixed JSON schema and validates it with
Pydantic before anything downstream trusts it. It classifies by *content*, so a
deck whose solution slide is titled "1-Click Car Service" is read correctly.

The **fallback** is regex-based and materially worse — on the real 2008 UberCab
deck it finds 3 claims where the LLM path finds 14.

This distinction exists because of the defect that shaped the whole project. A
single line, `pace_for(len(prompt), 1200)`, referenced a variable named `prompt`
that did not exist. Every call raised `NameError`; a bare `except Exception`
caught it; extraction silently fell back to regex. **Every analysis for an
unknown number of weeks was produced by the worse path, and nothing anywhere
said so.** It was found by a human comparing a report against the original PDF
by hand.

So the fallback is now visible in four places at once — logs (at ERROR for a
code defect, WARNING for a provider outage), the return value, the report's
`extraction_provenance` field, and a red banner in the UI.

### Extraction coverage

`extraction_coverage.py` answers one question: **of the text we were given, how
much can be found again in the structured output?**

It exists because "we found nothing in this deck" and "there was nothing in
this deck to find" used to produce byte-identical output. The first is a
parsing bug; the second is an honest reading. The headline is *slide* coverage
— the share of content slides that contributed at least one line — because the
failure mode is whole slides going missing. The report names the slides that
contributed nothing, which you can check against the PDF in ten seconds.

Measured before/after on the real corpus: **mean coverage 20.8% → 69.6%, total
claims 14 → 92.**

---

## 4. The models

Six models were trained. **Four ship. Two were deliberately shelved**, and the
reasons are as informative as the results.

### 4.1 VentureFlow Score — the headline number

*`ml/models/venturescore_model.pkl` · trainer `ml/scripts/train_venturescore_model.py`*

**Dataset:** Y Combinator's public company directory.
🔗 **https://github.com/yc-oss/api** — a continuously-updated open mirror of the
YC directory. Snapshot committed at `ml/data/yc_companies_raw.json` (10.4 MB).
Prepared into `ml/data/venturescore_dataset.jsonl` by
`ml/scripts/prepare_venturescore_dataset.py`.

**Label:** a coarse *survived-or-exited* proxy — acquired/public/still-operating
= 1, dead = 0. **Not** a returns model. Companies younger than 3.5 years are
filtered out, because "Active" for a company founded last year carries no
outcome information.

**Method:** 12-model Random Forest ensemble, **isotonic calibration**, 22
numeric + 5 categorical features → 80 encoded columns.

**Trained on n = 1,298.**

| Metric | Value |
|---|---|
| CV ROC-AUC | **0.6772** (95% CI 0.6607–0.6932) |
| Expected Calibration Error | 0.0219 |
| Brier score | 0.2223 |
| Base rate | 0.4892 |

**Leakage control — the important part.** Three features were removed as
contaminated: `team_size`, `age_years`, `batch_year`. All three are recorded at
snapshot time, *years after* the outcome being predicted — `team_size` measures
growth that already happened and `age_years` encodes right-censoring. Keeping
them would have inflated the score.

**Verified out-of-sample** (`ml/eval/validation/out_of_sample_verified.json`):
261 companies with **zero name overlap** with training → **AUC 0.6356**
(CI 0.5617–0.7021).

An earlier reported figure of 0.668 was **in-sample and void** — the evaluation
sampled from the model's own training file. The correction is recorded rather
than quietly overwritten.

For comparison, the hand-written formula this replaced scores **AUC exactly
0.5** — not approximately; *exactly*, because it reads no company feature at
all, so every company gets the same score and every pair ties.

### 4.2 Outcome Model — a second opinion, additive only

*`ml/models/outcome_model_combined.txt` · trainer `ml/scripts/train_outcome_model.py`*

**Dataset:** same yc-oss source, prepared by
`ml/scripts/prepare_outcome_dataset.py` → `ml/data/outcome_dataset.jsonl`.

**Method:** LightGBM over TF-IDF + SVD text features combined with structured
fields.

**n = 1,560** (1,248 train / 312 test), 726 positive / 834 negative.

Five variants were trained and all five are recorded in
`ml/models/outcome_model_report.json`:

| Variant | ROC-AUC | Accuracy | Brier |
|---|---|---|---|
| text_only | 0.5721 | 0.5545 | 0.2589 |
| structured_only_with_hindsight | 0.7047 | 0.6506 | 0.2157 |
| combined_with_hindsight | 0.7039 | 0.6506 | 0.2277 |
| structured_only_deployable | 0.6613 | 0.6250 | 0.2250 |
| **combined_deployable (shipped)** | **0.6459** | **0.6378** | **0.2353** |

**The shipped model is deliberately not the best-scoring one.** The hindsight
variants reach 0.70 by using `team_size` and `age_years` — the same leaked
features excluded above. Dropping them **costs 0.058 AUC**, and that cost is
recorded in the artifact rather than hidden.

A previously-reported 0.9747 for this model was **void**: it was measured on
261 companies drawn from the model's own training file. All 261 were in
training.

### 4.3 Risk Disclosure Model — the strongest result

*`ml/models/risk_disclosure_model.pkl` · trainer `ml/scripts/train_risk_disclosure_model.py`*

**Dataset:** real SEC regulatory filings — 10-K, 10-Q and 8-K risk sections.
🔗 **https://efts.sec.gov/LATEST/search-index** (EDGAR full-text search)
🔗 **https://www.sec.gov/Archives/edgar/data** (document archives)
Public domain primary sources. Built by
`ml/scripts/build_risk_training_corpus.py`; provenance recorded in
`ml/data/risk_training_corpus.provenance.json`.

**941 excerpts drawn from 614 unique filings** — 464 positive, 477 negative.

**Method: weak supervision** (Ratner et al., *Data Programming*, NeurIPS 2016)
— **38 labelling functions**, where the label is the retrieval phrase's bucket
rather than human judgement. The provenance file states this plainly:
*"labels are the retrieval phrase's bucket, NOT human judgement."*

**Split: `GroupShuffleSplit` by EDGAR accession number**, so no single filing
spans the train/test boundary. Eval disjointness was enforced by text hash,
containment and accession — 141 duplicates dropped.

| Held-out, in-distribution | |
|---|---|
| Accuracy | **0.9664** |
| ROC-AUC | **0.9973** |

| Disjoint benchmark (n=28) | |
|---|---|
| Precision / Recall / F1 | 0.9286 / 0.8667 / 0.8966 |
| Ranking AUC | 0.9641 |
| Boilerplate false-positive rate | 0.0769 |

**And the honest caveat, which the artifact records itself:** ranking AUC is
**1.00 on SEC filings** but **0.778 on the pitch-deck register**, with deck
recall 0.667. The model is excellent at the thing it was trained on and
noticeably weaker on the thing it is actually used for. That gap is in the
report file, not buried.

### 4.4 Text embedder

*`ml/models/text_embedder.pkl`*

TF-IDF + SVD → 64-dimensional vectors, fit on the same 1,560-company set.
Powers pgvector similarity retrieval (`rag_engine.py`) and comparable-company
matching (`comparables.py`). TF-IDF rather than a sentence-transformer because
`huggingface.co` was blocked in the sandbox where it was built.

Returns `None` — never a zero vector — on failure, so a missing model degrades
to "vector search unavailable" rather than to silently-wrong neighbours.

### 4.5 Claim Model — trained, measured, **deliberately not shipped**

*`ml/models/claim_model.txt`*

**Dataset: SciFact** (Allen Institute for AI) — scientific claim/evidence
verification.
🔗 **https://github.com/allenai/scifact**
🔗 **https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz**
(loaded directly from the tarball, because `datasets` 5.x dropped support for
script-based Hub datasets)

**Method:** TF-IDF + SVD → multiclass LightGBM. **1,109 claim/evidence pairs**
(887 train / 222 test).

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| NOT_ENOUGH_INFO | 0.735 | 0.602 | 0.662 | 83 |
| **REFUTES** | **0.063** | **0.042** | **0.050** | 48 |
| SUPPORTS | 0.393 | 0.527 | 0.451 | 91 |
| **Accuracy** | | | **0.450** | 222 |

**Result: not usable, and that is a finding.** REFUTES — the single most
valuable class for due diligence, since it catches a false claim — is
essentially never detected. Claim/evidence entailment requires representing
negation and relation, which lexical TF-IDF overlap cannot do.

It is **not wired into the product**, because shipping it would make claim
verification worse than the LLM-based verifier it would replace. It stands as
empirical justification for the current design rather than as a failure.

### 4.6 Risk/Tone Model — trained, usable, **not wired in**

*`ml/models/risk_tone_model.txt`*

**Datasets:**
🔗 **https://huggingface.co/datasets/takala/financial_phrasebank** — Financial
PhraseBank (Malo et al.), sentiment-annotated financial sentences
🔗 **https://huggingface.co/datasets/zeroshot/twitter-financial-news-sentiment**
— TFNS

**15,376 examples**, 77% accuracy, macro-F1 0.62 (negative-class recall 0.31 is
the weak point).

Usable, but not connected: replacing the existing keyword risk detector needs
its own comparative evaluation, and doing that properly is separate work rather
than something to bundle in unmeasured.

---

## 5. Dataset summary

| Dataset | Direct link | Used by | Size |
|---|---|---|---|
| Y Combinator directory | https://github.com/yc-oss/api | VentureFlow Score, Outcome Model, text embedder | 1,560 companies |
| SEC EDGAR filings | https://efts.sec.gov/LATEST/search-index · https://www.sec.gov/Archives/edgar/data | Risk Disclosure Model | 941 excerpts / 614 filings |
| SciFact | https://github.com/allenai/scifact | Claim Model *(shelved)* | 1,109 pairs |
| Financial PhraseBank | https://huggingface.co/datasets/takala/financial_phrasebank | Risk/Tone Model *(shelved)* | part of 15,376 |
| TFNS | https://huggingface.co/datasets/zeroshot/twitter-financial-news-sentiment | Risk/Tone Model *(shelved)* | part of 15,376 |
| Real pitch decks | `ml/eval/decks/manifest.json` (source URL + SHA-256 per file) | Evaluation only — never training | 7 decks |

Every dataset is a **named, public, verifiable source**. Nothing was scraped
from an unattributed origin, and no training data was synthesised.

---

## 6. How the score is composed

The headline number is not a single model output:

```
model prior          (VentureFlow Score, trained on company characteristics)
   − evidence penalty (what THIS deck's verification actually established)
   = final score
```

The evidence penalty is a **transparent bounded formula**, not a second trained
layer, and the code says why: fitting one would need labelled data linking
claim-verification outcomes to eventual company outcomes, and no such dataset
exists. Inventing that relationship and calling it learned would be exactly the
thing this codebase refuses to do. Every term is shown as
`evidence_components` on every report.

---

## 7. The engineering principle

Nearly every notable decision here is the same decision: **make the difference
between "we don't know" and "we measured nothing" impossible to lose.**

- Extraction coverage separates a thin deck from a dropped one.
- `extraction_provenance` separates a good extraction from a degraded one.
- Founder research separates *search failed* from *searched and found nothing*
  from *not attempted* — three states, three colours in the UI. Only one is
  evidence about a company.
- Founder names must be **grammatically attributed** in a source, not merely
  present on the page — otherwise an aggregator profile turns a real person
  into a fabricated founder.
- Names merge only on exact match after punctuation normalisation, never on
  similarity: Alan's two genuine founders share a forename token, so any fuzzy
  threshold would collapse two real people.
- Formatters render absent values as `—`, never `0`.
- A corpus deck that turned out to be a business-school case study rather than
  the company's own raise deck is flagged `provenance_confirmed: false` rather
  than quietly used.

---

## 8. Known limits — stated plainly

1. **Image-only decks are now readable — from pictures, and it says so.**
   Decks whose every page is a slide image used to be refused outright. An
   offline OCR engine (RapidOCR / PP-OCRv4, shipped as ONNX weights inside its
   wheel — no API key, no per-page cost, no system binary) now reads them.
   Measured against decks that DO have a text layer, word recall runs
   0.94–1.00 at roughly 2 seconds a page; on Uber's deck OCR returns 7,938
   characters against the text layer's 5,390, because it also reads the words
   baked into charts.
   The residual limit is honesty, not capability: OCR misreads digits more
   often than words, so every such analysis is labelled `text_source: "ocr"`
   and the UI says the figures were read from a picture. A read that runs out
   of its time budget reports how many pages it managed.
2. **The scores are weak predictors.** AUC ~0.64–0.68 is meaningfully better
   than the 0.5 it replaced, and nowhere near good enough to decide an
   investment. It is a triage signal.
   Newly measured: a text-only model trained on YC scores 0.6273 AUC
   [0.5750, 0.6699] on 462 companies that never went through an accelerator,
   against 0.5852 in-population. So it does transfer outside YC — modestly,
   and now with a number rather than an assumption.
   See `ml/scripts/eval_cross_population.py`.
3. **The label is survival, not returns.** A company that survived as a small
   business scores the same as a unicorn.
4. **Comparables now cover two populations, not one.** 1,560 Y Combinator
   alumni plus 470 technology companies from Wikidata and Wikipedia that were
   never in an accelerator, every row carrying a Q-identifier a reader can
   open and check. Results are stratified rather than pooled, because pooling
   was measured and returned 24 of 25 rows from YC for reasons of writing
   style rather than business similarity.
   **That second corpus is deliberately not used for training.** Its own AUC
   looks excellent (0.84) and the number is an artifact: Wikidata catalogues
   1990s games studios and their closures unusually thoroughly, so "video
   game" appears in 81.5% of its failures against 40.1% of its successes, and
   article length alone separates the classes at 0.62 AUC because surviving
   companies accumulate longer articles. A model trained on it would tell a
   founder that games companies fail. `tests/test_market_dataset_not_trained_on.py`
   keeps it out of the training scripts.
5. **Groq free tier: 200,000 tokens/day — this is the binding constraint on
   the whole product.** A full deck analysis costs roughly 25,000–50,000
   tokens across about a dozen LLM calls, so the day's budget is four to eight
   analyses. The ceiling appears in NO response header (only tokens-per-minute
   and requests-per-day do); the only way to discover it is the 429 body.

   What running out looks like, because it is not obvious: every LLM-backed
   component falls back at once. Claims come back NOT_ENOUGH_INFO, the bull and
   bear agents return "insufficient evidence", founder research retrieves
   sources and never reads them, and the memo is a stub. The report still
   renders and still shows a score, so nothing looks broken — it is just empty.
   That is what produced a 35/100 for Uber's 2008 deck.

   Three things now make this legible rather than silent. Components that
   failed on a provider error are excluded from the score instead of being
   counted as unresolved evidence (`ml/evidence_fusion.extract_features`), so
   an outage no longer costs a company points. The first tokens-per-day 429
   trips a circuit breaker (`groq_client`) so the remaining components fail in
   milliseconds with an accurate reason instead of each spending six retries.
   And the report says which components did not run, in the words "this is a
   fact about this deployment, not about the company".
6. **Authentication is email and password, and deliberately minimal.** Sign-up
   and sign-in with an email address only — no phone number, no third-party
   identity provider. Passwords are hashed with scrypt from the standard
   library; sessions are opaque random tokens stored only as their SHA-256
   digest and compared in constant time, so a database read does not yield a
   usable session. Reports are owned by the account that created them. What is
   still missing is everything around the edges: no email verification, no
   password reset, no rate limit specific to failed sign-ins beyond the global
   one.
7. **Web search fails over across providers, and knows the difference between
   an empty web and a broken one.** DuckDuckGo first, then Wikipedia — both
   keyless, so the chain works on a fresh clone — with Brave and Tavily joining
   only when a key is set.

   Two defects here were found by reading the claim benchmark's errors rather
   than by testing, and both were silent:

   * `ddgs` raises an exception for a query with no hits, so an unfindable
     query was recorded as a *provider failure* and put DuckDuckGo in a
     120-second cooldown. One analysis issues roughly twenty-five searches and
     deck claims are elliptical enough that at least one is always unfindable,
     so the first such query sidelined the general-web provider for the rest of
     the analysis and every later claim was judged on Wikipedia alone.
   * An empty result from one provider ended the chain, on the reasoning that a
     provider which answers has answered. But DuckDuckGo returns an empty page
     when it soft-throttles, byte-identical to a genuine miss. Two benchmark
     claims — the IBM/Red Hat acquisition and WeWork's withdrawn IPO — retrieved
     zero sources and scored NOT_ENOUGH_INFO. Neither is obscure; Wikipedia
     answers both.

   Emptiness now has to be confirmed by two independent providers before it is
   believed, which costs one extra keyless lookup on a genuine miss and
   recovers the throttled case.
8. **Claim retrieval now searches for the second company in a claim.** Every
   query template anchored on the claim as a whole, which retrieves pages about
   whichever entity the claim leads with — so for a claim comparing two
   companies, half the evidence was never searched for. Four of the six
   benchmark errors were this shape, and in each the judge's reasoning was
   correct and useless: *"none of the provided sources give the date of Uber's
   initial public offering"*. One extra query per additional named entity, hard
   capped at two.

   Measured at the retrieval layer, which needs no tokens: 5 of the 6 failing
   claims now retrieve the specific fact the judge said was missing, and the two
   zero-source claims retrieve 11 and 12 sources. **Whether the verdicts flip is
   not yet measured** — that needs the judge, and the token budget was spent.
   `scripts/verify_when_quota_returns.py` runs it.
9. **Tech startups only, enforced.** A deck that is not a technology company
   is refused at both `/upload-pdf` and `/analyze`, with the evidence shown.
   The gate is deliberately reluctant — it blocks only on positive evidence
   that a company is something else and allows anything it cannot classify,
   because wrongly refusing a real tech startup is the worse error.

---

## 8b. End-to-end verification, and what it found

`scripts/e2e_deck_audit.py` drives real decks through the real HTTP path --
`/upload-pdf`, then `/analyze` with the payload `AppContext.tsx` builds, then
`/analyze/status`, then a re-read from `/reports/{id}` -- and reports each thing
the product promises as PRESENT, EMPTY or BROKEN. It exists because
`ml/scripts/run_real_deck_corpus.py` calls the agent directly and therefore
skips the endpoints, the response model, the job queue and persistence, which is
where most of this project's shipped defects have actually lived.

Three decks, run 9 September 2026. Uber ran with token budget available; Airbnb
and Buffer exhausted it partway (three full analyses is roughly one day's
200,000 tokens), and the interest of those two runs is that the degradation
machinery reported the outage instead of hiding it.

| | Uber | Airbnb | Buffer |
|---|---|---|---|
| extraction | llm_schema, 25 slides | llm_schema, 11 slides | regex_fallback (quota), 13 slides |
| score | 41.0, model | 53.0, model | 53.0, model |
| claims checked | 5 (1 supported) | 5 | 5, degraded |
| bull / bear | 6 / 5 signals | outage, stated | outage, stated |
| founders | researched, 11 sources, model unreachable | none named, research quota-blocked | 3 from the deck, verified |
| comparables | stratified corpus | 5 across both populations | 5 across both populations |

Five defects were found by running it, none of which any unit test had caught:

1. **`/analyze` returned 422 for `"stage": null`.** `sector`, `domain` and
   `github_url` are declared `str | None`; `stage`, `company_description`,
   `filing_text` and the extraction fields are `str` with a default, so they
   accepted an absent key and rejected an explicit null. The browser never hit
   it because `?? undefined` makes `JSON.stringify` drop the key; every other
   client hits it immediately. Null now means the same as absent.

2. **A signed-in user could not download their own report.**
   `GET /reports/{id}` scopes its lookup to the caller; `/reports/{id}/pdf` and
   `/reports/{id}/export/{fmt}` called `get_report(report_id)` with no user.
   Since `get_report` returns a row only when it is unowned or owned by the id
   given, passing nothing never leaked anything -- it hid every private report
   from its owner. Download PDF, Export Word and Export Markdown all returned
   404 on your own analysis. `tests/test_report_export_is_scoped.py` pins both
   directions, because the obvious fix for the 404 reintroduces an enumeration
   hole over sequential integer report ids.

3. **The comparables list offered filenames as companies.** A real Uber
   analysis returned exactly one similar company: `02 uber`, a row created by an
   earlier run before names were cleaned, matched back to "Uber" by trigram
   similarity on its own filename.

4. **The test suite was writing permanently into the production database.** Of
   81 rows in `companies`, 47 were not companies: 33 test fixtures
   (`ScopeTest <hex>`, `ListScope <hex>`, `Legacy <hex>`) and 14 upload
   filenames. Because `find_similar_companies` draws from any company with a
   report attached, every one was a live candidate to be shown to a real user.
   The tests now delete what they create, the read side filters what is left,
   and `scripts/clean_junk_companies.py` removed the backlog (81 -> 34
   companies, 138 -> 85 reports).

5. **`founder_discovery` reported a bare `{"attempted": false}`** when the deck
   named its own team -- indistinguishable, read alone, from the feature being
   broken or switched off. It now says why it was skipped and points at
   `founder_verification`, where the founders actually are.

The founder question specifically: research is enabled by default and does run.
On Uber it searched, retrieved 11 sources, and could not read them because the
model call failed under per-minute throttling -- reported as "This is a fact
about this deployment, not about the company." On Buffer the deck named Joel
Gascoigne, Leo Widrich and Hiten Shah, and all three were verified against
public sources with `origin: "deck"`.

---

## 9. Running it locally

Two terminals from the repo root:

```bash
.venv/Scripts/python.exe -m uvicorn api:app --reload --port 8000
```

```bash
npm run dev --prefix frontend
```

Open http://localhost:5173. API docs at http://localhost:8000/docs.

From scratch you need `pip install -r requirements.txt`, a `.env` with
`DATABASE_URL` (Neon) and `GROQ_API_KEY`, then
`python scripts/migrate_neon.py`, then `npm install --prefix frontend`.

**Do not create `frontend/.env` locally** — with no such file the frontend
calls `/api`, which `vite.config.ts` proxies to port 8000. The template
contains a deployment placeholder that breaks local dev.

Tests:

```bash
GROQ_MAX_RETRIES=0 .venv/Scripts/python.exe -m pytest tests/ -q -p no:randomly
```

A passing run is **406 tests**.

---

## 10. Where to read more

| Document | Contents |
|---|---|
| `ml/README.md` | Every model, in depth |
| `ml/research/README.md` | Research write-up, methodology, related work |
| `ml/research/EXPERIMENT_LOG.md` | What was tried, including what failed |
| `HANDOFF.md` | Backend architecture, env vars, known issues |
| `frontend/FRONTEND_HANDOFF.md` | Frontend design system, a11y, deployment |
| `FIELD_NOTES.md` | Full engineering log (113 KB) |
| `ml/eval/validation/` | Out-of-sample validation, locked splits |
