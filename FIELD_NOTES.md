# Field notes — 22 Aug 2026 session

What changed in this pass, and why. Read this before the next session picks up
where this one left off.

## Update — 23 Aug 2026, tenth pass: the evaluation gap, closed with numbers

The audit's top finding was that this project had an evaluation *framework* and
no evaluation. `ml/scripts/eval_claim_verifier.py` had existed since the third
pass and had **never once been run end to end** — there was no results file
anywhere in the repository. Risk detection had no benchmark at all. Everything
below exists to fix that, plus the two report tabs that produced nothing.

### The claim benchmark, run for the first time, then expanded

Ran the existing 30 examples as-is first, so there is a "before" on record:
**93.3% accuracy** (`ml/eval/claim_benchmark_results_v1_30.json`). One harness
change was needed to make it run at all on Windows — it does not import
`console_safety`, so the LLM's typographic characters would have killed it
partway through with `UnicodeEncodeError`.

Then expanded to **150 hand-labeled claims**, 50/50/50, adding the sub-category
the old set explicitly lacked: **real but obscure Y Combinator companies paired
with publicly undocumented metrics** — Siasto, Picwing, Zumo Labs, Roost,
Talentdrop. A search finds the company and not the claim, which is exactly the
judgement an early-stage diligence tool makes on every real deck. The
invented-company examples cannot test that, because there the answer is
available from the absence of any result at all.

**134 of 150 scored** across two sessions; the free tier's daily token cap
stopped it both times. The results are real and the run resumes:

| | Precision | Recall | F1 | n |
|---|---|---|---|---|
| SUPPORTS | 1.000 | 0.905 | 0.950 | 42 |
| REFUTES | 1.000 | 0.952 | 0.976 | 42 |
| NOT_ENOUGH_INFO | 0.893 | 1.000 | 0.943 | 50 |

Accuracy **0.955**. By subset: public facts 0.929, invented companies 1.000,
obscure real companies 1.000. Both SUPPORTS and REFUTES precision are 1.000 —
**the verifier under-claims rather than over-claims**, which for a diligence
tool is the safe direction. It shows up in the four errors where it refused to
affirm a conjunction the retrieved evidence only half-covered (Tesla *produced*
its millionth vehicle in March 2020; it would not affirm *delivered*).

**The metrics have converged.** Going from 126 to 134 examples moved accuracy
+0.003 and every per-class F1 by ≤ +0.004; all eight new claims were classified
correctly, so the error set is unchanged at exactly six (four SUPPORTS and two
REFUTES read down to NOT_ENOUGH_INFO). That matters because the 30 → 126 step
had *overturned* a conclusion, so the obvious worry was that 150 would overturn
another. It is not doing so — the numbers are moving in the fourth decimal
place, not changing sign.

### The benchmark caught two of my own labels, one of them badly

`r25` — "SpaceX is a publicly traded company listed on Nasdaq" — was labeled
REFUTES. The verifier returned SUPPORTS at 0.97 confidence, citing the June
2026 Nasdaq listing under SPCX. Checked independently: **the verifier was right
and the label was wrong**, written from knowledge predating the listing. `o24`
was a name collision — the YC 2008 "Snipd" against a much better-known modern
product of the same name. Both corrected and re-queued, and both written up in
`ml/eval/README.md` §3 rather than quietly fixed.

### A negative result that reversed with sample size

The 30-example run showed verifier confidence averaging 0.901 when correct and
0.890 when wrong — an 0.011 gap, i.e. no usable signal. On 126 examples:
**0.886 correct vs 0.567 wrong, a 0.319 gap.** The small benchmark's reading
was not noisier, it was wrong, because it averaged over two errors. The old
`ml/eval/README.md` warned that 30 examples was "not enough to draw
fine-grained conclusions about calibration"; that warning was right and worth
heeding before quoting anything from a set that size.

**Checked again at 134 examples, because a number that flips once can flip
twice: 0.890 correct vs 0.567 wrong, a 0.323 gap.** Moved +0.004 from the
126-example reading. The gap is stable, and the 30-example figure remains the
outlier rather than the start of a trend.

### Baselines, all three of them

- **TF-IDF Claim Model vs the LLM verifier**, on *identical* retrieved evidence
  (the harness now persists what the LLM judged, so the baseline is not scored
  against a separately-retrieved and therefore incomparable set). On 120
  claims: **0.333 accuracy vs 0.967**, and **REFUTES F1 0.000 vs 0.986**. The
  documented SciFact negative result replicates in the target domain, worse.
- **Risk/Tone Model vs the keyword dictionary** — the head-to-head these notes
  have flagged as needed since the second pass. The keyword list wins outright:
  **F1 0.815 vs 0.000**, boilerplate false-positive rate 7.7% vs 0%, and the
  tone model's ranking AUC is **0.333 — below chance**, meaning it ordered
  risky text *below* risk-free text. It predicted `neutral` on all 28 excerpts,
  giving going-concern disclosures a negative probability of 0.014–0.071. Not a
  threshold problem: financial *news* sentiment is the wrong training domain for
  filing prose, as Loughran & McDonald established in 2011.
- **VentureFlow Score vs `_legacy_formula_score()`** on 300 real labeled YC
  companies with the evidence state held fixed: **0.668 vs 0.500**. The formula
  returns one identical value for all 300 because it reads no company feature
  at all. The finding is not "the model is better" — it is that the baseline
  has no company-level discrimination to be better than.

### The risk benchmark, built from real filings

28 excerpts, **22 of them real SEC text** pulled from EDGAR full-text search
(`ml/scripts/collect_risk_excerpts.py`, source URL kept per excerpt), plus 6
pitch-deck-register paragraphs since filings do not cover the product's actual
input. 15 genuine red flags, 13 deliberately hard risk-free negatives —
safe-harbour paragraphs, ASC 606 notes, a critical audit matter, macro risk
factors — all saturated with the vocabulary a keyword detector keys on.

The headline metric is the **boilerplate false-positive rate**, not recall: a
detector that flags everything scores perfect recall and is useless on
documents that are mostly hedged legal prose. It was completely unmeasured
before this benchmark existed.

### The bug the risk benchmark found on its first run

`groq_risk_analysis()` **never received the document**. It got only
`detect_signals()`'s output — the phrases the keyword dictionary had already
matched. So the LLM half of risk detection could not find any risk the keyword
list had missed, and on a document the dictionary matched nothing in it was
asked to assess a company it had been told nothing about. It returned
`overall_risk_level: "UNKNOWN"` with a null score on 13 of 28 excerpts,
including a deck paragraph disclosing 78% customer concentration. Fixed by
passing the text, adding constrained JSON output and a larger token budget (the
same fix `investment_agents.py` already carried), and telling the prompt
explicitly that boilerplate is not a red flag.

### Leakage: two models, opposite methodologies, nothing saying so

The Outcome Model still used `team_size` and `age_years` — the exact hindsight
features the VentureFlow Score model was rebuilt to exclude. In the combined
model `team_size` alone carried gain **1,978** against 390 for the next
structured feature: its single strongest signal was hindsight. Retrained on the
deployable feature set. **Cost: 0.058 ROC-AUC, 0.704 → 0.646** — close to the
0.048 the VentureFlow Score paid for the same exclusion. 0.646 is now the
reported figure everywhere, including against published work.

