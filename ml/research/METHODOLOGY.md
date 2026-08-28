# VentureFlow — methodology, and what is and is not established

**Last updated: 28 August 2026.** This is the canonical document. Where
`FIELD_NOTES.md`, `ml/README.md`, or any UI copy disagrees with it, this is
correct and the other is a bug.

It is written to be audited by someone who does not trust the author. Every
number below names the script that produced it and the artifact it is recorded
in, so any claim can be recomputed rather than believed.

---

## 1. What the product does

Upload a pitch deck → extract text and structured fields → verify factual claims
against live web search → detect risk signals → run four specialist LLM agents →
produce a 0–100 score → synthesise an investment memo.

**Stack:** FastAPI on Render, React/Vite on Vercel, Neon Postgres. Groq
(`openai/gpt-oss-120b`) is the only LLM provider. All data sources are free or
public.

---

## 2. Data, and where every piece came from

| Dataset | n | Source | Used for |
|---|---|---|---|
| YC outcome dataset | 1,560 | `yc-oss/api` (public) | Outcome Model training |
| VentureScore dataset | 1,298 | Same, tech-filtered | VentureFlow Score training |
| Risk training corpus | 941 excerpts, 614 filings | SEC EDGAR full-text search | Risk disclosure model |
| Risk benchmark | 28 excerpts | 22 real SEC + 6 deck-register, hand-labelled | Risk eval (never trained on) |
| Claim benchmark | 150 claims | Hand-labelled | Claim verifier eval |
| Real deck corpus | 7 decks | `media.genppt.com` (**third-party aggregator**) | Deck-level diagnostics |

**Deck corpus provenance is weaker than the rest and is not fixed.** The decks
come from a re-hosting aggregator, not first-party publication. An attempt to
source first-party decks largely failed; see §7.

---

## 3. What is genuinely validated

Every figure here is out-of-sample unless labelled otherwise.

### 3.1 Scoring models

| Model | AUC | 95% CI | n | Artifact |
|---|---|---|---|---|
| Outcome Model | **0.6459** | [0.5841, 0.7084] | 312 | `ml/eval/validation/out_of_sample_verified.json` |
| VentureFlow Score | **0.6356** | [0.5617, 0.7021] | 261 | same |
| `_legacy_formula_score` | 0.5000 | — | 261 | same |

Produced by `ml/scripts/verify_out_of_sample.py`, which prints train/test
overlap counts by identifier rather than asserting disjointness (index overlap
0; name overlap 0 for VentureScore, 2 for the Outcome Model out of 1,560).

The legacy formula's 0.5000 is exact and structural: it reads no company
feature, so every company receives an identical score and every pair ties.

**Scope limit that must travel with these numbers.** The VentureFlow Score
holdout is a *leftover* — companies absent from the training file — and its
composition is Consumer 162, Healthcare 62, Industrials 28, Real Estate 8, and
**zero B2B, zero Fintech**. The tech-only filter kept those for training. So
0.6356 is a genuine out-of-sample measurement on a population this product is
largely *not* aimed at. **Nothing here establishes performance on B2B or
Fintech decks.**

### 3.2 Risk detection

Measured on the 28-excerpt hand-labelled benchmark, which is disjoint from
training by text hash, containment, and EDGAR accession.

| detector | F1 | boilerplate FP | ranking AUC |
|---|---|---|---|
| Risk/Tone (retired) | 0.000 | 0.000 | **0.333** — below chance |
| keyword dictionary | 0.815 | 0.077 | 0.836 |
| keyword + deck financials | 0.933 | 0.077 | 0.941 |
| **shipped ensemble** | **0.933** | **0.077** | **0.990** |

Subgroup AUC for the trained disclosure model, which must not be averaged:
**0.992 on SEC filing prose (n=22), 0.667 on deck prose (n=6).** It solved the
register it was trained on and did not transfer, which is why it contributes
*severity ranking only* and gets no vote on whether a risk fired.

### 3.3 Claim verification

