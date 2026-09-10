# Evaluation benchmarks

Two hand-labeled benchmarks and the harnesses that score them. Both were built
because the audit's top finding was that this project had an evaluation
framework and no evaluation: the claim harness existed and had never been run
end to end, and risk detection had no benchmark at all.

Everything here follows one rule, the same one `ml/research/` follows: **a
number in a write-up must be reloadable from a committed artifact.** Every run
writes its raw per-example output next to the script that produced it, so any
figure can be recomputed without trusting a log line.

---

## 1. Claim verification

| File | What it is |
|---|---|
| `claim_benchmark.jsonl` | 150 hand-labeled claims — 49 SUPPORTS, 51 REFUTES, 50 NOT_ENOUGH_INFO (after one label correction; see below) |
| `claim_benchmark_v1_30.jsonl` | The original 30-example set, kept so the "before" number stays reproducible |
| `claim_benchmark_results_v1_30.json` | The 30-example run — the first time this harness was ever executed |
| `claim_benchmark_results.json` | The expanded run. Carries `complete` and `n_scored`; currently 134 of 150, the rest blocked on the daily token cap |
| `claim_benchmark_results.partial.jsonl` | Append-only per-claim log; a run resumes from it |
| `claim_baseline_results.json` | TF-IDF Claim Model vs the LLM verifier, on identical evidence |

```bash
python ml/scripts/eval_claim_verifier.py                    # the 150-example set
python ml/scripts/eval_claim_verifier.py \
    --benchmark ml/eval/claim_benchmark_v1_30.jsonl \
    --out ml/eval/claim_benchmark_results_v1_30.json        # reproduce the "before"
python ml/scripts/eval_claim_model_baseline.py              # the TF-IDF baseline
```

### How the labels were built

**SUPPORTS (50) and REFUTES (50)** are well-documented public facts about real
technology companies — founding dates, IPOs, acquisitions, product launches,
legal outcomes — chosen because a competent web search should not find them
ambiguous. "Stripe was founded in 2010 by Patrick Collison and John Collison"
(SUPPORTS); "Google was founded in 1995 by Mark Zuckerberg" (REFUTES). Each
label was assigned by hand and each REFUTES claim is false in a specific,
checkable way rather than merely vague.

**NOT_ENOUGH_INFO (50)** splits into two deliberately different sub-categories,
and the split matters more than the count:

- **`nonexistent_company` (25)** — invented companies (Northwind Analytics,
  Cindervale Energy, Kestrelbridge Payments) making plausible pitch-deck claims
  about ARR, churn, pilot results and certifications. A search correctly finds
  nothing because there is nothing to find. This is the original set's style,
  and its weakness was already recorded in the previous version of this file:
  the examples are *structurally* different from the other two classes, because
  there is no real company at all.

- **`obscure_real_company` (25)** — **the sub-category added in the expansion,
  and the one that matters for the product's actual use case.** Real, genuinely
  obscure Y Combinator companies drawn from `ml/data/outcome_dataset.jsonl`
  (Siasto, Picwing, Zumo Labs, Nextop IO, Talentdrop, Faction Technology …),
  each paired with a specific, plausible, and publicly undocumented metric:
  "Roost's web push notification service delivered more than one billion
  notifications." The company is real, so a search returns *something* — a YC
  directory page, a Crunchbase stub, a dead homepage — and the verifier has to
  decide that finding the company is not the same as finding the claim. That
  is precisely the judgement an early-stage diligence tool has to make on every
  deck it sees, and the `nonexistent_company` set cannot test it, because there
  the correct answer is available from the absence of any result at all.

  **Label honesty for this sub-category.** These are labeled NOT_ENOUGH_INFO
  because no public source states the specific figure, not because the company
  is unknown. A SUPPORTS prediction here is a false corroboration — the
  dangerous error for this product. A REFUTES prediction would mean the search
  surfaced a contradicting figure, in which case the gold label is wrong and
  should be corrected; the per-claim `reasoning` and `sources` in the results
  file are kept so that check is possible after each run.