### The two dead report tabs — root causes, not nicer empty states

**Competitor Insights** was reading `report.similar_companies`, which is
`db.find_similar_companies()`: a trigram match over the user's **own**
companies table, restricted to rows that already have a report or a portfolio
investment. On a fresh single-user database analysing a different company every
time it correctly returns nothing, every time. Meanwhile
`sections.market_comparables` — comparables.py's cosine search over 1,560 real
YC companies — was computed on every run and **never rendered**. The similarity
search was never broken; nothing displayed it. Verified on a live run: five
comparables at 0.53–0.65 similarity with real recorded outcomes.

**Founder Analysis** had no input path at all. `agents/founder_verifier.py` has
existed since the third pass and had never run in production, because nothing
ever populated `DiligenceRequest.founders` — the field existed on the API model
and neither the upload form nor extraction ever filled it. Fixed at every
layer: `structured_extractor` and `pdf_extractor` read the team slide, the
upload form shows the detected names back for correction before submitting
(they go to a live web search, so a wrong name means a background check on a
stranger), and verification now runs **before** the specialist agents, so the
team analyst — which produces the radar's capability scores — finally sees the
only non-deck-derived evidence about the team this pipeline gathers.

### Multi-column PDF extraction, fixed at last

Carried in these notes as a known defect since the first pass.
`page.extract_text()` reads in raster order, so a three-column slide
interleaves. Measured on RouteIQ.pdf, the pricing slide put "$28/vehicle/mo"
next to "Up to 500 vehicles" when the deck says 50 — a wrong number presented
as a quoted fact, which is precisely what this product exists to prevent.

Now reconstructed from word geometry: gutter detection by x-histogram, with
full-width prose lines excluded from that histogram (one slide subtitle
otherwise bridges every gutter and vetoes detection for the whole page), and
blocks split on large vertical gaps so footers stay at the foot of the page.
**Verified lossless across 21 real decks** — identical character multiset, pure
reordering. The PetVoice team slide now yields three intact founder records
where it previously yielded three names, three roles and three biographies in
separate runs.

### Multi-format input and output

`document_extractor.py` accepts **.pptx, .docx, .txt and .md** alongside PDF,
all converging on the same `structured_extractor` pipeline rather than a
parallel path per format. The pptx reader needed its own column reconstruction:
shapes are stored in z-order, and the same team slide came out as three names,
then three titles, then three biographies.

`report_document.py` now holds the report's content once, and **PDF, Word and
Markdown are three renderers over it**. Adding a fourth format is one renderer
and no content changes. A test asserts all three carry the same sections, which
is the drift this structure exists to prevent.

### Real bugs found by the new tests

- The `.txt`/`.md` reader tried **utf-16 before cp1252**. Without a BOM, utf-16
  accepts almost any even-length byte string, so an ordinary Windows-encoded
  note decoded to plausible-looking CJK and was passed downstream as the deck's
  text. Now BOM-gated.
- `_fallback_ai_analysis()` hardcoded "Insufficient database evidence was
  available for a reliable comparable-company analysis" — printed even when
  five real comparables were in the same report, so the memo contradicted the
  table rendered below it.
- `report_pdf` did not escape `&` or `<`. reportlab parses Paragraph text as
  mini-HTML, so a company name like "Smith & Sons" would have raised.

### Verified by running

`pytest tests/` → **97 passed** (65 before this pass). Frontend `eslint`,
`tsc -b` and `vite build` all clean. A live end-to-end run of a real deck
through the real HTTP endpoints (`scripts/run_single_deck.py`).

### Blocked, and not worked around

**Groq's free-tier 200,000 tokens/day is scoped to the organization, not the
API key** — verified by the 429 naming the same org id after a new key was
issued. A second, genuinely different org was then used and also exhausted.
What that blocks, precisely:

- The last **24 of 150** claims. `python ml/scripts/eval_claim_verifier.py`
  resumes from the partial log; the committed results file is marked
  `"complete": false` so nobody quotes a partial run as 150.
- The LLM risk detector's **post-fix** numbers. The as-shipped (pre-fix)
  measurement is preserved in `risk_benchmark_results_before_textfix.json`.
- A full-fidelity end-to-end deck run. The pipeline plumbing was verified on a
  real deck; the LLM stages inside that run degraded to their fallbacks.

Both harnesses now **refuse to score a provider outage**. When the cap is hit
the verifier degrades to NOT_ENOUGH_INFO at confidence 0.0, indistinguishable
in a results file from a real verdict; the first 150-example attempt recorded
14 such rows before this guard existed, and they would have depressed SUPPORTS
recall and inflated NOT_ENOUGH_INFO precision by an amount that is not a
property of the verifier at all.

### Still open after this pass

- The **investment memo is unevaluated**. LLM-synthesised, unattributed, and
  the half of the product a VC actually reads. FActScore/ALCE are the right
  instruments (`ml/research/related_work.md` §3).
- The **four specialist agents** are unvalidated LLM judges whose scores the
  report renders as measurements.
- Both benchmarks are **single-annotator**, with no agreement figure.
- No **contrastive evidence pairs**, so nothing tests whether the verifier is
  sensitive to evidence or merely to topic overlap.

## Update — 22 Aug 2026, ninth pass: the UI crash, and the first fully-working run

### "Something went wrong" on every page — Rules of Hooks

Reported as random breakage while navigating. Root cause in `Analysis.tsx`:

```
const Analysis = () => {
  const [activeTab, ...] = useState("Summary");
  const [ddOpen, ...]    = useState(false);
  const { report } = useApp();
  if (!report) { return <EmptyAnalysis /> }      // early return
  ...
  const [pdfExporting, ...] = useState(false);   // ~85 lines below
```

React identifies hooks by call order. With a report loaded this rendered five
hooks; the instant `report` became null the early return fired first and only
four ran, so React threw *"Rendered fewer hooks than expected"* — unrecoverable,
so the root ErrorBoundary replaced the whole application. `report` goes null on
several paths, most easily the sidebar's Settings button, which calls `reset()`.
That is why it looked navigation-related: what mattered was the report vanishing
underneath a mounted Analysis page.

**`tsc -b` and `vite build` passed for this bug's entire lifetime.** Neither has
any concept of hook ordering. Added ESLint with `react-hooks/rules-of-hooks` as
an **error**, wired into `npm run build`. Proved the guard works by
reintroducing the bug — ESLint reported *"React Hook useState is called
conditionally … Did you accidentally call a React Hook after an early return?"*
— then restoring the fix.

The ErrorBoundary itself was also part of the problem: it rendered a bare
"Reload to try again" and deliberately hid details. That is right for a public
product and wrong here, where the person seeing it is the person who can fix it.
It now shows the error, stack and component stack with a copy button.

### First fully-working end-to-end run

Live, against real Neon and real Groq, on `RouteIQ.pdf` — **210s, every stage
working simultaneously for the first time in this project**:

