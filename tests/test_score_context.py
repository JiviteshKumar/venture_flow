"""The headline number must say what it measures, and be banded honestly.

See ml/score_context.py for the three misreadings this closes: a band from
fixed thresholds rather than the model's interval, a 49% "base rate" that
excludes the 70% of companies still operating, and a survived-or-exited label
that scores a quiet survivor the same as a fund-returner.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import score_context as sc  # noqa: E402

UBER_VS = {"available": True, "venture_score": 44, "score_range": [32, 54], "base_rate": 0.4892}
YC_RATES = {"n": 5133, "exit_rate": 0.1455, "outsized_rate": 0.0146,
            "rates": {"operating": 0.7002, "exit": 0.1309, "outsized": 0.0146, "shut_down": 0.1543}}
UBER_COMPS = {"available": True, "outcome_rates": YC_RATES, "comparables": [
    {"name": "Mecho Autotech", "outcome": "Still operating"},
    {"name": "Debitel", "outcome": "Shut down"},
    {"name": "Drive Pulse", "outcome": "Shut down"},
    {"name": "Alma", "outcome": "Shut down"},
    {"name": "Orange UK", "outcome": "Exit"},
]}


class TestTheBandComesFromTheInterval:
    def test_uber_is_within_range(self):
        ctx = sc.build_score_context(UBER_VS, UBER_COMPS)
        assert ctx["band"] == sc.WITHIN
        assert "32-54" in ctx["band_reason"] and "49%" in ctx["band_reason"]

    def test_a_64_clearly_above_the_base_rate_is_above(self):
        """Fixed thresholds called this 'Near'."""
        band, _ = sc.band_for(64, 58, 70, 48.9)
        assert band == sc.ABOVE

    def test_a_46_entirely_below_the_base_rate_is_below(self):
        """Fixed thresholds also called this 'Near'."""
        band, _ = sc.band_for(46, 44, 48, 48.9)
        assert band == sc.BELOW

    def test_without_an_interval_it_says_so(self):
        band, reason = sc.band_for(70, None, None, 48.9)
        assert band == sc.ABOVE and "no interval" in reason


class TestItSaysWhatTheNumberIs:
    def test_the_measure_is_stated(self):
        ctx = sc.build_score_context(UBER_VS, UBER_COMPS)
        assert "survived or exited" in ctx["measures"]
        assert "not a forecast of returns" in ctx["measures"]

    def test_the_base_rate_is_not_left_to_be_misread(self):
        """49% excludes the 70% still operating; the real exit rate is 15%."""
        note = sc.build_score_context(UBER_VS, UBER_COMPS)["base_rate_note"]
        assert "49%" in note and "70%" in note and "15%" in note and "1.5%" in note

    def test_the_note_degrades_gracefully_without_population_rates(self):
        note = sc.base_rate_note(48.9, None)
        assert "49%" in note and "still operating" in note


class TestTheComparablesOutcomeMix:
    def test_uber(self):
        mix = sc.build_score_context(UBER_VS, UBER_COMPS)["comparable_mix"]
        assert mix["n"] == 5
        assert mix["counts"] == {"Exit": 1, "Still operating": 1, "Shut down": 3}
        assert mix["sentence"] == (
            "Of the 5 most similar companies with a recorded outcome, 1 exited, "
            "1 is still operating and 3 shut down."
        )

    def test_the_best_outcome_is_named_first(self):
        mix = sc.comparable_mix([{"outcome": "Shut down"}, {"outcome": "Outsized outcome"}])
        assert mix["sentence"].index("outsized") < mix["sentence"].index("shut down")

    def test_one_comparable_is_singular(self):
        assert "1 most similar company" in sc.comparable_mix([{"outcome": "Exit"}])["sentence"]

    def test_no_comparables_is_empty_not_invented(self):
        assert sc.comparable_mix([])["sentence"] == ""
        ctx = sc.build_score_context(UBER_VS, {"available": False})
        assert ctx["comparable_mix"]["n"] == 0


class TestWhenThereIsNoModel:
    @pytest.mark.parametrize("vs", [None, {}, {"available": False}, {"available": True}])
    def test_it_does_not_invent_a_context(self, vs):
        assert sc.build_score_context(vs, UBER_COMPS) == {"available": False}


class TestThePipelineAttachesIt:
    def test_the_report_carries_score_context(self):
        source = (Path(__file__).resolve().parents[1] / "ventureflow_agent.py").read_text(encoding="utf-8")
        assert 'report["sections"]["score_context"]' in source