The file is stored **interleaved by class** (s1, r1, n1, o1, s2, …) rather than
grouped. This is not cosmetic. The run is rate-limited by a free-tier daily
token ceiling and can stop partway; grouped, a partial run yields 50 SUPPORTS
and nothing else, and its per-class metrics are meaningless. Interleaved, any
prefix is a roughly balanced subsample.

### Honest limitations

- 150 examples is enough to catch a systematically broken verifier and to
  compare two systems. It is not enough for fine-grained calibration claims.
- SUPPORTS/REFUTES skew to prominent companies. Prominent facts are easy; the
  product's real input is obscure. The `obscure_real_company` subset partly
  offsets this and 25 examples is still small.
- No contrastive pairs (cf. VitaminC, `ml/research/related_work.md` §2), so
  nothing here tests whether the verifier is actually sensitive to evidence
  rather than to topic overlap.
- Labels are single-annotator. There is no inter-annotator agreement figure and
  it would be wrong to imply one.

### Running it

Needs a working `GROQ_API_KEY` and internet access for DuckDuckGo. Two
operational notes learned the hard way:

- **The harness refuses to score a provider outage.** When Groq's daily token
  cap is hit, `agents/claim_verifier.py` degrades to `NOT_ENOUGH_INFO` at
  confidence 0.0 — indistinguishable in a results file from a real verdict. The
  first 150-example attempt hit the cap at claim 36 and recorded 14 such rows
  before this guard existed; they would have depressed SUPPORTS recall and
  inflated NOT_ENOUGH_INFO precision by an amount that is not a property of the
  verifier at all. The harness now waits and retries, then raises rather than
  writing them.
- **Groq's free-tier daily token limit is scoped to the organization, not the
  API key.** Issuing a new key inside the same org does not reset it.

`tests/test_eval_claim_verifier.py` unit-tests the metrics computation against
synthetic rows with no network and no LLM, so that part is verified wherever
this runs.

---

## 2. Risk detection

| File | What it is |
|---|---|
| `risk_benchmark.jsonl` | 28 hand-labeled excerpts — 15 genuine red flags, 13 risk-free boilerplate |
| `risk_excerpts_raw.jsonl` | The raw retrieved paragraphs, with filer and EDGAR URL for each |
| `risk_benchmark_results.json` | Latest run |
| `risk_benchmark_results_before_textfix.json` | The as-shipped LLM detector, before it was given the document text |

```bash
python ml/scripts/collect_risk_excerpts.py    # re-pull the raw excerpts from EDGAR
python ml/scripts/build_risk_benchmark.py     # apply the hand labels
python ml/scripts/eval_risk_detector.py       # score all detectors
```

### How it was built

**22 of the 28 excerpts are real text from real SEC filings**, pulled from
EDGAR full-text search by `ml/scripts/collect_risk_excerpts.py` and traceable
to their filing by the `url` field. The remaining 6 are pitch-deck-register
paragraphs written for this benchmark and labeled as such in `source`, because
SEC filings cover none of the product's actual input: decks assert rather than
disclose, and a risky deck is risky for what it quietly admits, not for its
legal vocabulary.

The retrieval query that found an excerpt is **not** its label. Labels were
assigned by reading each excerpt, and several disagree with the bucket that
retrieved them — `sec_restatement_bam` was retrieved by a red-flag query and is
labeled MEDIUM rather than HIGH because the paragraph discloses a real prior
restatement while concluding controls were effective; several excerpts
retrieved by boilerplate queries are saturated with risk vocabulary and are
labeled risk-free precisely because saying "could have a material adverse
effect" about the weather discloses nothing. Each label carries a one-line
`rationale` so a reviewer can disagree with a specific judgement rather than
with the file.

### The boilerplate half is the point

The 13 risk-free excerpts were chosen to be **hard negatives**: a
Private Securities Litigation Reform Act safe-harbour paragraph, an ASC 606
revenue-recognition note, a critical audit matter, a macro "general economic
conditions" risk factor, a "we face intense competition" risk factor, an
Item 2.02 earnings furnish, routine board appointments. All are stuffed with
the vocabulary a keyword detector keys on and none discloses anything.

