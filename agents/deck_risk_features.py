"""Structured features for risk detection, and the leakage audit for each one.

WHY FEATURES AT ALL

The text-only disclosure model scores 0.992 AUC on SEC filing prose and 0.667 on
deck prose. It solved the register it was trained on and did not transfer, which
is expected: 941 training excerpts are all SEC filings, and a founder does not
write like a securities lawyer. Collecting thousands of real pitch decks to
balance that corpus is not available -- only seven genuine decks could be
scraped at all, and six well-known ones have no text layer.

So the deck register gets structured features instead of more text. The
quantities that make a deck risky are arithmetic (2.7 months of runway, 79% of
revenue in one account) rather than vocabulary, and `agents/deck_financials`
already computes them deterministically from the same text.

THE LEAKAGE AUDIT

Every candidate feature is recorded below with an explicit verdict, kept or
rejected, because this project has already shipped one leaking model: the
Outcome Model's `team_size` and `age_years` encoded hindsight -- a company that
survived long enough to grow a team looks different from one that died young,
and the model was reading the outcome rather than predicting it.

The test applied here is different from that one and worth stating precisely.
The target is "does THIS paragraph disclose a material risk". A feature computed
from the paragraph itself cannot leak future information, because there is no
future involved -- it is a property of the input, not of the outcome. What CAN
leak here is *label construction*: the corpus labels come from the retrieval
phrase that surfaced each excerpt, so any feature derived from that phrase would
hand the model its own label.

That distinction is why `retrieval_phrase`, `form`, `accession` and `cik` are
rejected below while `runway_months` is kept.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.deck_financials import deck_risk_signals, derive_state

# (feature, verdict, reasoning). Reproduced in the model report so the audit
# travels with the numbers rather than living only in a commit message.
LEAKAGE_AUDIT: list[dict[str, str]] = [
    {
        "feature": "runway_months",
        "verdict": "KEPT",
        "reasoning": "Computed from cash and burn stated in the same paragraph. A "
                     "property of the input text, not of any outcome. Cannot encode "
                     "hindsight because no future information is involved.",
    },
    {
        "feature": "burn_multiple",
        "verdict": "KEPT",
        "reasoning": "Annualised burn over annualised revenue, both parsed from the "
                     "same paragraph. Same reasoning as runway_months.",
    },
    {
        "feature": "largest_customer_share",
        "verdict": "KEPT",
        "reasoning": "Concentration stated in the paragraph, as a percentage or as an "
                     "amount against a stated total. This is the exact quantity the "
                     "keyword dictionary could not see, and it is disclosed by the "
                     "author rather than observed after the fact.",
    },
    {
        "feature": "growth_multiple",
        "verdict": "KEPT",
        "reasoning": "Current over prior revenue, both stated in the paragraph. Note "
                     "it is a WEAK risk signal in both directions and is included for "
                     "the model to weigh, not because its sign is known in advance.",
    },
    {
        "feature": "has_revenue / has_burn / has_cash (presence indicators)",
        "verdict": "KEPT",
        "reasoning": "Whether a figure was disclosed at all. Missingness is itself "
                     "informative and the alternative -- imputing a number -- would "
                     "invent a fact the document does not contain.",
    },
    {
        "feature": "deck_signal_count (by category)",
        "verdict": "KEPT, WITH A STATED CAVEAT",
        "reasoning": "Counts from deck_risk_signals, which is a rule-based detector "
                     "for the same target. This is not leakage -- the rules read only "
                     "the input text and encode no outcome -- but it does mean the "
                     "model partly wraps those rules, so any gain must be compared "
                     "against the rules alone, which the ensemble arm already does.",
    },
    {
        "feature": "retrieval_phrase",
        "verdict": "REJECTED -- LABEL LEAKAGE",
        "reasoning": "The corpus label IS the retrieval phrase's bucket. Feeding it in "
                     "hands the model its own label and would produce a near-perfect "
                     "in-distribution score that means nothing. This is the single "
                     "most dangerous feature available and the easiest to add by "
                     "accident.",
    },
    {
        "feature": "form (10-K / 10-Q / 8-K)",
        "verdict": "REJECTED -- LABEL LEAKAGE BY CORRELATION",
        "reasoning": "Form type correlates strongly with the labelling functions used "
                     "to build the corpus -- most 8-K queries are positives. The model "
                     "would learn the collection procedure, not the risk.",
    },
    {
        "feature": "accession / cik / filing_date",
        "verdict": "REJECTED -- IDENTITY, NOT SIGNAL",
        "reasoning": "Document and company identifiers let the model memorise which "
                     "filings were sampled. They also do not exist for a pitch deck, "
                     "so a model relying on them could not run on the product's actual "
                     "input.",
    },
    {
        "feature": "text length",
        "verdict": "REJECTED -- ARTEFACT OF COLLECTION",
        "reasoning": "Excerpt length is set by this project's own windowing "
                     "(MIN_CHARS/MAX_CHARS) rather than by the source document, so it "
                     "encodes how the corpus was cut, not what the text says.",
    },
    {
        "feature": "specialist agent confidence",
        "verdict": "REJECTED FOR THIS MODEL -- NOT AVAILABLE AT SCORING TIME",
        "reasoning": "Considered because Part F asks about specialist outputs. Rejected "
                     "because risk scoring runs BEFORE the specialists in the pipeline, "
                     "so the feature would not exist when it is needed; and the "
                     "benchmark's 28 excerpts are bare paragraphs with no specialist "
                     "run behind them, so it could not be evaluated honestly either.",
    },
]

FEATURE_NAMES = [
    "runway_months", "runway_known",
    "burn_multiple", "burn_known",
    "largest_customer_share", "concentration_known",
    "growth_multiple", "growth_known",
    "has_revenue", "has_cash",
    "n_deck_signals", "n_high_severity_signals",
    "sig_financial", "sig_operational", "sig_management", "sig_legal",
]


def extract_features(text: str) -> list[float]:
    """Structured features for one excerpt, derived only from that excerpt.

    Missing values are encoded as 0.0 alongside an explicit `*_known` indicator
    rather than imputed, so "no runway stated" and "runway of zero months" stay
    distinguishable -- they are opposite facts.
    """
    state = derive_state(text)
    signals = deck_risk_signals(text, state)
    by_category = {}
    for signal in signals:
        by_category[signal["category"]] = by_category.get(signal["category"], 0) + 1

    def known(value: Any) -> float:
        return 1.0 if value is not None else 0.0

    # Runway is capped: an unbounded value would let one 600-month outlier
    # dominate a linear model's scaling.
    runway = state.runway_months
    burn_multiple = state.burn_multiple

    return [
        min(float(runway), 60.0) if runway is not None else 0.0,
        known(runway),
        min(float(burn_multiple), 50.0) if burn_multiple is not None else 0.0,
        known(burn_multiple),
        float(state.largest_customer_share) if state.largest_customer_share is not None else 0.0,
        known(state.largest_customer_share),
        min(float(state.growth_multiple), 50.0) if state.growth_multiple is not None else 0.0,
        known(state.growth_multiple),
        1.0 if state.annual_revenue else 0.0,
        1.0 if state.cash_on_hand else 0.0,
        float(len(signals)),
        float(sum(1 for s in signals if s.get("severity") == "HIGH")),
        float(by_category.get("financial_risk", 0)),
        float(by_category.get("operational_risk", 0)),
        float(by_category.get("management_risk", 0)),
        float(by_category.get("legal_risk", 0)),
    ]


def audit_table() -> list[dict[str, str]]:
    return list(LEAKAGE_AUDIT)


if __name__ == "__main__":
    import json

    print(json.dumps(LEAKAGE_AUDIT, indent=2))
    sample = ("Financials. Monthly burn is currently $410K against $38K in monthly "
              "recognised revenue. Cash on hand at the end of last month was $1.1M.")
    print("\nfeatures:", dict(zip(FEATURE_NAMES, extract_features(sample))))


class DeckFeatureTransformer:
    """`extract_features` as a scikit-learn transformer.

    Lives HERE, in an importable module, rather than inside the training
    script. That is not a style preference -- it is a correctness requirement
    that cost a silent outage to learn.

    A class defined in a script run as `__main__` is pickled by reference as
    `__main__.DeckFeatureTransformer`. The training script runs as `__main__`,
    so the saved model referenced a class that resolves in no other process:
    `agents/risk_disclosure` loaded it, hit an unpickling error, and -- exactly
    as its degradation contract promises -- reported `available: False` and
    returned None for every severity score. The product silently lost its
    severity model while every test and benchmark still passed, because the
    benchmark harness re-trained rather than re-loaded.

    Defined as a plain duck-typed class rather than subclassing
    BaseEstimator/TransformerMixin so that unpickling needs only this module and
    not a matching scikit-learn class hierarchy.
    """

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        import numpy as _np

        return _np.asarray([extract_features(t) for t in X], dtype=float)

    def get_params(self, deep=True):
        return {}

    def set_params(self, **params):
        return self
