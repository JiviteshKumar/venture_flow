"""Turn the pipeline's agent findings into structured numbers the score can use.

WHAT WAS ACTUALLY WRONG -- STATED PRECISELY, BECAUSE THE OBVIOUS FRAMING IS WRONG

It is tempting to say the agents' findings never reach the score and only feed
the memo. That is not true, and building on it would have produced the wrong
fix. `ventureflow_agent._evidence_components()` already converts claim
verification, risk detection, data quality and specialist confidence into a
penalty that adjusts the model probability before the memo is written.

The measured defect is **asymmetry**. Sweeping the evidence inputs from their
worst plausible state to their best:

    worst-case evidence  ->  penalty  +0.785  (clamped to 0.60, i.e. -60 points)
    best-case evidence   ->  penalty  -0.025  (i.e. +2.5 points)

So a deck whose every claim was independently verified, with no risk signals,
disclosed revenue and high data quality, is rewarded 2.5 points -- while a deck
with refuted claims is punished up to 60. The pipeline can prove a company is
sound and barely move the number. That is the gap this module closes.

WHY A BOUNDED RULE AND NOT A FITTED LAYER

A fitted fusion would be better and is not available. Fitting requires examples
labelled with (evidence state, eventual outcome), and this project has seven
decks with outcomes, all seven of which succeeded. Fitting a layer on one class
is not possible, and fitting it on YC metadata would be fitting something else
entirely.

So this stays an explicit, inspectable, bounded arithmetic rule with stated
weights -- the same decision `_evidence_components` documents, for the same
reason -- and every term is reported on the report so a reader can see which one
moved the number. It is NOT a second LLM judgement layered over the first: no
free text enters here, only counts and calibrated probabilities.

THE LEAKAGE THAT MATTERS MOST HERE

One candidate feature is genuinely dangerous and is documented at length below:
**claim corroboration by web search correlates with fame, and fame correlates
with success.** A dead startup has little written about it, so its claims come
back NOT_ENOUGH_INFO; a company that went public has extensive coverage, so its
claims verify. A model rewarding "claims verified" would partly be rewarding
"is already famous", which is not a prediction. It is kept, deliberately, but
capped hard and recorded as the weakest term.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Per-feature leakage verdicts. Written out because this project has already
# shipped one leaking model (the Outcome Model's team_size/age_years), and the
# check that catches it is asking "could this encode the answer rather than
# predict it" of every single feature, out loud.
LEAKAGE_AUDIT: list[dict[str, str]] = [
    {
        "feature": "refuted_fraction",
        "verdict": "KEPT",
        "reasoning": "Proportion of extracted claims that web evidence directly "
                     "contradicted. Derived from the deck's own statements checked "
                     "against sources; it describes what the company claimed and "
                     "whether it held up, not what happened to the company later.",
    },
    {
        "feature": "supported_fraction",
        "verdict": "KEPT, CAPPED, AND FLAGGED AS THE WEAKEST TERM",
        "reasoning": "THE DANGEROUS ONE. Corroboration by public web search is "
                     "confounded with fame: a company that went public has "
                     "extensive coverage and its claims verify, while a company "
                     "that quietly died has almost nothing written about it and "
                     "returns NOT_ENOUGH_INFO regardless of whether its deck was "
                     "honest. Rewarding this partly rewards 'is already famous', "
                     "which is hindsight wearing a prediction's clothes. Kept "
                     "because refusing to credit verified evidence at all is also "
                     "wrong, but capped at the smallest positive weight of any "
                     "term and reported as such.",
    },
    {
        "feature": "unsupported_fraction",
        "verdict": "KEPT, SMALL NEGATIVE WEIGHT ONLY",
        "reasoning": "Proportion of claims the verifier could not resolve either "
                     "way. Carries the SAME fame confound as supported_fraction "
                     "and in the opposite direction: an early-stage company "
                     "nobody has written about returns NOT_ENOUGH_INFO on "
                     "everything, which is a fact about press coverage rather "
                     "than about the company. Kept because a deck of entirely "
                     "uncheckable assertions is genuinely weaker evidence, but "
                     "weighted low for exactly this reason -- it must not become "
                     "a penalty for being early.",
    },
    {
        "feature": "risk_severity",
        "verdict": "KEPT",
        "reasoning": "Calibrated P(this text discloses a material risk) from the "
                     "in-domain disclosure model, read off the deck text itself. "
                     "A property of the document, not of any outcome.",
    },
    {
        "feature": "deck_signal_count",
        "verdict": "KEPT",
        "reasoning": "Deterministic arithmetic on figures the deck states -- "
                     "runway, burn multiple, customer concentration. Self-disclosed "
                     "and contemporaneous with the deck.",
    },
    {
        "feature": "specialist_grounding",
        "verdict": "KEPT, CONDITIONAL ON THE PART D WORK",
        "reasoning": "Mean confidence of specialists that actually answered, which "
                     "is meaningful only because the prompt now defines confidence "
                     "as evidence-grounding rather than leaving it undefined. "
                     "Degraded agents are excluded: a provider failure is not a "
                     "judgement about the company.",
    },
    {
        "feature": "financial_disclosure",
        "verdict": "KEPT",
        "reasoning": "Whether the deck disclosed revenue, burn and runway at all. "
                     "Measures the document's candour, which is available at the "
                     "moment a VC reads it.",
    },
    {
        "feature": "company_age / founded_year",
        "verdict": "REJECTED -- HINDSIGHT",
        "reasoning": "The same right-censoring defect that got team_size and "
                     "age_years excluded from both existing models: older cohorts "
                     "have had longer to resolve, so age encodes how much time the "
                     "outcome had to happen in, not company quality.",
    },
    {
        "feature": "total_sources_retrieved",
        "verdict": "REJECTED -- MEASURES FAME, NOT THE COMPANY",
        "reasoning": "How many pages a search returned is almost purely a function "
                     "of public prominence. It is supported_fraction's confound "
                     "with none of its compensating value.",
    },
    {
        "feature": "memo length / sentiment",
        "verdict": "REJECTED -- LLM JUDGEMENT BY THE BACK DOOR",
        "reasoning": "Any feature read off the synthesised memo would let the "
                     "narrative influence the number it is supposed to be "
                     "explaining, which is the exact inversion the "
                     "score-before-synthesis ordering exists to prevent.",
    },
    {
        "feature": "recommendation / final_score from a previous run",
        "verdict": "REJECTED -- CIRCULAR",
        "reasoning": "Feeding a prior verdict back in makes the score partly a "
                     "function of itself and would drift on re-analysis of an "
                     "unchanged deck.",
    },
]

# Weights, stated rather than fitted. Each is the maximum probability delta that
# term may contribute. Positive weights are deliberately smaller than negative
# ones: this product's job is diligence, and the cost of missing a red flag is
# higher than the cost of under-crediting a good deck.
POSITIVE_WEIGHTS = {
    # Smallest deliberately, and the suite enforces that it stays smallest.
    # Web corroboration is confounded with fame: a company that went public has
    # extensive coverage and verifies easily, while one that quietly died has
    # almost nothing written about it. Rewarding this too heavily would reward
    # "is already famous", which is hindsight wearing a prediction's clothes.
    #
    # An earlier revision had this at 0.06 -- the LARGEST positive weight --
    # while the docstring claimed it was the smallest. The test that compares
    # the two caught the contradiction.
    "supported_fraction": 0.03,
    "financial_disclosure": 0.06,
    "specialist_grounding": 0.06,
    "low_risk": 0.05,
}
NEGATIVE_WEIGHTS = {
    "refuted_fraction": 0.30,
    "risk_severity": 0.12,
    "deck_signal_count": 0.10,
    "unsupported_fraction": 0.08,
}
MAX_POSITIVE = sum(POSITIVE_WEIGHTS.values())   # 0.20 -> +20 points
MAX_NEGATIVE = sum(NEGATIVE_WEIGHTS.values())   # 0.60 -> -60 points


@dataclass
class EvidenceFeatures:
    refuted_fraction: float = 0.0
    supported_fraction: float = 0.0
    unsupported_fraction: float = 0.0
    n_claims: int = 0
    risk_severity: float | None = None
    deck_signal_count: int = 0
    specialist_grounding: float | None = None
    financial_disclosure: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "refuted_fraction": round(self.refuted_fraction, 4),
            "supported_fraction": round(self.supported_fraction, 4),
            "unsupported_fraction": round(self.unsupported_fraction, 4),
            "n_claims": self.n_claims,
            "risk_severity": None if self.risk_severity is None else round(self.risk_severity, 4),
            "deck_signal_count": self.deck_signal_count,
            "specialist_grounding": (
                None if self.specialist_grounding is None
                else round(self.specialist_grounding, 4)
            ),
            "financial_disclosure": round(self.financial_disclosure, 4),
        }


def extract_features(
    claim_results: list[dict[str, Any]] | None,
    risk_result: dict[str, Any] | None,
    specialist_results: dict[str, Any] | None,
    *,
    revenue: float | None = None,
    burn_rate: float | None = None,
    runway_months: float | None = None,
) -> EvidenceFeatures:
    """Structured numbers only. No free text crosses this boundary."""
    # Only claims that were actually CHECKED may move the score.
    #
    # A claim whose verification failed on a provider error carries the verdict
    # NOT_ENOUGH_INFO, which is indistinguishable by verdict alone from "we
    # searched and the web could not settle it". The first is a fact about our
    # infrastructure; the second is a fact about the company. Counting the
    # first as the second is how a working company gets marked down for our
    # outage -- and it did: with the Groq daily quota exhausted, all five of
    # Uber's deck claims failed to a 429, every one landed in `unresolved`, and
    # the resulting evidence penalty took the report from a model prior of 50
    # to a final 35.
    #
    # This mirrors the rule already applied to specialist agents a few lines
    # below ("a degraded agent's zero reflects a provider failure, not a
    # judgement"); it simply was never applied to claims, because the flag it
    # keys on was being dropped in agents/claim_verifier.verify_claim.
    #
    # `n` counts only the checked claims too, so the fractions stay fractions
    # of what was actually established. With every claim degraded, n is 0 and
    # all three fractions are 0.0 -- no penalty, no bonus, which is the honest
    # answer when nothing was verified either way.
    all_claims = claim_results or []
    claims = [
        c for c in all_claims
        if isinstance(c, dict) and not c.get("_degraded")
        # A private operating metric that public sources could not settle
        # ("ARR $11.4M", "We have 40 enterprise customers") says nothing about
        # the company: no private company publishes those numbers. Counting its
        # NOT_ENOUGH_INFO as an unsupported claim penalised every deck for
        # being private. Across the stored claims, 0 of 10 such claims ever got
        # a verdict. A SUPPORTS or REFUTES on one still counts in full.
        and not (c.get("claim_kind") == "internal"
                 and str(c.get("verdict", "")).upper() == "NOT_ENOUGH_INFO")
    ]
    n = len(claims)
    verdicts = [str(c.get("verdict", "")).upper() for c in claims]
    refuted = sum(1 for v in verdicts if v == "REFUTES")
    supported = sum(1 for v in verdicts if v == "SUPPORTS")
    unresolved = sum(1 for v in verdicts if v == "NOT_ENOUGH_INFO")

    risk = risk_result or {}
    severity = risk.get("disclosure_severity")
    try:
        severity = None if severity is None else float(severity)
    except (TypeError, ValueError):
        severity = None

    # Only specialists that actually answered. A degraded agent's zero reflects
    # a provider failure, not a judgement, and averaging it in would re-import
    # the constant-score bug this codebase spent a session removing.
    grounding = None
    if specialist_results:
        answered = []
        for result in specialist_results.values():
            if not isinstance(result, dict) or result.get("_degraded"):
                continue
            try:
                answered.append(float(result.get("confidence", 0)))
            except (TypeError, ValueError):
                continue
        if answered:
            grounding = sum(answered) / len(answered)

    disclosed = sum(1 for value in (revenue, burn_rate, runway_months) if value)

    return EvidenceFeatures(
        refuted_fraction=(refuted / n) if n else 0.0,
        supported_fraction=(supported / n) if n else 0.0,
        unsupported_fraction=(unresolved / n) if n else 0.0,
        n_claims=n,
        risk_severity=severity,
        deck_signal_count=len(risk.get("deck_signals") or []),
        specialist_grounding=grounding,
        financial_disclosure=disclosed / 3.0,
    )


def fuse(model_probability: float, features: EvidenceFeatures) -> dict[str, Any]:
    """Adjust the model's prior by this report's own evidence, both directions.

    Returns the adjusted probability and a full per-term breakdown, because a
    number that moved for reasons a reader cannot inspect is not better than no
    number at all.
    """
    terms: dict[str, float] = {}

    # ── negative: what the evidence found against the company ──────────────
    terms["refuted_claims"] = -NEGATIVE_WEIGHTS["refuted_fraction"] * min(1.0, features.refuted_fraction)
    terms["risk_severity"] = (
        -NEGATIVE_WEIGHTS["risk_severity"] * features.risk_severity
        if features.risk_severity is not None else 0.0
    )
    terms["deck_risk_signals"] = -NEGATIVE_WEIGHTS["deck_signal_count"] * min(1.0, features.deck_signal_count / 3.0)
    terms["claims_unresolved"] = -NEGATIVE_WEIGHTS["unsupported_fraction"] * features.unsupported_fraction

    # ── positive: what the evidence found FOR it ───────────────────────────
    #
    # The half that did not exist. Note every positive term is gated on there
    # being something to credit: an empty analysis earns nothing rather than
    # defaulting to the maximum.
    if features.n_claims >= 2:
        terms["claims_supported"] = POSITIVE_WEIGHTS["supported_fraction"] * features.supported_fraction
    else:
        terms["claims_supported"] = 0.0
    terms["financials_disclosed"] = POSITIVE_WEIGHTS["financial_disclosure"] * features.financial_disclosure
    terms["specialist_grounding"] = (
        POSITIVE_WEIGHTS["specialist_grounding"] * features.specialist_grounding
        if features.specialist_grounding is not None else 0.0
    )
    terms["low_risk"] = (
        POSITIVE_WEIGHTS["low_risk"] * (1.0 - features.risk_severity)
        if features.risk_severity is not None else 0.0
    )

    raw = sum(terms.values())
    # Bounded on both sides, and asymmetrically: diligence should be readier to
    # mark down than to mark up.
    delta = max(-MAX_NEGATIVE, min(MAX_POSITIVE, raw))
    adjusted = max(0.0, min(1.0, float(model_probability) + delta))

    return {
        "model_probability": round(float(model_probability), 4),
        "adjusted_probability": round(adjusted, 4),
        "delta": round(delta, 4),
        "delta_points": round(delta * 100, 1),
        "clamped": abs(raw - delta) > 1e-9,
        "terms": {k: round(v, 4) for k, v in terms.items()},
        "features": features.as_dict(),
        "bounds": {"max_positive": MAX_POSITIVE, "max_negative": -MAX_NEGATIVE},
        "method": (
            "Explicit bounded arithmetic over structured agent outputs. Not a "
            "fitted layer: fitting needs examples labelled (evidence state, "
            "outcome), and the seven decks with known outcomes are all successes. "
            "Not an LLM judgement: no free text enters this function."
        ),
    }


def audit_table() -> list[dict[str, str]]:
    return list(LEAKAGE_AUDIT)