| | Result |
|---|---|
| Extraction | `llm_schema`, 4 claims (not the regex fallback) |
| Claim verification | 4 checked — 1 supported, 3 NOT_ENOUGH_INFO |
| Risk analysis | **MEDIUM** — worked at all, having failed 100% of runs before the Unicode fix |
| Specialist agents | market 0.30, team 0.20, bull 0.32, bear 0.32 — real confidences, previously all 0 |
| VentureFlow Score | 47/100, range 34–56, medium confidence |
| Memo | 6,505 chars, and it explains the model's score |
| RAG | 5 prior reports retrieved via pgvector |
| Persistence | report 58, chat session attached |

Verified in the browser afterwards: the report renders, the score panel shows
47/100 with its interval, chat is enabled, no console errors.

**Every stage in that table was broken or degraded before this pass and the
one before it.** The reason they all looked fine is that each failure is caught
and degraded individually, so the product kept producing reports that were
quietly empty.

## Update — 22 Aug 2026, eighth pass: first run against live credentials, and what that exposed

This is the first pass executed with a working `DATABASE_URL`, a working
`GROQ_API_KEY` and real network access. Every prior pass ran in a sandbox that
could reach none of those, which is why a set of bugs that break the product on
every single run survived several "all green" passes. **Automated tests,
`tsc -b` and `vite build` were passing throughout — none of them exercise the
live app, and that gap is the entire story of this pass.**

### The reported failure, root-caused

The user's symptom was an analysis that ran for minutes, sat at roughly 60%,
then failed with the generic "Analysis could not be completed. Please retry."
Two separate bugs were bundled in that.

**Bug 1 — the failure was never reported.** `_run_analysis_job` caught every
exception and wrote a fixed string into the job's `error` field, discarding the
actual exception. An exhausted API quota, an unreachable database and a genuine
code bug were indistinguishable on screen, and "retry" was actively wrong
advice for two of the three. Fixed first, deliberately, because without it the
real cause could not be seen. `_describe_failure()` now translates known causes
into an action and falls through to the real exception type and message
otherwise. `tests/test_job_error_reporting.py` covers this; nothing previously
exercised the failure path at all.

**Bug 2 — the actual crash**, which the fix above immediately surfaced:

```
File "ventureflow_agent.py", line 236, in _evidence_penalty
    penalty += max(0.0, min(0.20, (risk_score / 100.0) * 0.20))
TypeError: unsupported operand type(s) for /: 'NoneType' and 'float'
```

`risk_score` came from `risk_result.get("overall_score", 30)`. That idiom is
not a null guard — the default applies only when the key is *absent*, and the
risk agent emits the key with a null value whenever its own LLM call fails.
The arithmetic raised, and the exception escaped every try/except in the
pipeline and failed the whole job after minutes of real work. This was code
added in the sixth pass, and it is exactly the degradation contract the rest of
`ventureflow_agent.py` follows and this did not. Fixed with `_coerce_number()`,
applied to every numeric input of both scoring functions rather than only the
one that happened to raise first.

### Three more bugs that were silently destroying report content

**`UnicodeEncodeError` from debug prints was deleting the product's output.**

```
File "agents/risk_detector.py", line 164, in score_risk
    print(f"\n\U0001f50d Running risk analysis for: {company}")
UnicodeEncodeError: 'charmap' codec can't encode character '\U0001f50d'
```

Windows stdout is cp1252. `risk_detector` prints a hardcoded emoji, so **risk
analysis raised on every single run** and degraded to `available: false`.
`claim_verifier` prints the model's reasoning, which routinely contains
typographic characters (U+2011, U+202F), so individual claim verifications
failed at random. Both are caught by the pipeline's try/except, so the app
looked healthy while shipping reports with no risk assessment and missing
claims. `console_safety.py` forces UTF-8 on stdout/stderr at import, covering
all 58 print sites and any added later — fixing the three known call sites
individually would have left the next one to be found in production.

**pgvector retrieval had never worked.** See the correction inserted into the
fourth-pass section above. `vector <=> double precision[]` does not exist;
every call fell back to keyword search while the product reported vector
retrieval. Fixed with `::vector` casts and verified returning real
cosine-ranked neighbours.

**The document-chat panel was dead on every saved report.** `store_document`
files the deck text under a session id, but that id was never written into the
report, and `_normalize_report` hardcoded `session_id=""`. Chat worked only in
the browser tab that had just run the analysis; any report opened from the
Dashboard showed a disabled "Run analysis first" box while its text sat in the
database. Now persisted and read back.

**Specialist agents were failing on JSON parsing** — truncated objects and
empty completions, because `max_tokens=1000` was tuned for Llama 3.3 and the
current model spends part of its budget on an internal reasoning trace. Now
uses Groq's constrained `json_object` output (verified supported for this
model), a larger budget, and logs what actually happened.

### Performance: 262s → 99-117s, measured

Profiled rather than guessed. Claim evidence collection ran five DuckDuckGo
queries and five page fetches sequentially per claim: **16.8s + 5.5s measured
per claim**, roughly half of a four-minute analysis spent waiting on I/O with
no ordering requirement. Now concurrent, capped at 5 workers: **24s → 9.3s per
claim**. Full timed runs went from 262s to 99-117s. Some DuckDuckGo queries get
throttled under concurrency and return no results; evidence still came back
complete in every observed run, but that trade is real and worth knowing.

### Progress reporting is now honest

The frontend advanced its labels on fixed 30/60/90/120s `setTimeout`s that had
nothing to do with the backend, so a slow-but-working run looked identical to a
hung one — which is what the user was actually looking at. Migration 008 adds
`analysis_jobs.stage`, the pipeline reports its real current step, and the UI
shows that plus elapsed seconds. Observed stage transitions on a live run:
41s claims → 89s risk → 101s agents → 126s evidence → 138s memo → 149s done.

### Step 4 verification: what was real and what was not

- **The VentureFlow Score model is real.** The file loads, it is a 12-member
  calibrated RandomForest ensemble, and its stored metrics (ROC-AUC 0.6772,
  ECE 0.0219, n=1298) **match `ml/research/venturescore_experiments.json`
  exactly**, checked programmatically rather than by eye. It is genuinely
  wired into the score a user sees: live runs report
  `score_source=venturescore_model`.
- **`openai/gpt-oss-120b` is real** and reachable on this key.
- **"SEC EDGAR filings" was fabricated.** It appeared twice in the UI and
  nowhere in the backend — no sec.gov call, no CIK lookup, no EDGAR client.
  It had also survived an earlier cleanup that removed a neighbouring
  Crunchbase/PitchBook fabrication from the same sentence, which is a useful
  reminder that removing one false claim from a string does not validate the
  rest of it. Removed.
- **"in under 60 seconds" was false** — measured runs are 99-262s. Now says
  2-4 minutes. **"cross-references every claim with live databases"** likewise
  overstated a single web-search call. Corrected.

### Still blocked, and not worked around

**A full-fidelity live run could not be demonstrated, because the Groq free
tier's 200,000 tokens/day is exhausted.** One analysis costs roughly 30-50k
tokens, so a handful of runs consumes the day. Under that limit every LLM step
degrades: extraction falls back to regex, specialists return confidence 0, and
the memo is a 1.2KB stub. What *was* verified:

- A live run against real Neon and real Groq **completes** (status `complete`,
  report persisted, `score_source=venturescore_model`, chat session attached)
  rather than failing — the reported crash is genuinely fixed.
