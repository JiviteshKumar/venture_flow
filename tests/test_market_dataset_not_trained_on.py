"""The market corpus is for showing companies, never for training a model.

WHY THIS FILE EXISTS

`ml/data/market_dataset.jsonl` is 470 real technology companies with outcomes
recorded in public reference data. It was added to fix a real limitation -- the
comparable-company search covered Y Combinator and nothing else -- and it does
fix it.

It is also, measurably, poisonous as training data, and the reason is not
obvious enough to be safe from a future session that sees a labelled dataset
sitting in `ml/data/` and reasonably concludes it is there to be trained on.

Measured in `ml/scripts/eval_cross_population.py`:

  * Raw, it scores 0.8586 AUC on itself against 0.5852 for Y Combinator. The
    text states the outcome. "defunct" appears in 13.4% of failures and 1.1% of
    successes; the present-tense "is a" in 9.0% of failures and 79.6% of
    successes. Grammatical tense nearly separates the classes on its own.

  * De-leaked -- outcome sentences dropped, tense flattened, "defunct" down to
    0.0% in both classes -- it still scores 0.8429. So the leak was never the
    main thing. What remains is Wikidata's coverage:

        "video game" appears in 81.5% of failures, 40.1% of successes
        "telecommunications" in 3.1% of failures, 28.1% of successes
        founding year alone            AUC 0.6180 (failures 1998, successes 2001)
        article length alone           AUC 0.6225 (411 vs 618 median chars)

    A model trained on this learns "games company, founded in the nineties,
    short article -> failure". Every part of that is a fact about what an
    encyclopedia chose to write about, and the product would state it to a
    founder as a fact about their company.

So the corpus stays where it is useful -- a comparables table, where each row is
a real company with a verified outcome and nothing is predicted -- and these
tests keep it out of everywhere else.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MARKET_PATH = ROOT / "ml" / "data" / "market_dataset.jsonl"

# Scripts that fit a model. If any of them starts reading the market corpus,
# this file should be the thing that notices.
TRAINING_SCRIPTS = sorted((ROOT / "ml" / "scripts").glob("train_*.py"))


@pytest.mark.skipif(not MARKET_PATH.exists(), reason="market corpus not built")
def test_the_corpus_is_present_and_labelled():
    rows = [json.loads(line) for line in MARKET_PATH.open(encoding="utf-8")]

    assert len(rows) > 100
    assert all(row["label"] in (0, 1) for row in rows)
    # Both classes present, and neither overwhelming -- a degenerate split would
    # mean the labelling rule broke again (an earlier version produced 80.9%
    # positive by counting lifelong subsidiaries as acquisitions).
    positive_rate = sum(row["label"] for row in rows) / len(rows)
    assert 0.35 < positive_rate < 0.70, (
        f"positive rate {positive_rate:.3f} suggests the labelling rule has "
        f"broken; see build_market_company_dataset.label_of"
    )


@pytest.mark.skipif(not MARKET_PATH.exists(), reason="market corpus not built")
def test_every_row_can_be_checked_by_a_human():
    """The corpus's entire claim to trustworthiness. A row nobody can verify is
    indistinguishable from one that was made up."""
    rows = [json.loads(line) for line in MARKET_PATH.open(encoding="utf-8")]

    for row in rows:
        assert re.fullmatch(r"https://www\.wikidata\.org/wiki/Q\d+", row["source_url"]), (
            f"{row['name']} has no checkable source URL"
        )
        assert row["label_reason"], f"{row['name']} does not say why it is labelled"


@pytest.mark.skipif(not MARKET_PATH.exists(), reason="market corpus not built")
def test_the_provenance_file_records_the_known_biases():
    """A future reader has to be able to find out what is wrong with this data
    without re-deriving it."""
    provenance = json.loads(
        MARKET_PATH.with_suffix(".provenance.json").read_text(encoding="utf-8")
    )

    assert provenance["known_biases"], "the biases must be written down"
    joined = " ".join(provenance["known_biases"]).lower()
    assert "notable" in joined, "encyclopedia notability bias must be recorded"
    assert "video game" in joined, "the games-studio skew must be recorded"
    assert provenance["label_rules"]["excluded"]


@pytest.mark.parametrize("script", TRAINING_SCRIPTS, ids=lambda p: p.name)
def test_no_training_script_reads_the_market_corpus(script):
    """The guard that matters.

    A labelled JSONL in ml/data/ looks exactly like training data, and the
    reasons it is not are three measurements deep. If a future change points a
    trainer at it, this fails and the docstring above explains why.
    """
    source = script.read_text(encoding="utf-8")

    assert "market_dataset" not in source, (
        f"{script.name} reads ml/data/market_dataset.jsonl. That corpus is not "
        f"trainable: its own AUC is produced by Wikidata's coverage biases "
        f"(category, era and article length), not by anything predictive about "
        f"startups. See this file's docstring and "
        f"ml/eval/cross_population_results.json."
    )


def test_the_evaluation_that_established_this_is_committed():
    """The claim above is only as good as the measurement behind it, and that
    measurement has to stay runnable and readable."""
    script = ROOT / "ml" / "scripts" / "eval_cross_population.py"
    assert script.exists(), "the cross-population evaluation is missing"

    results_path = ROOT / "ml" / "eval" / "cross_population_results.json"
    if not results_path.exists():
        pytest.skip("evaluation has not been run in this checkout")

    results = json.loads(results_path.read_text(encoding="utf-8"))
    confounds = results["confounds_in_the_market_corpus"]

    # The three confounds, each with a recorded number rather than an assertion
    # in prose.
    assert confounds["founding_year_only_auc"] > 0.55
    assert confounds["article_length_only_auc"] > 0.55
    games = confounds["category_frequencies"]["video game"]
    assert games["in_failures"] > games["in_successes"] * 1.5

    # And the useful result: the YC-trained model does transfer, modestly.
    transfer = next(
        r for r in results["results"]
        if r["comparison"] == "[de-leaked] YC -> Market (transfer)"
    )
    assert transfer["roc_auc"] > 0.55, (
        "YC -> market transfer has fallen to chance; the shipped model would no "
        "longer have any measured basis outside Y Combinator"
    )
