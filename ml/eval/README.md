# Claim-verification benchmark

`claim_benchmark.jsonl` -- 30 hand-labeled claims, 10 each of SUPPORTS,
REFUTES, and NOT_ENOUGH_INFO, evaluated by `ml/scripts/eval_claim_verifier.py`
against the live `agents/claim_verifier.py`.

**How the labels were built, honestly**: the 20 SUPPORTS/REFUTES claims are
about well-documented, high-profile public events (company founding dates,
IPOs, acquisitions, product launches) chosen because they're unlikely to be
ambiguous to a competent web search -- e.g. "Stripe was founded in 2010 by
Patrick Collison and John Collison" (SUPPORTS) or "Google was founded in 1995
by Mark Zuckerberg" (REFUTES, obviously). The 10 NOT_ENOUGH_INFO claims are
about entirely fictional companies I invented for this benchmark
(Northwind Analytics, Bramblecart Inc., etc.) making specific, plausible-
sounding pitch-deck-style claims (ARR figures, churn rates, pilot results) --
a search for these will correctly turn up nothing, because they don't exist.
This is a legitimate way to test the NOT_ENOUGH_INFO class without a public
dataset of intentionally-obscure real claims, but it does mean the
NOT_ENOUGH_INFO examples are structurally different from the other two
classes (no real company at all, vs. real companies with contested facts) --
worth being aware of when reading results, and worth expanding with harder,
real-but-obscure examples over time.

**30 examples is a starting point, not a finished benchmark.** It's enough to
catch a systematically broken verifier (e.g. one that always returns
NOT_ENOUGH_INFO, or one that treats topic similarity as support), but not
enough to draw fine-grained conclusions about calibration. Grow this file as
real usage surfaces claims the verifier got wrong.

**Running it** needs a working `GROQ_API_KEY` and live internet access for
the DuckDuckGo search `agents/claim_verifier.py` depends on -- neither was
available in the sandbox this benchmark was built in. Run:

```bash
python ml/scripts/eval_claim_verifier.py
```

`tests/test_eval_claim_verifier.py` unit-tests the metrics computation itself
against synthetic cases, with no network or LLM calls, so that part is
verified regardless of where this file is run.