- With the Groq calls stubbed and everything else real, **all 14 report
  sections populate** and specialists report real confidences, so the pipeline
  itself is correct.

This is a billing limit, not a code limit, and it is recorded here rather than
papered over. Re-running the deck batch on a day with quota, or on a paid tier,
is what remains to produce full-fidelity output.

**Also still open:** the demo-deck path referenced in the brief no longer
exists — it was deleted in commit `d348b32` at the user's explicit request in
an earlier session, so it could not be tested. And `pdf_extractor`'s
multi-column handling still interleaves text on some decks, which is
pre-existing and unchanged.

### Verified by running

`pytest tests/` → **65 passed** (55 before this pass's additions), `tsc -b`
clean, `vite build` succeeds. Manual QA against the live backend: all four
Analysis tabs render real content with no placeholders; PDF export returns a
genuine 2-page, 2,445-character PDF (opened and read, not just status-checked);
comments POST and reload correctly; score history returns real multi-point
series (AgroPulse 4 points, Calmwell 3, ShelfSight 2); `/database/stats`
returns real counts; unknown chat sessions and unknown routes degrade cleanly.

## Update — same-day, seventh pass: fixed report persistence, surfaced the score in the UI

**The "Analysis could not be completed" error is fixed. It was three bugs
stacked, not one**, and the analysis itself was never the problem — every
report was being generated correctly and then thrown away on save.

1. **Migrations 005 and 007 could never apply to this database.** Both
   declared `report_id UUID REFERENCES dd_reports(id)`, but this Neon instance
   is the legacy integer-key schema that `002_repair_legacy_neon_schema.sql`
   exists specifically to support — `dd_reports.id` is `integer`. Postgres
   raised `DatatypeMismatch: foreign key constraint cannot be implemented`.
   Both migrations now resolve the referencing column's type from
   `information_schema` at run time, so they work on either schema.
2. **`ensure_schema()` ran every migration inside one transaction**, so that
   single failure silently rolled back 004, 006 and 007 as well. The database
   looked migrated — the base tables were all present from earlier runs —
   while `chat_sessions`, `report_comments` and the pgvector `embedding`
   column were all quietly missing. Each migration now runs in its own
   savepoint and a failure is logged and skipped rather than taking the
   others with it.
3. **`persist_report()` called `conn.rollback()` inside its fallback path.**
   When the embedding insert failed (because of #2), that rollback undid the
   *entire* transaction including the `companies` INSERT immediately above
   it. The retry then wrote a `dd_reports` row pointing at a company that no
   longer existed: `ForeignKeyViolation: Key (company_id)=(33) is not present
   in table "companies"`. Now a `SAVEPOINT`, which undoes only the failed
   statement. Caught a follow-on bug while fixing it, too: `RELEASE SAVEPOINT`
   replaces the cursor's result set, so the `RETURNING id` has to be fetched
   *before* the release or psycopg raises "the last operation didn't produce
   records".

**Verified**: all 7 tables now exist, pgvector is enabled, `ensure_schema()`
reports zero skipped migrations, and a live end-to-end `_perform_analysis()`
run persisted successfully as report 36 with the VentureFlow Score attached.

**The score is now visible in the product.** Until this pass the trained model
existed only in the API response — the UI never rendered it, which made the
whole sixth pass invisible to a user. New `VentureScorePanel` component on the
Analysis summary tab shows the score with its 5th–95th percentile range, the
confidence label, the split between the model's prior and this report's
evidence adjustment, input coverage, ensemble agreement, and an expandable
methodology section quoting ROC-AUC with its CI, calibration error, and the
deliberately-excluded contaminated features.

**One contradiction found by looking at the rendered page rather than the
code**: the panel showed 57 while the stat card below it showed 30, with
nothing explaining the difference — the pipeline caps `final_score` at 30 when
verification is incomplete. Two unexplained scores on one page is worse than
either alone, so the panel now states the cap and why it applies.

**Frontend audit — what was actually wrong.**

- **Two false claims in the UI, both now corrected.** The "Live Fact-Check"
  step advertised cross-referencing against "Crunchbase, PitchBook signals";
  neither is used, and `market_data.py` holds both as documented stubs
  returning `available: false` because there is no budget for either
  contract. Telling investors the product queries paid data sources it does
  not have is precisely the sort of claim this codebase refuses to make
  anywhere else. The Data Sources list also still advertised "Groq Llama 3.3
  70B", decommissioned in the previous pass.
- **`styles/tailwind.css` was never imported by anything.** Tailwind has
  therefore never been active in this app; every page styles itself with an
  inline `<style>` block. Worth correcting an assumption made earlier in this
  session: the dark `body` gradient in that file was *not* causing the dark
  edges visible in the app, because the file was never loaded at all. It is
  now imported and carries the theme tokens, focus-visible rings,
  reduced-motion handling and the responsive breakpoints. Verified after
  wiring it up that Tailwind Preflight does not disturb the existing pages —
  the Dashboard `h1` still computes to 28px with no injected margin.
- **The app had zero media queries.** Below ~1100px the fixed `1fr 320px`
  rail and `repeat(4, 1fr)` stat grids simply crushed. Added breakpoints;
  verified in a real browser at 768px (stat grid 4→2 columns, rail collapsed,
  no horizontal overflow) and at 375px (single column, no overflow).
- **`* { transition: all 0.2s ease }`** applied a transition to every property
  of every element, including layout properties, fighting Framer Motion and
  animating things that should be instant. Removed.
- **A mislabelled header chip** rendered the final score as "30% data
  confidence" — two different quantities. Now reads "30/100 overall score".
- **Accessibility was near-absent** (2 aria attributes across ~3,400 lines of
  page code). The new panel is properly labelled, and a global
  `:focus-visible` ring plus `prefers-reduced-motion` support now exist.

**Not addressed, and worth being explicit about**: 24 of the 49 files under
`frontend/src/` are 0 bytes — empty scaffolding for components, hooks, types
and services that were never written. The real application is ~3,400 lines
crammed into four files (`Analysis.tsx` 943, `UploadDeck.tsx` 1097,
`Dashboard.tsx` 867, `Sidebar.tsx` 483) with 223 inline `style={{}}` blocks
and no shared design system. That is the real frontend debt here, and
splitting it apart is a dedicated pass, not something to bolt onto a bug fix.
There is also still no dark mode, no loading skeletons, and no toast system.

**Verified this pass**: `pytest tests/` → 44 passed, `tsc -b` clean,
`vite build` succeeds, zero browser console errors, and the panel confirmed
rendering real model output in a live browser against report 36.

## Update — same-day, sixth pass: the VentureFlow Score replaces the hand-tuned formula

The headline number a VC sees is no longer arithmetic somebody made up. It
comes from a trained, calibrated model, and the LLM's job has been demoted to
explaining that number rather than producing it. Full methodology, results
with confidence intervals, and an honest limitations section are in the new
`ml/research/` directory; the model card in `ml/README.md` is updated.

**Audit first — three things in the incoming brief did not match the repo.**
Every file the brief described as existing does exist, the Outcome Model
loads and scores for real (0.7038/0.5721/0.7001 in its report.json matches
the 0.704/0.572/0.700 claimed), and `pytest` was green at 18/18 before any
change. But:

- **Groq's `llama-3.3-70b-versatile` is decommissioned.** The key still
  authenticates; the model id returns 404 `model_not_found`. Listing the
  models actually available on this key shows no Llama 3.3 of any size. The
  entire LLM layer of the app — claim verification, founder verification,
  risk detection, all four specialist agents, memo synthesis, structured
  extraction, chat — was dead. Switched to `openai/gpt-oss-120b` (user's
  choice from the available list) in `groq_client.py`, which is the single
  place the model id lives, and verified with a live call.
- **`huggingface.co` is reachable in this environment.** Every prior pass
  recorded it as blocked. That unblocked the two never-run training scripts —
  see below.
- **`DATABASE_URL` still points at the dead Supabase host**, unchanged from
  the fifth pass. Not fixed here; it needs the user's own Neon credentials.
  Consequence for this pass: no persisted reports exist, so no feature could
  be derived from report history.

**What was built.** `ml/scripts/prepare_venturescore_dataset.py` rebuilds the
labelled set with 30 features instead of 6, from YC fields an audit found
sitting unused at 97-100% coverage: the second-level `subindustry` taxonomy,
12 technology tag indicators, remote-work posture, Bay Area / US geography, a
rebrand signal (normalised so the 91 companies whose "former name" is
literally the string "Inc." don't count as pivots), and text-shape features.
`ml/scripts/train_venturescore_model.py` then compares four model families
against a logistic-regression baseline under repeated stratified 5-fold CV
with 2,000-sample bootstrap CIs, with every transformer fit inside the
training fold. `ml/venturescore.py` serves the winner.

**The finding worth publishing, and the reason the shipped model scores
*lower* than it could.** `team_size` came out of the first SHAP run at 0.72
mean |SHAP|, more than three times the next feature. Checking its
distribution against the label: exited companies have median 11 / mean 105,
shut-down companies median 3 / mean 10 — and only ~5% of either class is
zero, so this is not a crude "dead company has no staff" artefact. YC records
*current* headcount, so the feature is mostly recording that successful
companies grew. A model that keeps it learns "big team implies success" and
would systematically mark down exactly the four-person seed-stage startups
this product exists to evaluate. `age_years` and `batch_year` have the same
problem from the other direction — cohort exit rate falls 0.65 to 0.38 from
the 2010 batches to 2021-22, which is right-censoring, not worse founders.
All three were dropped. It costs 0.048 AUC (0.7243 to 0.6759), which is
**about 22% of the model's above-chance signal**. Both numbers are reported,
because the gap is the point. `isHiring`, `top_company` and website-liveness
were excluded earlier still, at dataset level, as outright observations of
the outcome.

**Shipped**: calibrated Random Forest (isotonic), 12-member bootstrap
ensemble, ROC-AUC 0.6739 [0.658, 0.689], ECE 0.0210, Brier 0.2226. Random
Forest beating LightGBM was not expected — LightGBM was this project's
default — and on the clean feature set LightGBM is the *worst* tree model
(0.6462), below plain logistic regression. The incumbent choice was the one
most dependent on the contaminated features.

**Uncertainty is reported on every prediction**, along two separate axes,
because they mean different things: `ensemble_std` plus a 5th-95th percentile
range for model uncertainty, and `feature_coverage` for input uncertainty
(the model trains on directory metadata and scores pitch decks; remote
posture and subindustry simply aren't in a deck). Confidence degrades on
either axis — tight ensemble agreement computed over mostly-imputed input is
agreement about nothing — and a `low`-confidence score is blocked from
producing a decisive INVEST or PASS.

**Two bugs caught by running things rather than reading them.**

1. **The specialist-agent confidence field crashed the entire report.** The
   prompt asks for "keys confidence, ..." and never says it must be numeric.
   Llama 3.3 always answered with a number, so `float(result["confidence"])`
   worked for as long as that model existed. `gpt-oss-120b` answers
   `"confidence": "low"` — and `float("low")` raises `ValueError`, which
   propagated out of `run_due_diligence()` and failed the whole report. Found
   because the existing test suite went red after the model switch. Fixed at
   both ends: `_coerce_confidence()` now handles numbers, numeric strings,
   percentages and the low/medium/high vocabulary, degrading to 0.0 rather
   than raising; and the prompt now states the expected type. An LLM-authored
   field should never have been parsed with a bare `float()`.
2. **`print(ai_analysis)` destroyed completed reports on Windows.** Found
   during a live end-to-end run, not a mocked one. `sys.stdout` here is
   cp1252, the memo contained U+2011 NON-BREAKING HYPHEN, and the resulting
   `UnicodeEncodeError` fired *after* the report was fully built — so a
   correct report was lost on its way to the console. Now `_safe_print()`.
   Precise about blast radius: the returned dict and the persisted JSON were
   always fine, but the exception escaped `run_due_diligence()`, so the
   caller lost the report anyway. The same class of bug also broke
   `prepare_outcome_dataset.py` outright — `Path.read_text()` with no
   encoding against a raw YC dump containing 14,833 non-ASCII bytes — meaning
   the "reproduce from scratch" command documented in `ml/README.md` had
   never worked on Windows. Fixed; the rebuilt dataset matches the committed
   one exactly at 1,560 rows.

**Also caught, by reading the live LLM output instead of trusting it**: the
first live run had the memo state "67 - 0.17 = 66.8, rounded to 50", because
the prompt handed it the evidence adjustment as a probability delta while the
score is in points. Confident arithmetic nonsense in front of an investor.
The prompt now states the units and shows the subtraction; re-verified live,
and it now reads "Model-only baseline: 67/100, Evidence adjustment: -17
points, Resulting score: 50/100".

**The two never-run models were finally run.** `huggingface.co` being
reachable removed the historical blocker, but a new one replaced it:
`datasets` 5.x dropped script-based datasets, and both corpora are
script-based with no parquet conversion. Both loaders were rewritten to read
published source files directly (SciFact from AllenAI's S3 tarball,
PhraseBank/TFNS from their Hub repos), which is more durable anyway.
- **Claim Model: trained, and the honest result is that it is unusable.** 45%
  accuracy, and REFUTES — the class that matters for diligence — has F1 0.05.
  Not wired in, because shipping it would make claim verification worse. This
  is a clean negative result and it argues *for* the existing LLM verifier:
  lexical TF-IDF overlap cannot represent negation or entailment.
- **Risk/Tone Model: trained, 77% accuracy, macro-F1 0.62.** Genuinely
  usable. Also not wired in — swapping it against the incumbent keyword
  detector needs its own head-to-head evaluation, and bundling that into this
  pass would have meant shipping an unmeasured change.

**Verified this pass, by running it**: `pytest tests/` → **44 passed** (18
before, plus 26 new across `tests/test_venturescore.py`), with no
`DATABASE_URL` and no network needed for the suite. `tsc -b` clean and
`vite build` succeeds. A live end-to-end `run_due_diligence()` against real
Groq produced score 50/100 sourced from `venturescore_model`, with the memo
correctly explaining the model-only 67 and the -17 evidence adjustment. The
model artefact was also cut from 362 MB to 26 MB (30x400-tree members to
12x120) after the first fit produced something too large to version; AUC
moved +0.0045 and ECE -0.005, both within noise.

**Still open, honestly**: the pipeline-derived features the brief most wanted
— claim-verification confidence, founder verification, risk counts, GitHub
rubric score — are still not in the model, and this is the single largest gap.
They are computed at inference time and do not exist for the 1,560 labelled
companies; training on them means running the full LLM pipeline over the
entire training set, which is a real API cost that hasn't been incurred. The
evidence penalty in `_evidence_penalty()` is a stated, bounded, visible prior
standing in for that fitted layer, and is labelled as such everywhere it
appears. GitHub-derived features are also still out of reach at scale: no
`GITHUB_TOKEN` is set (60 requests/hour), and YC's data has no repo field, so
discovery would be guesswork.

## Update — same-day, fifth pass: root-caused the DB error, removed the demo deck

- **Root cause of "Analysis queue is currently unavailable" found, not just
  ruled-out hypotheses.** The live `.env`'s `DATABASE_URL` points at a
  Supabase Postgres host (`db.<project>.supabase.co`), not Neon — and that
  host no longer resolves at all (`getaddrinfo failed`), confirmed with a
  direct `psycopg.connect()` from this machine. That's the "wrong folder /
  missing .env" symptom too: several stale copies of this repo exist side by
  side in `Downloads/` (`venture_flow_hardening_pass/`, old `venture-flow*`
  zips/folders), so running the app from one of those, or from this repo
  before `.env` was filled in, would crash or 503 the same way. Per the
  decision recorded below ("nothing stays on Supabase, everything goes to
  Neon"), the fix is to put a real Neon connection string in this repo's
  `.env` — not a code change, since `db.py`/`ensure_schema()` already target
  Neon correctly and will pick up all seven migrations on first successful
  connect. Not fixed *for* the user in this pass, since it needs the user's
  own Neon project credentials, which aren't something a session should
  invent or guess at.
- **Demo deck feature removed**, per explicit user request, not just
  disabled: `demo_data.py` deleted; `GET /demo/sample` and its import
  removed from `api.py`; `runDemoAnalysis`/`getDemoSample`/`DemoSample`
  removed from `AppContext.tsx`/`apiClient.ts`; the "Try a demo deck — no
  upload needed" button and its handler removed from `UploadDeck.tsx`.
  Verified: `pytest tests/` → 18/18 still pass (no test referenced the demo
  route), `tsc -b` builds clean, `api.py` byte-compiles clean, and a repo-wide
  grep for `demo_data`/`DEMO_SAMPLE`/`getDemoSample`/`runDemoAnalysis`/
  `DemoSample` outside `legacy/` returns nothing.

## Update — same-day, fourth pass: Evidence Depth + Product Polish

All 8 remaining Ship List items in these two sections, built and verified.
Nothing in Foundation Hardening or "Make the model real" changed this pass.

**Evidence depth (4/4)**

- **[CORRECTED 22 Aug 2026, seventh pass — this claim was false.** The
  vector search described below never once executed successfully. The query
  passed a Python list, psycopg adapted it to `double precision[]`, and
  pgvector has no `vector <=> double precision[]` operator, so every call
  raised `UndefinedFunction` and fell through to the keyword `LIKE` branch.
  The claim that a `"method"` field meant this was "never silently degraded
  without a trace" was itself wrong in practice: the fallback logged at INFO
  and the product reported vector retrieval while doing keyword matching
  100% of the time. Fixed by adding `::vector` casts; verified returning real
  cosine-ranked neighbours. The rest of this entry is accurate.]**
- **Real pgvector retrieval.** Trained a second, general-purpose TF-IDF+SVD
  embedder (`ml/scripts/train_text_embedder.py`, 64 dims, same free YC
  dataset the Outcome Model uses — `huggingface.co` is still blocked in this
  sandbox, so this reuses the established workaround rather than inventing
  a new one). `embeddings.py` loads it; `migrations/006_pgvector_retrieval.sql`
  adds a `vector(64)` column to `dd_reports` and enables the pgvector
  extension. `rag_engine.build_context()` now tries real cosine-similarity
  vector search first and falls back to the original keyword `LIKE` search
  if the embedding or the extension is unavailable for any reason — a
  `"method"` field on the returned context says which one actually ran, so
  this is never silently degraded without a trace.
- **Founder/team verification agent** (`agents/founder_verifier.py`) — reuses
  the same web-search-plus-Groq-judgment pattern as the existing claim
  verifier. Given a founder name it searches, then asks Groq whether the
  evidence is CONSISTENT, CONTRADICTS, or NOT_ENOUGH_INFO with what the deck
  claims about them. Capped at 3 founders per report. Wired into
  `ventureflow_agent.py` as an additive `sections.founder_verification`
  field — only runs if the caller passes `founders`, and never blocks the
  rest of the report on failure.
- **Real comparable-company benchmarking** (`comparables.py`) — embeds the
  target company's description with the same embedder above, and finds the
  nearest real companies (by name, industry, stage, batch, and actual
  outcome) from the 1,560-company YC dataset by in-memory cosine similarity.
  Not synthetic; every comparable returned is a real company from the
  dataset with a real recorded outcome.
- **Paid market-data API integration path** (`market_data.py`) — an abstract
  `MarketDataProvider` interface with `FreeDataProvider` (wraps the above,
  the only one actually wired in) and documented `CrunchbaseProvider` /
  `PitchBookProvider` stub classes gated on `CRUNCHBASE_API_KEY` /
  `PITCHBOOK_API_KEY`. They return `{"available": False, "reason": "...not
  implemented -- no API key/budget configured."}` rather than pretending to
  call an API this project has no budget or contract for. This is the
  integration point a future pass wires a real key into — not a fake call.

**Product polish (4/4)**

- **Proper PDF export** (`report_pdf.py`, reportlab Platypus) — a real
  multi-section PDF: score/recommendation/risk summary table, investment
  memo, claim-verification summary, key concerns/red flags/positives,
  comparable companies (if available), outcome-model signal (if available),
  technical score (if available), closing caveat. New endpoint
  `GET /reports/{id}/pdf`. `Analysis.tsx`'s export button now calls it, and
  falls back to the original plain-text export only if the PDF request
  fails.
- **Historical score tracking per company** — `db.get_score_history()` reads
  every past `dd_reports` row for a company name, oldest first.
  New endpoint `GET /companies/{name}/history`. `Dashboard.tsx`'s
  "Investment Score Trend" chart — previously hardcoded to
  `hasHistory = false` and an empty dataset, i.e. fabricated-looking but
  actually inert — now fetches real history and only renders once there
  are 2+ real data points to draw a trend from.
- **Team collaboration on reports** — `migrations/007_report_comments.sql`
  adds a `report_comments` table; `POST`/`GET /reports/{id}/comments`;
  a `CommentsPanel` component in `Analysis.tsx` next to the existing chat
  panel. Honest caveat, stated directly in the migration and worth
  repeating here: there is no auth yet (that's a Foundation Hardening item,
  not started), so `author_name` is free text a commenter types in, not a
  verified identity. This is "shared notes on one Neon database," not real
  per-user team accounts — good enough to demo, short of the real thing
  until accounts exist.
- **Onboarding / sandbox mode** — `demo_data.py` bundles one clearly-labeled
  fictional company ("Solstice Robotics (Demo)") with a deck-style
  description, a mix of claims (some should verify, some shouldn't — not a
  rigged all-green demo), founders, and financials. New endpoint
  `GET /demo/sample`. A new "Try a demo deck — no upload needed" button on
  the upload page runs the *real* pipeline (claim verification, risk model,
  RAG, Groq synthesis, comparables, the works) against it, so a first-time
  user with no deck and no Neon data yet can still see what a completed
  report looks like.

**Verified this pass**: `pytest tests/` → 18/18 still passing (no new test
files added this pass — the new code paths were smoke-tested directly:
`embeddings.embed_text()`, `comparables.find_comparables()`,
`market_data.get_market_data_provider()`, `report_pdf.build_report_pdf()`
against a synthetic report, and `agents.founder_verifier.verify_founders()`
on empty input, all run and inspected directly, not just read). Every new
`.py` file byte-compiles cleanly. `frontend`: `tsc -b` and `vite build` both
succeed (one real bug caught doing this — `Analysis.tsx` used the new
`useEffect` for the comments panel without importing it; fixed). A live
`TestClient` request against the new `GET /demo/sample` route returns 200
with no environment variables set, confirming it degrades to nothing worse
than "demo unavailable" rather than crashing if it ever did depend on
something live (it doesn't — it's a static fixture).

**Not resolved this pass, and needs the user's own terminal output to
diagnose**: the "Analysis queue is currently unavailable" error the user is
seeing is `api.py`'s literal 503 message, raised whenever
`db.create_analysis_job()` throws — confirmed by grepping the frontend
(the string doesn't originate there). Ruled out one hypothesis directly: a
`#` character in the DB password (visible in an earlier screenshot) does
*not* break psycopg's URL parsing — tested with
`psycopg.conninfo.conninfo_to_dict()` directly. The real cause needs the
`uvicorn` terminal's actual traceback, which isn't visible from this
sandbox — most likely candidates, in order of likelihood: the Neon/Supabase
project being paused (common on free tiers after inactivity), a stale or
malformed `DATABASE_URL` in `.env`, or `ensure_schema()` failing partway
through on first boot. Once the backend can reach the DB at all,
`ensure_schema()` will pick up both new migrations (006 pgvector, 007
comments) automatically on the next restart — no manual migration step
needed.

## Update — same-day, second pass: the ML layer

Full detail and methodology lives in `ml/README.md`; this is the summary.

- **Trained and running**: the Outcome Model. Real data (1,560 Y Combinator
  companies, pulled live from `yc-oss/api`, 3.5y+ post-launch, resolved
  outcome only), real held-out test set, real ablation (text-only AUC 0.572,
  structured-only AUC 0.700, combined AUC 0.704 — structured features carry
  almost all the signal, which is itself the finding). Wired into
  `ventureflow_agent.py` as an additive `sections.ml_outcome_model` field;
  verified it never blocks the report if the model is missing or errors
  (`tests/test_ml_outcome_model.py`). Zero frontend changes were made or
  needed.
- **Written but not run**: Claim Model (SciFact) and Risk/Tone Model
  (Financial PhraseBank + TFNS) — both scripts are complete and correct in
  `ml/scripts/`, but this session's cloud sandbox blocks `huggingface.co`
  and S3 at the network level (confirmed with direct connection tests, not
  assumed) while allowing PyPI/npm/plain GitHub. Run either script on a
  machine with normal internet access and it will produce a trained model
  in the same format the Outcome Model uses.
- **Deliberately not attempted this session**: multi-tenant auth, billing,
  compliance docs (ToS/DPA/retention policy), and go-to-market — these need
  real business/legal decisions and infrastructure provisioning, not code
  a session can unilaterally "complete." They're still tracked, honestly,
  on the Ship List.

## Bugs fixed (verified, not just described)

1. **`agents/investment_agents.py` had a real `SyntaxError`** — an f-string
   expression contained a backslash (`f"...{'\n'.join(claim_lines)}..."`),
   which is illegal before Python 3.12. Since `ventureflow_agent.py` imports
   this module at the top level, and `api.py` imports `ventureflow_agent`,
   **the entire FastAPI app failed to import on Python < 3.12** — not just
   the specialist-agent feature. Confirmed locally on Python 3.11.15. Fixed
   by precomputing the joined string on its own line before the f-string.

2. **The Groq client was constructed eagerly at import time** in five files
   (`chatbot.py`, `ventureflow_agent.py`, `agents/claim_verifier.py`,
   `agents/investment_agents.py`, `agents/risk_detector.py`). Groq's SDK
   raises immediately if no API key is resolvable — so with `GROQ_API_KEY`
   unset or misconfigured, the whole app failed to start, including
   completely unrelated routes like `/health`. Replaced with a shared lazy
   singleton in the new `groq_client.py` (`get_client()` + a single `MODEL`
   constant, previously duplicated five times). Verified: the full test
   suite and a live `TestClient` smoke test now pass with **no
   `GROQ_API_KEY` and no `DATABASE_URL` set at all** — `/health` correctly
   reports `degraded` instead of crashing, `/database/stats` returns a clean
   503, and `/nonexistent-route` returns 404.

3. **No catch-all frontend route** (QA-006 from the deleted 2026-08-03 audit
   was never actually fixed) — an unknown path rendered the sidebar with a
   blank main panel. Added `frontend/src/pages/NotFound.tsx` and a `path="*"`
   route in `App.tsx`.

4. **`DBStats`/`getStats()` in `apiClient.ts` described a schema that no
   longer exists** — `documents`, `sentiment_records`, `visual_assets`,
   `qa_pairs`, etc. are all legacy Supabase-era fields. The live
   `/database/stats` endpoint returns `{companies, dd_reports,
   portfolio_investments}`. Fixed the type to match. Note: nothing in the UI
   actually calls `getStats()` today, so this was dead code, not a live bug —
   worth knowing if you're deciding whether to wire a real stats widget into
   the dashboard later.

## Verified working (didn't just skim it)

- `pip install -r requirements.txt` + `pytest tests/` → **12/12 pass**, with
  zero environment variables set.
- A live `TestClient` run against `api.app` with no credentials configured:
  `/health` → 200 degraded, `/` → 200, `/nonexistent-route` → 404,
  `/database/stats` → 503 (clean error, not a crash).
- `frontend`: `npm install`, `tsc -b`, and `vite build` all succeed cleanly.

## Findings not yet fixed (flagged, not resolved — pick these up next)

- **Dashboard's "Investment Score Trend" chart is fabricated.** The eight
  monthly data points in `Dashboard.tsx` (`arrData`) are computed as
  `score * 0.012`, `score * 0.014`, … from the single current score — there
  is no real historical time series behind it. It reads as a real trend line
  to a VC glancing at the dashboard. Same issue with the Bull/Bear
  "conviction" scores (`score * 1.05`, `(100 - score) * 0.8`) — arithmetic
  derived from one number, not two independent signals. Either remove these
  widgets or wire them to something real (e.g. score history across repeat
  analyses of the same company, once that's tracked).
- **The orphaned Supabase ingestion pipeline** (`base.py`,
  `ingest_*.py` × 10, `model_singleton.py`, `generate_embeddings.py`,
  `download_docvqa.py`, `check_folders.py`, `final_check.py`,
  `agents/financial_reasoner.py`, `agents/visual_extractor.py`) is not wired
  into the live app at all — it targets Supabase tables the current Neon
  schema doesn't have. It represents real, reusable work (ten ingested
  financial-NLP datasets) toward the "real RAG" and "calibration layer"
  goals in the strategy report, but as-is it's dead code sitting next to the
  live pipeline. Decide: quarantine into a `legacy/` folder with a README,
  or delete, or actually wire it up — don't leave it half-connected.
- Claim/financial extraction in `pdf_extractor.py` is still pure regex and
  known (from the deleted QA audit) to mangle multi-column deck layouts.
- The in-memory rate limiter and the chat document store
  (`chatbot.py`'s `_document_store`) both reset on every restart/redeploy —
  fine for local single-user testing, not fine for anything persistent.

## Decisions the user made this session (don't re-ask)

- End goal is a multi-tenant SaaS for VC firms, but **right now**: single
  user, running and tested locally, no paid subscriptions.
- No historical deal-outcome data available initially → outcome-prediction
  modeling (Option C in the strategy report) was out of scope in the first
  pass. **Superseded in the second pass**: real labeled outcome data (YC's
  own directory, via `yc-oss/api`) was found and used — see the "Make the
  model real" section below. This line is kept for the record, not as
  current guidance.
- Free/low-cost data sources only — no paid company-data API (Crunchbase/
  PitchBook-style) budgeted yet.
- Groq stays the only LLM provider for now — no fallback provider.

See the published strategy report ("VentureFlow Field Report") for the full
competitive-landscape research and proposed build order (Phase 0 → 3).

## Update — same-day, third pass: Foundation hardening + the rest of "Make the model real"

Ship-list items closed this pass (Foundation hardening: 5/9 → all except the
regex-extraction item, which is now replaced too, so Foundation is
effectively done except `f6`/`f8` follow-ups below; Model layer: 2/9 → 8/9,
everything except the two still-network-blocked training scripts):

- **Chat/document sessions now persist to Neon** (`migrations/004_chat_sessions.sql`,
  `db.py`'s `upsert_chat_session`/`get_chat_session`/`delete_chat_session`,
  wired into `chatbot.py`). Falls back to in-memory-only, with a logged
  warning, if Neon is briefly unreachable — chat still works, it just won't
  survive a restart in that case, same as before this change.
- **Rate limiter is now multi-instance-safe when `REDIS_URL` is set**
  (`rate_limiter.py`) — a fixed-minute-bucket Redis counter, with a documented,
  automatic fallback to the original in-memory sliding window when Redis
  isn't configured or isn't reachable. Local single-instance use is
  unaffected either way.
- **Claim/financial extraction is now schema-validated** (`structured_extractor.py`):
  asks the LLM for a Pydantic-validated JSON object instead of parsing free
  text, and falls back to the original regex extractor (`pdf_extractor.py`,
  kept, not deleted) on any invalid JSON, schema violation, or LLM failure.
  `/upload-pdf` now reports which path actually produced the result via a
  new `extraction_method` field.
- **The orphaned Supabase pipeline is quarantined**, not deleted, not wired
  in — moved to `legacy/supabase_ingestion/` with a README explaining what
  it is and exactly how to revive it. **User decision, stated directly:
  nothing stays on Supabase, everything goes to Neon** — closes the question
  the quarantine README originally left open. All remaining "Supabase" strings
  in the live codebase (`.env.example`, `chatbot.py` comments/labels,
  `README.md`) were stale references cleaned up to say Neon, since nothing
  live actually used Supabase — `rag_engine.py` already queried Neon only.
- **Dashboard's fabricated charts are fixed, not just flagged.** The
  "Investment Score Trend" 8-point line (`score * 0.012` … `* 0.028`) is
  replaced with an honest single-point state ("today's score, re-analyze
  later for a real trend") since no real historical-score tracking exists
  yet (`p2`, still open). The four metric-card mini-sparklines, which used
  the same fabricated arithmetic, are removed rather than left inconsistent
  with the fix above. Bull/Bear conviction is now the real ratio of
  independently-detected positive factors to red flags for that report, not
  a rescaling of the single final score.
- **Technical/GitHub scoring module** (`technical_scoring.py`) — a
  transparent, individually-inspectable rubric over the public GitHub API
  (recent activity, contributors, tests/CI, README/LICENSE, issue health,
  repo age), wired in additively as `sections.technical_score` when a
  `github_url` is supplied (new optional `DiligenceRequest` field; not yet
  exposed in the upload form — zero other frontend changes).
- **Firm-personalization ranking layer — the mechanism, honestly not yet
  active.** `POST /reports/{report_id}/decision` captures the user's own
  invest/pass call; `ml/scripts/train_personalization_model.py` fits once 15+
  decisions exist; `ml/personalization.py` reports itself unavailable with a
  running count below that floor. There is no usage data on day one of this
  feature existing, and pretending otherwise would be the same mistake this
  whole session has been trying to avoid.
- **Claim-verification benchmark + eval framework** (`ml/eval/`) — 30
  hand-labeled claims, an eval harness reporting precision/recall/F1/
  confusion matrix/calibration. The metrics computation is unit-tested
  without network access; actually scoring the benchmark against live claims
  needs a working `GROQ_API_KEY` and internet, neither available here — see
  `ml/eval/README.md` for exactly how to run it and how the labels were built.
- **Drift monitoring** — `ml/inference.py` now logs every outcome-model call;
  `ml/scripts/check_drift.py` flags distribution shift via PSI once 20+ calls
  are logged. This is the retraining trigger for now; an automated retraining
  loop isn't built because there's no usage volume yet to justify one.
- **Documented, not coded: where models run in production.** In-process,
  same as the Outcome Model already does — right for single-user/local now,
  revisit only when this becomes a real multi-tenant service. See
  `ml/README.md`'s "Where trained models run in production" section.

**Still blocked, unchanged from the second pass**: Claim Model and Risk
Model training (`ml/scripts/train_claim_model.py`, `train_risk_model.py`) —
both need `huggingface.co`, still unreachable from this sandbox. Same
commands as before, run them on a machine with normal internet access.

**Verified this pass**: `pytest tests/` → 18/18 passed with zero environment
variables set (12 → 14 after the second pass's ML tests → 18 after this
pass's eval-harness tests). A live `TestClient` run against every route with
no credentials configured showed the same clean degradation as before,
including the new `/reports/{id}/decision` endpoint (503, not a crash,
when Neon isn't configured). `frontend`: `npm install`, `tsc -b`, and
`vite build` all succeed cleanly with the Dashboard changes. A full AST
syntax check of every `.py` file in the repo (including the newly-quarantined
`legacy/` folder) found zero syntax errors.

**One real bug caught by actually running this, not just reading it**: the
firm-personalization block was first written earlier in `run_due_diligence()`
(right after the specialist agents), before `report["final_score"]` is
computed later in the same function — it would have scored every report
against a hardcoded default of 50 instead of the report's real score. Moved
to after `final_score` is set, and the mocked end-to-end run confirmed the
fix (`ventureflow_agent.py`'s "Firm-personalization ranking" comment block
notes why it's placed where it is).