- Benchmark accuracy **0.955** on 134 of 150 claims scored
  (`ml/eval/claim_benchmark_results.json`). SUPPORTS and REFUTES precision both
  1.000 — the verifier under-claims rather than over-claims.
- Retrieval on-topic rate **14.1% → 97.0%** after company-scoping and a
  relevance gate (`ml/eval/retrieval_quality_results.json`, 14 real deck claims).
- **Temporal grounding, confirmed live 28 Aug 2026**
  (`ml/eval/temporal_grounding_live.json`): the historical-claim false-positive
  is fixed in both paths. Evidence below in §5.

### 3.4 Memo faithfulness

- **Numeric restatement: 0.9907** over 214 assertions across 38 reports
  (`ml/eval/memo_faithfulness_results.json`). This checks that numbers the memo
  repeats match the structured sections. It is exact and needs no LLM.
- **Entailment of the memo's prose: see §6 for current status.**

---

## 4. What is void, and why

| Number | Status | Reason |
|---|---|---|
| Outcome Model AUC 0.9747 | **VOID** | Measured on a 261-company set drawn from its own training file. All 261 were in training. |
| Score baseline 0.668 vs 0.500 | **VOID (model half)** | `eval_score_baseline.py` samples 300 companies from `venturescore_dataset.jsonl`, the training file. 300/300 in training. The *legacy formula's* 0.500 survives — it reads no features. |
| Risk/Tone model | **RETIRED** | 0.767 accuracy on its own test set, 0.333 AUC on the target task. Task mismatch, per Loughran & McDonald (2011). Kept on disk as a documented negative result. |

Superseded numbers are kept on record with their invalidation attached rather
than deleted.

---

## 5. Signal integrity: does real deck content reach the score?

This project has now shipped three bugs where a field the model consumes was
silently hardcoded, dropped, or truncated. None raised an error; all produced
plausible numbers.

- `stage` hardcoded to `None` — 42 points of the model's range, discarded on
  every analysis ever run.
- `description` truncated to 1,200 characters, flattening `desc_len` to a
  near-constant.
- `burn_rate` extracted, then dropped by `PDFExtractResponse` (Pydantic
  discards undeclared keys), then overwritten by a literal `burn_rate: null`
  in the UI — two independent layers on one field.

`ml/scripts/audit_signal_path.py` now walks every consumed field across every
hop and fails if any is lost. **Result: 12/12 fields reach their consumer**, up
from 3/12 when the audit was first run. It is enforced by
`tests/test_signal_path.py`.

### Extraction honesty

`deck_metadata.py` extracts stage, sector, team size, GitHub URL and domain, and
**abstains rather than guesses**. Measured on the 7-deck corpus for stage and
sector: **3 correct, 0 wrong, 11 not-stated.** Precision over recall is
deliberate — a fabricated stage would move the score 42 points on an invention.

When stage or sector is absent the report says so explicitly
(`venture_score.degraded_note`) rather than presenting the number as though it
were fully specified.

### Temporal grounding, live evidence

Same claim, same evidence, same model, differing only in whether the deck's
vintage was supplied:

| claim | deck date | verdict | confidence |
|---|---|---|---|
| Coinbase "$2M/day" (2012 deck) | *withheld*, old prompt | **REFUTES** | **0.92** ← the defect |
| Coinbase "$2M/day" | supplied | NOT_ENOUGH_INFO | 0.90 |
| Coinbase "$2M/day" | *withheld*, new prompt | NOT_ENOUGH_INFO | 0.90 ← fixed |
| Buffer "800 paying users" (2011) | either | NOT_ENOUGH_INFO | 0.80–0.90 |

Deck vintage inference was also corrected to take the **earliest** plausible
year rather than the first: mean absolute error fell from ~3.3 years to ~1.5
(Buffer and Mint now exact). Coinbase's deck yields no year at all, which is why
the unknown-date prompt branch had to carry the full instruction — and it does.

---

## 6. What is not established

Stated plainly, because these are the things a reader would otherwise assume.

