"""Unit-tests the metrics computation in ml/scripts/eval_risk_detector.py, and
the integrity of the labeled benchmark itself.

Same pattern as tests/test_eval_claim_verifier.py: `compute_metrics` is a pure
function of a list of rows, so it is exercised directly with no network, no
Groq key and no model files. Actually running the detectors needs those; see
that script's docstring.

The benchmark-integrity tests exist because the labels are the artifact here.
A silent edit that unbalances the classes, drops the provenance URL on an SEC
excerpt, or lets a "risk-free" row keep a severity would quietly change every
number the harness reports.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.scripts.eval_risk_detector import compute_metrics, load_benchmark

CATEGORIES = {
    "financial_risk", "legal_risk", "operational_risk",
    "market_risk", "management_risk",
}


def _row(gold, predicted, *, ident="x", gold_cats=None, pred_cats=None, score=None):
    return {
        "id": ident,
        "gold_risk": gold,
        "predicted_risk": predicted,
        "gold_categories": gold_cats or [],
        "predicted_categories": pred_cats or [],
        "score": score,
    }


# ── The benchmark file itself ───────────────────────────────────────────────

def test_benchmark_loads_with_both_classes_represented():
    rows = load_benchmark()
    assert len(rows) >= 20, "the brief asks for 20-30 examples"
    assert len(rows) <= 40
    positives = [r for r in rows if r["gold_risk"]]
    negatives = [r for r in rows if not r["gold_risk"]]
    # The boilerplate half is the whole point of this benchmark; a set that
    # drifted to mostly-positive would make the headline false-positive rate
    # meaningless.
    assert len(positives) >= 10
    assert len(negatives) >= 10


def test_benchmark_ids_are_unique():
    ids = [r["id"] for r in load_benchmark()]
    assert len(ids) == len(set(ids))


def test_labels_are_internally_consistent():
    for row in load_benchmark():
        if row["gold_risk"]:
            assert row["gold_severity"] in {"LOW", "MEDIUM", "HIGH"}, row["id"]
            assert row["gold_categories"], f"{row['id']} is a red flag with no category"
            assert set(row["gold_categories"]) <= CATEGORIES, row["id"]
        else:
            # A risk-free excerpt carrying a severity or a category would be a
            # half-edited label, and would silently inflate category recall.
            assert row["gold_severity"] == "NONE", row["id"]
            assert row["gold_categories"] == [], row["id"]


def test_every_example_is_substantial_and_explained():
    for row in load_benchmark():
        assert len(row["text"]) > 150, f"{row['id']} is too short to judge"
        assert row["rationale"], f"{row['id']} has no stated reason for its label"


def test_sec_excerpts_keep_their_provenance():
    """An SEC-sourced excerpt without its URL cannot be audited back to the
    filing, which is the only thing making 'real filing text' checkable."""
    for row in load_benchmark():
        if row["source"].startswith("pitch_deck_register"):
            assert row["url"] == ""
        else:
            assert row["url"].startswith("https://www.sec.gov/"), row["id"]


# ── compute_metrics ─────────────────────────────────────────────────────────

def test_perfect_detector():
    metrics = compute_metrics([_row(True, True), _row(False, False)])
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == 1.0
    assert metrics["boilerplate_false_positive_rate"] == 0.0


def test_detector_that_flags_everything_is_caught_by_the_false_positive_rate():
    """The failure this benchmark exists to catch. Perfect recall, and useless."""
    rows = [_row(True, True, ident="a"), _row(False, True, ident="b"), _row(False, True, ident="c")]
    metrics = compute_metrics(rows)
    assert metrics["recall"] == 1.0
    assert metrics["boilerplate_false_positive_rate"] == 1.0
    assert metrics["boilerplate_flagged_ids"] == ["b", "c"]


def test_detector_that_flags_nothing_scores_zero_not_an_error():
    rows = [_row(True, False, ident="a"), _row(False, False, ident="b")]
    metrics = compute_metrics(rows)
    assert metrics["precision"] == 0.0
    assert metrics["recall"] == 0.0
    assert metrics["f1"] == 0.0
    assert metrics["missed_red_flag_ids"] == ["a"]


def test_category_scores_ignore_risk_free_rows():
    """Categories predicted on a risk-free excerpt must not be counted; that
    error is already reported as the false-positive rate, and counting it twice
    would make a noisy detector look worse on categories than it is."""
    rows = [
        _row(True, True, gold_cats=["financial_risk"], pred_cats=["financial_risk"]),
        _row(False, True, gold_cats=[], pred_cats=["legal_risk", "market_risk"]),
    ]
    metrics = compute_metrics(rows)
    assert metrics["category_precision"] == 1.0
    assert metrics["category_recall"] == 1.0


def test_auc_is_reported_only_when_every_row_carries_a_score():
    unscored = compute_metrics([_row(True, True), _row(False, False)])
    assert unscored["score_roc_auc"] is None

    scored = compute_metrics([
        _row(True, True, score=0.9), _row(False, False, score=0.1),
    ])
    assert scored["score_roc_auc"] == 1.0


def test_a_constant_score_gives_auc_of_exactly_one_half():
    """Ties count a half, so a detector that returns the same number for every
    input lands on 0.5 rather than on an artefact of sort order. This is what
    makes the legacy-formula and tone-model comparisons readable."""
    metrics = compute_metrics([
        _row(True, False, score=30.0), _row(False, False, score=30.0),
    ])
    assert metrics["score_roc_auc"] == 0.5


def test_below_chance_ranking_is_reported_as_below_chance():
    """The Risk/Tone model's real measured behaviour: it ranked risky text
    below risk-free text. That has to surface as < 0.5 rather than being
    folded away by an absolute value somewhere."""
    metrics = compute_metrics([
        _row(True, False, score=0.02), _row(False, False, score=0.40),
    ])
    assert metrics["score_roc_auc"] == 0.0


def test_committed_results_file_matches_its_own_rows():
    """Guards against a results file whose headline metrics were edited by hand
    or left stale after the rows changed -- the whole reason artifacts are
    committed is that they can be recomputed."""
    path = Path(__file__).resolve().parents[1] / "ml" / "eval" / "risk_benchmark_results.json"
    if not path.exists():
        return  # not yet run in this checkout; nothing to verify
    payload = json.loads(path.read_text(encoding="utf-8"))
    for name, result in payload.get("detectors", {}).items():
        if "unavailable" in result:
            continue
        recomputed = compute_metrics(result["rows"])
        assert recomputed["f1"] == result["metrics"]["f1"], name
        assert (recomputed["boilerplate_false_positive_rate"]
                == result["metrics"]["boilerplate_false_positive_rate"]), name
