"""Tests for the in-domain risk-disclosure model and its role in the pipeline.

The model file is not mocked. Where it is present these exercise the real
thing; where it is absent they assert the documented degradation instead, which
is the path a fresh clone takes.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import risk_disclosure

GOING_CONCERN = (
    "These conditions raise substantial doubt about our ability to continue as a "
    "going concern. Our independent registered public accounting firm has included "
    "an explanatory paragraph in its report on our financial statements."
)
ASC_606_BOILERPLATE = (
    "Revenue is recognized when control of the promised goods or services is "
    "transferred to the customer, in an amount that reflects the consideration we "
    "expect to be entitled to in exchange for those goods or services."
)
SAFE_HARBOUR = (
    "This report contains forward-looking statements within the meaning of the "
    "Private Securities Litigation Reform Act of 1995. Actual results could differ "
    "materially from those anticipated in these forward-looking statements."
)

needs_model = pytest.mark.skipif(
    not risk_disclosure.is_available(),
    reason="risk_disclosure_model.pkl not present in this checkout",
)


def test_absent_text_scores_none_not_zero():
    """None means "not scored", never "not risky". A caller that substitutes 0.0
    for None turns a missing model into a clean bill of health, which is the
    defect class this codebase has hit repeatedly."""
    assert risk_disclosure.severity("") is None
    assert risk_disclosure.severity("   ") is None


@needs_model
def test_a_going_concern_disclosure_outranks_revenue_policy_boilerplate():
    """The exact comparison the previous model failed. Risk/Tone scored a
    ranking AUC of 0.333 on this benchmark -- below chance -- meaning it ordered
    genuine going-concern disclosures BELOW risk-free text."""
    assert risk_disclosure.severity(GOING_CONCERN) > risk_disclosure.severity(ASC_606_BOILERPLATE)


@needs_model
def test_hard_boilerplate_scores_low():
    """Safe-harbour and ASC 606 paragraphs are saturated with the vocabulary a
    keyword detector fires on. They must not score as risk."""
    for text in (ASC_606_BOILERPLATE, SAFE_HARBOUR):
        assert risk_disclosure.severity(text) < 0.5


@needs_model
def test_severity_is_a_probability():
    for text in (GOING_CONCERN, ASC_606_BOILERPLATE, SAFE_HARBOUR):
        assert 0.0 <= risk_disclosure.severity(text) <= 1.0


@needs_model
def test_metadata_states_the_subgroup_limitation():
    """The combined benchmark AUC of 0.959 is dominated by the 22 SEC excerpts.
    The metadata must carry both subgroup figures so nothing downstream can
    quote the combined number as deck-register performance."""
    meta = risk_disclosure.model_metadata()
    assert meta["available"] is True
    assert meta["benchmark_auc_sec_filings"] > 0.9
    assert meta["benchmark_auc_deck_register"] < 0.8
    assert "severity" in meta["role"]


def test_a_missing_model_degrades_without_claiming_safety(monkeypatch):
    """A fresh clone has no model file. That must produce "not scored", and must
    not stop the discrete detectors from working."""
    monkeypatch.setattr(risk_disclosure, "_bundle", None)
    monkeypatch.setattr(risk_disclosure, "_load_attempted", True)

    assert risk_disclosure.severity(GOING_CONCERN) is None
    meta = risk_disclosure.model_metadata()
    assert meta["available"] is False
    assert "reason" in meta


def test_the_model_does_not_decide_whether_a_risk_fired():
    """Structural guard for the measured decision. Giving the model a vote
    raised ranking AUC 0.941 -> 0.990 and doubled the boilerplate false-positive
    rate 0.077 -> 0.154, because it fires on a risk-free team slide at p=0.691.
    Firing is decided by the discrete detectors alone.

    ASC 606 boilerplate is the right probe here: it is genuinely risk-free and
    genuinely contains no dictionary phrase, so if it stays unflagged the
    severity model is confirmed to have no vote.
    """
    from agents.deck_financials import deck_risk_signals
    from agents.risk_detector import detect_signals

    assert detect_signals(ASC_606_BOILERPLATE) == {}
    assert deck_risk_signals(ASC_606_BOILERPLATE) == []


def test_the_keyword_detectors_false_positive_on_safe_harbour_is_the_statute_name():
    """Documents a real, pre-existing weakness rather than asserting it away.

    The keyword dictionary flags safe-harbour paragraphs as `legal_risk` because
    it substring-matches "litigation" inside "Private Securities Litigation
    Reform Act of 1995" -- the name of the very statute that makes the paragraph
    boilerplate. This is a concrete instance of the 7.7% boilerplate
    false-positive rate measured on ml/eval/risk_benchmark.jsonl, and it is why
    the benchmark's negatives were chosen to be adversarial.

    Pinned as a known limitation, not a bug to silently fix: narrowing the
    dictionary entry would need re-measuring against the whole benchmark, and
    the ensemble already keeps the overall rate at 0.077.
    """
    from agents.risk_detector import detect_signals

    signals = detect_signals(SAFE_HARBOUR)
    assert "legal_risk" in signals
    assert any(hit["signal"] == "litigation" for hit in signals["legal_risk"])


def test_the_saved_model_loads_in_a_process_that_did_not_train_it():
    """Regression guard for a silent outage this session introduced and caught.

    The feature-augmented model uses a custom sklearn transformer. When that
    class was defined inside the training script, pickle saved it by reference
    as `__main__.DeckFeatureTransformer` -- a path that resolves in NO other
    process. `agents/risk_disclosure` loaded the file, hit an unpickling error,
    and behaved exactly as its degradation contract promises: `available: False`
    and `severity() -> None`.

    The dangerous part is what did NOT happen. Nothing crashed, no test failed,
    and every benchmark number stayed identical -- because the evaluation
    harness re-TRAINS the model rather than re-LOADING it. The product had
    silently lost its severity model while all the evidence said it was fine.

    So this asserts the property that actually matters: a file written by the
    trainer can be read back by the application. The transformer now lives in
    `agents/deck_risk_features`, which both can import.
    """
    import pickle

    from agents.risk_disclosure import MODEL_PATH

    if not MODEL_PATH.exists():
        pytest.skip("model file not present in this checkout")

    with MODEL_PATH.open("rb") as handle:
        bundle = pickle.load(handle)

    assert "model" in bundle and "threshold" in bundle
    module = type(bundle["model"]).__module__
    assert not module.startswith("__main__"), (
        f"model pickled with a __main__ reference ({module}); it will not load "
        f"outside the training script"
    )
    # And it must actually score, not merely unpickle.
    assert 0.0 <= float(bundle["model"].predict_proba([GOING_CONCERN])[0][1]) <= 1.0


def test_the_deck_feature_transformer_is_importable_from_the_app():
    """The specific import path the pickle depends on."""
    from agents.deck_risk_features import FEATURE_NAMES, DeckFeatureTransformer

    features = DeckFeatureTransformer().transform([GOING_CONCERN])
    assert features.shape == (1, len(FEATURE_NAMES))