1. **No deck-level outcome validation exists, and none is currently possible.**
   All 7 corpus decks are companies that succeeded. With no negative class there
   is no AUC, no precision, no recall — a model returning a constant would score
   perfectly. See §7.
2. **No B2B or Fintech out-of-sample evidence.** The only genuine holdout has
   zero of both.
3. **The score has never been shown to predict a real deck's outcome.** The
   0.6356 is on YC *metadata*, not decks.
4. **Memo prose entailment**: see the status line in
   `ml/eval/memo_entailment_results.json`. The numeric check (0.9907) measures
   something different and narrower.
5. **The specialist agents' confidence is directionally valid but poorly
   calibrated.** Reproducible (sd 0.02–0.07), correct in sign on all four
   agents, but an adjectives-only deck still scored 0.68–0.78 where the prompt's
   own bands say 0.15–0.34. The prompt was tightened afterward and **that
   revision is unverified**.
6. **`bear_case` confidence does not discriminate** — its rich-vs-thin gap
   (+0.020) is smaller than its own standard deviation.

---

## 7. Why there are no failure decks

Recorded in full in `ml/eval/validation/FAILURE_DECK_SOURCING.md`.

15 publicly-failed companies were probed on the aggregator already in use. One
responded (WeWork), and it extracts to **0 characters across 36 pages** — a deck
of slide images with no text layer. Open search returns post-mortems in the
thousands and decks in the zeroes.

The bias is structural, not effort-limited: decks become public because
companies become famous, and companies become famous by succeeding.

The one realistic path is building an OCR/vision reader, which would unlock
WeWork plus five other known image-only decks.

---

## 8. Operational limits

**A full deck analysis costs ~24,000 tokens against a free-tier ceiling of
8,000 tokens per minute.** The arithmetic is unforgiving: a deck needs at least
three minutes of budget, so no batching or prompt trimming brings it under.

Previously the pipeline spent it all at once and every call after the first
burst returned 429 — six of six real deck runs came back `provider_degraded`
with most of their analysis missing, even at concurrency 1.

`groq_client.TokenPacer` now paces spend across the window. A deck takes three
to four minutes and **completes**, instead of taking forty seconds and arriving
hollow. Disable with `GROQ_PACING=off` on a paid tier.

---

## 9. Do not demonstrate these

| # | Item | Status |
|---|---|---|
| 1 | Claim verification calling a true historical claim false | **CLOSED** — confirmed live, both paths (§5) |
| 2 | Comparables always returning 5 rows | **CLOSED** — similarity floor, honest empty state. But see below. |
| 3 | Decks with no stage silently scoring normally | **CLOSED** — extracted where stated, flagged when absent |
| 4 | Image-only decks processed on empty input | **CLOSED** — rejected with the real reason |
| 5 | Implying validated performance on "tech startups" broadly | **CLOSED in UI/docs** — the population is now named everywhere |
| 6 | Full deck upload degrading mid-analysis | **CLOSED on free tier** via pacing; the deck simply takes ~4 minutes |

**Still true and still worth avoiding live:**

- **Comparables similarity is lexical, not semantic.** Measured: "a commercial
  laundry servicing hotels" scores 0.83 against this corpus while "an AI
  developer tools platform" scores 0.76. The threshold removes the detached
  tail; it does not make the number a relevance measure. The UI now says so.
- **Any claim that the score predicts deck outcomes.** It has never been tested
  and cannot be until failure decks exist.
- **Any B2B or Fintech performance claim.**
- **Scanned decks.** They are rejected cleanly, but they are rejected.

---

## 10. How to reproduce every number here

```
python ml/scripts/verify_out_of_sample.py            # §3.1
python ml/scripts/eval_risk_detector.py              # §3.2
python ml/scripts/verify_temporal_grounding_live.py  # §3.3, §5  (needs Groq)
python ml/scripts/eval_memo_faithfulness.py          # §3.4
python ml/scripts/audit_signal_path.py               # §5
python ml/scripts/diagnose_deck_score_clustering.py  # §5
python ml/scripts/build_validation_harness.py --verify
pytest tests/
```
