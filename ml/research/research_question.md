# The reframed research question

Written 23 Aug 2026, after the first evaluation runs (`ml/eval/`). The point of
reframing is to narrow the claim to what this codebase can now actually
support with measurements, and to drop the parts it cannot.

---

## The question

> **When should a calibrated statistical model be allowed to defer to an
> LLM-synthesised narrative, and when should it not?**
>
> We evaluate a two-part evidence layer — claim verification built on live web
> search plus a general-purpose LLM, and risk detection over document text —
> against hand-labeled benchmarks and stated baselines. On 134 pitch-deck-style
> claims the LLM verifier reaches 0.955 accuracy (SUPPORTS F1 0.950, REFUTES
> F1 0.976, NOT_ENOUGH_INFO F1 0.943), against 0.333 accuracy for a TF-IDF
> entailment model given the identical retrieved evidence — a gap large enough
> that the retrieval-plus-LLM design is not a close call. On 28 hand-labeled
> document excerpts, however, the incumbent keyword dictionary scores F1 0.815
> at a 7.7% boilerplate false-positive rate while the trained tone model ranks
> *below chance* (AUC 0.333), so the same "use a learned model" instinct fails
> completely one component over. Separately, the calibrated outcome model
> reaches ROC-AUC 0.668 on real labeled companies where the pre-ML formula it
> replaced reaches exactly 0.500, because that formula reads no company feature
> at all. **The contribution is the pairing: a characterisation of where an
> LLM evidence layer decisively beats a trained baseline, where it does not,
> and a deferral rule grounded in measured confidence separation rather than in
> the assumption that the newer component is the better one.**

---

## Why this wording, and what the results forced to change

The brief's draft question assumed the LLM layer would be the thing under
suspicion and the statistical model the thing being protected. The measurements
partly invert that.

**Claim verification: the LLM wins decisively, and this is not a close
result.** 0.955 vs 0.333 accuracy on identical evidence, and REFUTES F1 0.976
vs 0.000. REFUTES is the class that matters for diligence — it is the one that
catches a founder overstating — and the TF-IDF baseline never detects it, on
this benchmark or on SciFact (F1 0.05). Lexical overlap cannot represent
negation or relation. That was already this repository's documented hypothesis;
it is now measured in the target domain rather than inferred from a different
one.

**Risk detection: the trained model loses to a keyword list.** F1 0.815 vs
0.000, and the tone model's ranking AUC of 0.333 means it ordered risky text
*below* risk-free text. "Prefer the learned component" would have been exactly
the wrong call here. The reason is domain shift — financial *news* sentiment
does not transfer to filing prose — and Loughran & McDonald established that in
2011, which is a reminder that the reframed question should be answered with
reference to the literature rather than by rediscovering it.

**A negative result that changed with sample size, and matters for the
deferral rule.** On the original 30-example benchmark, verifier confidence
averaged 0.901 when correct and 0.890 when wrong — a 0.011 gap, i.e. stated
confidence carrying no usable signal, which would have made confidence-gated
deferral impossible. On 134 examples it averaged 0.890 when correct and 0.567
when wrong: a **0.323 gap**, and re-checking at 134 rather than trusting the
126 figure was the point: a number that has already flipped once has to be
shown to have settled. The small-benchmark reading was not a noisier
version of the right answer, it was the wrong answer, because it averaged over
two errors. Any deferral rule built on the 30-example number would have been
built on noise.

**One result the brief anticipated and the data did not support.** The draft
allowed for "if the LLM verifier doesn't clearly beat the TF-IDF baseline, say
that." It does clearly beat it. The honest negative results are elsewhere: the
risk tone model, the outcome model's 0.058 AUC drop once hindsight features
were removed, and the fact that the memo — the product's most visible output —
is still not evaluated at all.

---

## What the question deliberately excludes

- **The investment memo.** It is LLM-synthesised, unattributed, and has no
  faithfulness measurement. Including it would be claiming an evaluation that
  does not exist. FActScore and ALCE (`related_work.md` §3) are the right
  instruments and neither has been applied.
- **Outcome prediction as a contribution.** ROC-AUC 0.646 post-leakage-fix, on
  a YC-only population, against a coarse survived-or-exited label. Below
  published work on richer data. It is a component of the system, not a result.
- **The four specialist agents.** Unvalidated LLM judges producing scores the
  report renders as measurements. They should be either evaluated or presented
  differently, and until then they are outside the claim.
- **Anything about VC decision quality.** No outcome data links this tool's
  output to investment results, and none will exist for years.

---

## What would have to be true to strengthen it

1. **Finish the benchmark.** 134 of 150 claims are scored; 16 remain, blocked
   only on Groq's free-tier daily token cap, which releases about 8,760
   tokens/hour against roughly 4,000 needed per claim. The headline numbers
   should be restated on the full set, though the 126 → 134 step moved every
   metric by ≤ 0.004, so the remaining 16 are unlikely to change a conclusion.
2. **Contrastive evidence pairs** (VitaminC-style), to test whether the
   verifier is sensitive to evidence or to topic overlap. Nothing here
   currently distinguishes those.
3. **A second annotator** on both benchmarks. Every label is currently
   single-annotator with no agreement figure.
4. **A reliability diagram and ECE for the verifier's stated confidence**, not
   just a mean-gap. A gap between two means is not calibration in Guo et al.'s
   sense, and the deferral rule needs the stronger property.
5. **Evaluate the memo**, or stop describing the product as evidence-grounded
   end to end. Half of it is; the half a VC actually reads is not.
