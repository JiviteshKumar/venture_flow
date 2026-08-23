# Related work, and where VentureFlow actually sits

Written 23 Aug 2026, alongside the first end-to-end evaluation runs
(`ml/eval/`). Its purpose is narrow: to let a reviewer place this project in
the literature quickly, and to stop it from claiming novelty it does not have.
Where the honest answer is "this is a known task and we are not advancing the
state of the art on it," that is what this document says.

Every arXiv identifier below was checked against the arXiv API while writing
this file, not recalled. The three non-arXiv finance citations are marked as
such and were **not** re-verified in this session; treat them as pointers to
follow up rather than as checked references.

---

## 1. What this project actually is

Stripped of product framing, VentureFlow's evaluable core is two components:

1. **A claim verifier** — take a natural-language claim from a pitch deck,
   retrieve web evidence for it (DuckDuckGo), and have a general-purpose LLM
   return SUPPORTS / REFUTES / NOT_ENOUGH_INFO with a stated confidence
   (`agents/claim_verifier.py`).
2. **A risk detector** — take a document excerpt and decide whether it
   discloses a material red flag, by keyword dictionary, by a trained tone
   classifier, or by an LLM (`agents/risk_detector.py`).

Around them sit a calibrated statistical model over company metadata
(`ml/venturescore.py`) and an LLM that writes the memo. So the relevant
literatures are fact verification, retrieval-augmented generation
faithfulness/attribution, LLM confidence calibration, and — much more thinly —
startup outcome prediction.

---

## 2. Fact verification: this is a well-established task and we did not invent it

The SUPPORTS / REFUTES / NOT_ENOUGH_INFO label schema this codebase uses is
**FEVER's**, essentially verbatim.