Recall is the easy metric here and the misleading one — a detector that flags
everything scores perfect recall and is useless on documents that are mostly
hedged prose. So the headline number reported alongside precision/recall/F1 is
the **boilerplate false-positive rate**, which was completely unmeasured before
this benchmark existed. See `ml/research/related_work.md` §6 for why this
follows from Loughran & McDonald (2011) rather than being a new idea.

### Honest limitations

- 28 examples. Small enough that one label change moves F1 by ~0.03.
- Single-annotator, no agreement figure.
- The SEC half skews to small-cap filers, because those are what a full-text
  search for distress language surfaces. Large-cap disclosure prose is more
  lawyered and probably harder.
- The LLM detector is scored **without** the web-search step the production
  `score_risk()` performs, so its number is not the production number — a
  benchmark excerpt is a paragraph, not a company to search for, and leaving
  search in would measure DuckDuckGo's mood that minute.
- Severity labels (`gold_severity`) are recorded but not currently scored by
  the harness; only the binary risk/no-risk decision and the category overlap
  are.

---

## 3. Post-run label review (23 Aug 2026)

The `obscure_real_company` section above commits to re-reading the retrieved
evidence after each run and correcting any gold label the evidence contradicts.
That review was done on the 128-claim run and **found two of my own labels
wrong.** Both are recorded here rather than quietly fixed, because a benchmark
whose corrections are invisible is not auditable.

**`r25` — "SpaceX is a publicly traded company listed on Nasdaq."** Labeled
REFUTES. The verifier returned SUPPORTS at 0.97 confidence, citing sources
saying SpaceX listed on Nasdaq under SPCX in June 2026. Checked independently:
the verifier is right and the label was wrong — written from knowledge that
predates the listing. This is the exact failure this project's honesty standard
exists to catch, and the benchmark caught it in the direction that matters: the
system was right and the human was wrong. Replaced with a durably false claim
about Falcon 9 reuse, so the item cannot silently flip again, and re-queued.

**`o24` — "Snipd's content-clipping tool had 60,000 registered users."**
Labeled NOT_ENOUGH_INFO for the YC Summer 2008 company Snipd. The verifier
returned REFUTES, citing "over 500,000 knowledge workers" — for a *different*,
much better-known modern product also called Snipd. The verdict was reasonable
on the evidence and the benchmark item was defective: a name collision, not a
thin-evidence case. Rewritten to name the YC batch explicitly, and re-queued.

The other six errors were reviewed and left alone, because they are real system
behaviour rather than label defects:

- **Two (`r1`, `s35`) retrieved zero sources.** `verify_claim` forces
  NOT_ENOUGH_INFO when nothing comes back, so these are DuckDuckGo throttling
  showing up as verifier errors. The `retrieval.claims_with_zero_sources`
  figure in every results file exists to keep that visible: 6 of 134 on this
  run.
- **Four (`s9`, `s10`, `s29`, `r35`) are the verifier being strictly literal
  about conjunctions.** It found that Tesla *produced* its millionth vehicle in
  March 2020 and refused to affirm *delivered*; found Notion's $50M-at-$2B round
  and refused to affirm it was the Series C; confirmed Lyft's March 2019 IPO but
  had no Uber IPO date in the retrieved set and so would not affirm "before
  Uber". Each is arguably pedantic and each errs toward NOT_ENOUGH_INFO rather
  than toward a false SUPPORTS. **For a diligence tool that is the safe
  direction**, and it is visible in the confusion matrix as recall loss on
  SUPPORTS with precision 1.000 — the verifier under-claims rather than
  over-claims. That is a property worth keeping, not a bug to tune away.

---

## 4. Memo faithfulness

| File | What it is |
|---|---|
| `memo_faithfulness_results.json` | Every checked assertion, its memo value, the report's own value, and the verdict |