- **FEVER** (Thorne et al., [arXiv:1803.05355](https://arxiv.org/abs/1803.05355);
  shared task [arXiv:1811.10971](https://arxiv.org/abs/1811.10971)) — 185k
  claims over Wikipedia with exactly these three labels. Anyone reading this
  project's benchmark will recognise the schema, and it should be cited as
  inherited rather than presented as a design choice.
- **SciFact** (Wadden et al., "Fact or Fiction: Verifying Scientific Claims",
  [arXiv:2004.14974](https://arxiv.org/abs/2004.14974)) — 1.4k scientific
  claims with cited evidence abstracts. **This is the direct lineage of this
  repository's negative-result baseline**: `ml/scripts/train_claim_model.py`
  trains on SciFact, and `ml/models/claim_model_report.json` records the result
  (45% accuracy, REFUTES F1 0.05). SciFact is also where that model's ceiling
  comes from — it is a scientific-abstract corpus being applied to startup
  claims, which is a domain shift we state rather than paper over.
- **VitaminC** (Schuster et al., "Get Your Vitamin C! Robust Fact Verification
  with Contrastive Evidence",
  [arXiv:2103.08541](https://arxiv.org/abs/2103.08541)) — trains verifiers to be
  *sensitive to evidence*, using contrastive pairs where a small evidence edit
  flips the label. Directly relevant to a failure mode this project's own
  prompt tries to guard against in prose ("topic similarity does NOT mean the
  claim is supported") and does not currently test for. A contrastive slice
  would be a genuine improvement to `ml/eval/claim_benchmark.jsonl`.
- **AVeriTeC** (Schlichtkrull et al.,
  [arXiv:2305.13117](https://arxiv.org/abs/2305.13117); shared task
  [arXiv:2410.23850](https://arxiv.org/abs/2410.23850)) — **the closest prior
  work to what this system does architecturally**: real-world claims verified
  against evidence retrieved from the open web, rather than against a fixed
  Wikipedia snapshot. If one paper should be read before extending this
  project's verifier, it is this one. AVeriTeC decomposes a claim into
  question-answer pairs before judging; VentureFlow issues five fixed query
  templates and hands everything to one judge call. That is a simpler and
  weaker design, and the difference is a concrete avenue rather than a defect
  to hide.
- **A Survey on Automated Fact-Checking** (Guo et al.,
  [arXiv:2108.11896](https://arxiv.org/abs/2108.11896)) — the standard entry
  point for the field, and the right citation for "this pipeline shape is
  conventional."

**Honest positioning.** VentureFlow contributes nothing new to fact
verification as a task. What it has that these datasets do not is a small
benchmark in a *specific commercial domain* — pitch-deck claims about
early-stage companies — including a sub-category (real but obscure companies
with genuinely thin web evidence) that is hard for exactly the reason the
product cares about. That is a narrow contribution, and it is 150 hand-labeled
examples, not a dataset paper.

---

## 3. Retrieval-augmented generation: faithfulness and attribution

The verifier is a RAG system whose output is a verdict rather than prose, so
the RAG-faithfulness literature applies to it almost directly.

- **Measuring Attribution in Natural Language Generation Models** (Rashkin et
  al., [arXiv:2112.12870](https://arxiv.org/abs/2112.12870)) — the AIS
  ("Attributable to Identified Sources") framework. The formalisation of the
  property this product markets: every claim shown with the source that
  supports it.
- **RARR** (Gao et al., [arXiv:2210.08726](https://arxiv.org/abs/2210.08726)) —
  research-and-revise: use retrieval to attribute and then edit a model's
  output. The mirror image of what VentureFlow does — it retrieves to *judge*
  rather than to *revise* — and the natural next step if the memo itself, not
  just the claims, is to be held to an attribution standard. Currently the memo
  is synthesised free-form and is not attributed at all, which is a real gap.
- **ALCE** (Gao et al., "Enabling Large Language Models to Generate Text with
  Citations", [arXiv:2305.14627](https://arxiv.org/abs/2305.14627)) — the
  benchmark for citation-bearing generation. The standard the investment memo
  would have to meet to claim it is evidence-grounded end to end.
- **FActScore** (Min et al., [arXiv:2305.14251](https://arxiv.org/abs/2305.14251))
  — decomposes long-form output into atomic facts and scores each. The right
  method for evaluating the memo, which this project does not evaluate at all.
- **RAGAS** (Es et al., [arXiv:2309.15217](https://arxiv.org/abs/2309.15217)) —
  reference-free RAG evaluation (faithfulness, answer relevance, context
  relevance). Directly usable here and not used.
- **SelfCheckGPT** (Manakul et al.,
  [arXiv:2303.08896](https://arxiv.org/abs/2303.08896)) — sampling-based
  hallucination detection with no external resource. An alternative baseline to
  web retrieval that this project has never compared against, and a fair
  question a reviewer would ask.

**Honest positioning.** The claim-level output is attributed. The memo is not.
Describing the whole product as "evidence-grounded" is therefore true of one
half and aspirational for the other, and the memo has no faithfulness
measurement of any kind.

---

## 4. Calibration and LLM-as-judge

The product's central open question — when should a calibrated statistical
model defer to an LLM narrative — is a calibration question.

- **On Calibration of Modern Neural Networks** (Guo et al.,
  [arXiv:1706.04599](https://arxiv.org/abs/1706.04599)) — where Expected
  Calibration Error comes from. `ml/research/README.md` reports ECE 0.0219 for
  the VentureFlow Score using this definition.
- **Language Models (Mostly) Know What They Know** (Kadavath et al.,
  [arXiv:2207.05221](https://arxiv.org/abs/2207.05221)) — self-evaluated
  correctness carries real signal, under conditions.
- **Can LLMs Express Their Uncertainty?** (Xiong et al.,
  [arXiv:2306.13063](https://arxiv.org/abs/2306.13063)) — the direct caution:
  verbalised confidence is systematically overconfident and poorly calibrated.
  `agents/claim_verifier.py` asks the model for a `confidence` float and the UI
  shows it as a percentage, so this matters here.

  **Measured locally, and the answer changed with sample size — which is the
  more useful finding.** On the 30-example set the verifier's stated confidence
  averaged 0.901 when correct against 0.890 when wrong: a 0.011 gap, no usable
  discrimination, apparently confirming the paper's warning
  (`claim_benchmark_results_v1_30.json`). On 126 examples of the expanded set
  it averaged **0.886 when correct against 0.567 when wrong — a 0.319 gap**
  (`claim_benchmark_results.json`). The confidence *is* informative here.

  The 30-example reading was not a smaller version of the right answer, it was
  the wrong answer, and it was wrong for a structural reason: with only two
  errors in the set, the "incorrect" mean was an average over two numbers. The
  previous `ml/eval/README.md` warned that 30 examples is "not enough to draw
  fine-grained conclusions about calibration" and that warning turned out to be
  exactly right. Verbalised confidence still should not be presented to a user
  as a probability — a mean gap is not calibration in Guo et al.'s sense, and
  no reliability diagram or ECE has been computed for it — but "the model's
  confidence is worthless" is not what this system's data says.
- **Judging LLM-as-a-Judge** (Zheng et al.,
  [arXiv:2306.05685](https://arxiv.org/abs/2306.05685)) — position and
  verbosity biases in LLM judges. Relevant because the four specialist agents
  in `agents/investment_agents.py` are unvalidated LLM judges producing scores
  the report presents as measurements.

---

## 5. Startup outcome prediction

Thin, and mostly not comparable to this project.

- **Startup success prediction and VC portfolio simulation using CrunchBase
  data** ([arXiv:2309.15552](https://arxiv.org/abs/2309.15552)) — already cited
  in `ml/README.md` as the reference point for "AUC 0.70 is in the published
  range, not better." That comparison should be restated now: after the
  leakage fix (23 Aug 2026) the Outcome Model's honest figure is **ROC-AUC
  0.646**, not 0.70, because `team_size` and `age_years` were hindsight
  features (`ml/models/outcome_model_report.json`). The earlier number was not
  comparable to published work in the first place, and neither is the new one
  without knowing how the cited paper handles the same problem — which we have
  not checked.
- **Finding the unicorn: Predicting early stage startup success through a
  hybrid intelligence method** (Dellermann et al.,
  [arXiv:2105.03360](https://arxiv.org/abs/2105.03360)) — human judgement
  combined with machine prediction for early-stage evaluation. The closest
  thing in the literature to this product's actual thesis, and worth reading
  before making any claim about human-plus-model being novel here.
- **Solving the Data Sparsity Problem in Predicting the Success of the Startups
  with Machine Learning**
  ([arXiv:2112.07985](https://arxiv.org/abs/2112.07985)) — same population
  problem (sparse, censored startup data) that forces the right-censoring
  exclusions in `ml/scripts/prepare_outcome_dataset.py`.

**Honest positioning.** Most of this literature trains on Crunchbase, which is
paid and which this project explicitly cannot use. Training on the free
`yc-oss/api` YC directory is a reproducibility advantage and a population
disadvantage — YC companies are pre-selected by YC's own admissions process,
so calibration should not be assumed to transfer. The numbers here are not
better than published work and should not be presented as if they were.

---

## 6. Risk detection in financial text

The risk benchmark (`ml/eval/risk_benchmark.jsonl`) is built from real SEC
filings, which puts it next to a finance-NLP literature this project had not
previously engaged with.

- **Loughran & McDonald (2011), "When Is a Liability Not a Liability? Textual
  Analysis, Dictionaries, and 10-Ks", *Journal of Finance* 66(1).** *(Not
  re-verified in this session.)* Showed that general-purpose sentiment
  dictionaries misclassify financial text badly, because words that are
  negative in ordinary English ("liability", "cost", "capital") are neutral
  accounting vocabulary. **This is, in advance, the explanation for this
  project's own measured negative result**: the trained Risk/Tone model —
  Financial PhraseBank plus Twitter financial news — predicted `neutral` on all
  28 benchmark excerpts, assigning going-concern disclosures a negative
  probability of 0.014–0.071, and ranked *below chance* (AUC 0.333). News-
  sentiment training data does not transfer to filing prose. Loughran and
  McDonald said as much fifteen years ago, and reading them first would have
  predicted the result.
- **Cohen, Malloy & Nguyen (2020), "Lazy Prices", *Journal of Finance* 75(3).**
  *(Not re-verified in this session.)* Year-over-year *changes* in 10-K
  language predict returns, precisely because the baseline text is boilerplate
  that gets copied forward. This is the empirical grounding for making
  boilerplate false-positive rate the headline metric of the risk benchmark
  rather than recall: most risk-factor language carries no information, and a
  detector that fires on it is not detecting anything.

**Honest positioning.** Measuring the boilerplate false-positive rate is not a
novel idea — it follows straightforwardly from Loughran & McDonald. What the
benchmark adds is that it is *measured here, on this system*, where before it
was unmeasured. The finding that the incumbent keyword detector beats the
trained model (F1 0.815 vs 0.0) is a local engineering result, not a
contribution to the literature.

---

## 7. LLM-assisted VC due diligence specifically

Searched for and largely **not found** in peer-reviewed form. There is
practitioner and vendor material, and there is the hybrid-intelligence work
cited in §5, but no established academic benchmark for "LLM reads a pitch deck
and produces a diligence memo."

This is worth stating carefully, because the tempting move is to read the
absence as novelty. It is at least as likely to reflect that the task is
poorly specified as a research problem — there is no agreed ground truth for a
good diligence memo, and the outcome label that would define one arrives years
later and is dominated by factors no deck contains. **A reviewer should read
the absence of prior work here as a reason to be sceptical of the evaluation,
not as evidence that this project is first.** It is also why the reframed
research question (see §8) deliberately narrows to the two components that
*can* be scored against labels, rather than to the memo.

---

## 8. Summary: what is and is not a contribution

| | Status |
|---|---|
| The claim-verification task and its label schema | Inherited from FEVER. Not a contribution. |
| Web-retrieval-based verification of real-world claims | Prior art: AVeriTeC. Our implementation is simpler and weaker. |
| A 150-example pitch-deck claim benchmark, including real-but-obscure companies | Small, domain-specific, hand-labeled. A modest contribution. |
| A 28-example risk benchmark with a measured boilerplate false-positive rate | Method follows Loughran & McDonald. The measurement on this system is new. |
| TF-IDF claim model as a negative result | A clean, reportable negative result, and it **replicates in the target domain**: 0.333 accuracy and REFUTES F1 0.0 on 120 pitch-deck claims, against 0.967 / 0.986 for the LLM verifier on the same claims and the same retrieved evidence. Explained by known domain-shift findings. |
| Risk/Tone model as a negative result | Same. Predicted in advance by Loughran & McDonald. |
| Startup outcome prediction | Below published AUC and on a narrower population. Not a contribution. |
| Leakage control as an explicit, measured decision | Ordinary good practice, applied and quantified (0.048 and 0.058 AUC). Reportable as methodology, not as novelty. |
| An LLM-written diligence memo | Unevaluated. Not a contribution until it is measured (see FActScore, ALCE). |