```bash
python ml/scripts/eval_memo_faithfulness.py              # every stored report
python ml/scripts/eval_memo_faithfulness.py --report-id 65
```

The memo is the half of this product a VC actually reads, and it was the only
component with no evaluation of any kind. `ml/research/research_question.md`
excludes it from the project's claims for exactly that reason. This closes part
of the gap.

### What it measures, and what it does not

The memo restates facts the pipeline already established — the score and its
components, the risk level, how many claims were checked and how many held up.
Those are numbers the report already contains, so agreement is exact and needs
no LLM. **Where the memo and the section disagree, the memo is wrong by
construction**: the section is the source, the memo is the retelling.

It does **not** evaluate whether the memo's free prose is entailed by the
retrieved evidence. That needs atomic-claim decomposition and an entailment
model (FActScore, ALCE — `ml/research/related_work.md` §3), which costs LLM
calls the free-tier quota cannot currently afford. This instrument costs
nothing, so it runs over every stored report today and over every future one
for free.

A memo that simply does not restate a fact is **not** penalised. Only
`SUPPORTED` and `CONTRADICTED` enter the ratio; unrestated facts are recorded as
`NOT_ASSERTED`.

### Result: 0.991 over 214 assertions in 38 reports

212 supported, 2 contradicted.

**Both contradictions are real, and they are the same bug.** On reports 36 and
39 the memo quotes a score the product does not show:

| Report | Memo says | Report headline | Why |
|---|---|---|---|
| ComplyForge AI (36) | 57 / 100 | **30** | `incomplete_analysis` capped it |
| AgroPulse (39) | 33 / 100 | **30** | same |

`ventureflow_agent.py` applies `final_score = min(final_score, 30)` when
`incomplete_analysis` is set, and the memo is synthesised from the *uncapped*
model score. So the memo can present a materially more favourable number than
the product's own headline — 57 against 30 — and it does so precisely on the
reports where verification was too incomplete to trust the estimate. The error
runs in the least safe direction available.

### The first run was wrong, and that is why the tests exist

The evaluator's first pass reported **33 contradictions**, and every one was the
instrument misreading the memo rather than the memo misreading the report:

- a bare `N/100` pattern matched the fallback memo's `data quality (85/100)`,
  on 25 of 38 reports;
- `| **REFUTED** | 90 % |` in a per-claim table was read as a refuted *count*
  of 90;
- `| **High** |` in a risk table was read as the score's confidence band;
- another company's `Risk score 30 / 100` in a comparables table was read as
  this company's.

The common cause was matching inside markdown table rows. None of the facts
checked here is ever legitimately stated in a table row in these memos, so
`_search` now skips any match whose line contains a pipe, and the headline-score
pattern requires an explicit label.

Each of those four cases is pinned by name in
`tests/test_memo_faithfulness.py`. **An evaluator that invents contradictions is
worse than no evaluator**, because its output looks like evidence — so the
regression tests matter more here than the headline number.

### Honest limitations

- Exact restatement only. Prose faithfulness is unmeasured.
- 38 reports from one deck corpus, mostly generated during development.
- The comparables check (`no_fabricated_comparable`) is reported but never
  scored: capitalised prose produces too many false positives for it to be a
  pass/fail signal, so it is a pointer for a human rather than a number.

### Label corrections

Corrections are recorded here and on the row itself (`label_note`), never made
silently. A corrected label changes every accuracy figure computed from the
benchmark, so a reader must be able to see what changed, when, and on what
evidence.

| id | was | now | evidence |
|---|---|---|---|
| s10 | SUPPORTS | REFUTES | "Notion raised a Series C funding round in 2020 at a $2 billion valuation." The April 2020 raise was $50M at $2B and was not a Series C; Notion's Series C was the $275M round of October 2021. A true valuation attached to the wrong round is false as written. Found 11 Sep 2026 when the verifier returned REFUTES citing exactly this. |

Results files produced before a correction were scored against the old label;
they are left as they were rather than rewritten.

