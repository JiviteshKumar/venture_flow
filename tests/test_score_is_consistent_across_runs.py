"""The same deck must get the same starting score however it was read.

WHAT WAS WRONG

Uber's 2008 deck scored 41 and 44 on healthy runs and 52 on a run where Groq
was out of tokens -- higher when the product was broken than when it worked.

Taking the three scores apart term by term showed the evidence adjustment was
almost identical (-5.6 vs -5.4 points). The whole gap was the model's STARTING
score: 58 on the broken run, 49 on the healthy ones. The cause was one feature.
`desc_len` means "how much a company wrote on its YC profile" in training, but
in this product it was the length of whatever our extraction step produced -- a
178-character LLM summary when Groq answered, a 1,200-character slab of raw
deck text when it fell back to regex. Length alone moved the score about ten
points (41 at 100 characters, 51 at 800+), so every regex-fallback run started
at 58 whatever the company: Uber, Buffer and Airbnb alike.

Length is now imputed (it measures our pipeline, not the company) and keyword
tags come from the full deck text, which is identical on both paths. Measured
on Uber, Airbnb, Buffer and Coinbase: the gap between paths went from up to 9
points to 0.

What cannot be made identical is a run whose claim checks or specialists
failed: their evidence terms are absent. Such a run is now labelled
provisional, next to the number, rather than presented like a complete one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml import venturescore  # noqa: E402

SUMMARY = ("UberCab is a members-only, on-demand luxury car service that uses a "
           "mobile app to match professional clients with premium vehicles, "
           "offering fast, cashless rides in major cities.")
DECK = (
    "UberCab Next-Generation Car Service. Problem: taxis are slow and dispatch "
    "is broken. Solution: an iPhone app that summons a car in minutes. Mobile "
    "software, GPS, cashless payment through the app. Market: San Francisco "
    "black cars and taxis. Business model: 20% commission per ride. "
) * 6

pytestmark = pytest.mark.skipif(not venturescore.is_available(),
                                reason="VentureFlow Score model not present")


class TestTheStartingScoreIgnoresTheExtractionPath:
    def test_summary_and_raw_slab_score_the_same(self):
        """The Uber case: the LLM's short summary vs the regex fallback's
        1,200-character slab of the same deck."""
        slab = " ".join(DECK.split())[:1200]
        from_llm = venturescore.score_company(SUMMARY, one_liner=SUMMARY[:120], tag_text=DECK)
        from_regex = venturescore.score_company(slab, one_liner=slab[:120], tag_text=DECK)
        assert from_llm["venture_score"] == from_regex["venture_score"], (
            f"{from_llm['venture_score']} vs {from_regex['venture_score']}: the "
            f"extraction path still moves the starting score"
        )

    @pytest.mark.parametrize("length", [100, 200, 400, 800, 1200])
    def test_length_alone_no_longer_moves_it(self, length):
        """Before: 41 at 100 characters, 51 at 800+ for the same content."""
        text = ((SUMMARY + " ") * 10)[:length]
        baseline = venturescore.score_company(SUMMARY, tag_text=DECK)["venture_score"]
        assert venturescore.score_company(text, tag_text=DECK)["venture_score"] == baseline

    def test_length_is_reported_as_imputed_not_observed(self):
        result = venturescore.score_company(SUMMARY, tag_text=DECK)
        assert "desc_len" in result["imputed_features"]
        assert "one_liner_len" in result["imputed_features"]

    def test_content_still_matters(self):
        """Imputing length must not make every deck identical: tags derived
        from the deck text still differ between companies."""
        consumer = venturescore.score_company(SUMMARY, tag_text="A consumer marketplace.")
        fintech = venturescore.score_company(
            SUMMARY, tag_text="Fintech payments API for banks, B2B SaaS, AI.")
        assert consumer["venture_score"] != fintech["venture_score"]


class TestAPartialRunSaysItIsPartial:
    """The one difference that cannot be removed, stated instead."""

    def test_the_pipeline_sets_it_where_degradation_is_decided(self):
        import ventureflow_agent as agent
        source = Path(agent.__file__).read_text(encoding="utf-8")
        start = source.index('report["degraded_components"] = degraded_components')
        assert source.index('report["score_status"]', start) > start

    def test_the_response_model_declares_it(self):
        """A field the model does not declare is dropped silently -- the defect
        that hid provider_degraded from the UI once already."""
        import api
        fields = api.DiligenceResponse.model_fields
        assert "score_status" in fields and "score_status_note" in fields
        assert fields["score_status"].default == "final"

    def test_both_construction_sites_populate_it(self):
        import api
        source = Path(api.__file__).read_text(encoding="utf-8")
        assert source.count('score_status=report.get("score_status")') == 2


@pytest.mark.skipif(not venturescore.is_available(), reason="model not present")
class TestEndToEndThroughThePipeline:
    """run_due_diligence with every provider call stubbed (the same pattern as
    tests/test_fusion_end_to_end.py), so the status is read from the real
    report -- and nothing reaches Groq."""

    def _wire(self, monkeypatch, *, claims_degraded=False, specialists_degraded=False):
        from types import SimpleNamespace
        import ventureflow_agent as agent

        def claim(text, **_k):
            out = {"claim": text, "verdict": "NOT_ENOUGH_INFO", "confidence": 0.6,
                   "reasoning": "nothing public", "key_evidence": "", "sources": [],
                   "total_sources": 3, "full_pages_read": 1}
            if claims_degraded:
                out.update(confidence=0.0, total_sources=0, _degraded=True,
                           _degraded_kind="provider",
                           _degraded_reason="claim verifier: quota")
            return out

        specialist = {"confidence": 0.7, "signals": []}
        if specialists_degraded:
            specialist = {**specialist, "_degraded": True, "_degraded_reason": "429"}

        monkeypatch.setattr(agent, "verify_claim", claim)
        monkeypatch.setattr(agent, "score_risk", lambda *a, **k: {
            "risk_level": "LOW", "overall_score": 20, "key_concerns": [],
            "positive_factors": [], "red_flags": [], "total_signals": 0,
            "disclosure_severity": 0.2, "deck_signals": [],
        })
        monkeypatch.setattr(agent, "run_investment_agents", lambda **k: {
            "market": dict(specialist), "team": dict(specialist),
        })
        monkeypatch.setattr(agent, "build_context", lambda *a: {"relevant_reports": []})
        monkeypatch.setattr(agent, "format_context_for_llm", lambda *a: "")
        monkeypatch.setattr(agent, "get_client", lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(
                create=lambda **_: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="memo"))],
                    usage=SimpleNamespace(total_tokens=10),
                )))))

    def _run(self, extraction_method="llm_schema"):
        import ventureflow_agent as agent
        return agent.run_due_diligence(
            "Acme Robotics",
            company_description="Warehouse robotics software for logistics operators.",
            claims_to_verify=["We serve 62 customers.", "ARR is $2.4M."],
            filing_text="Acme Robotics builds warehouse robotics software. " * 20,
            sector="B2B", stage="Seed", extraction_method=extraction_method,
        )

    def test_a_complete_run_is_final(self, monkeypatch):
        self._wire(monkeypatch)
        report = self._run()
        assert report["score_status"] == "final", report.get("score_status_note")
        assert report["score_status_note"] == ""

    def test_failed_claim_checks_make_it_provisional(self, monkeypatch):
        self._wire(monkeypatch, claims_degraded=True)
        report = self._run()
        assert report["score_status"] == "provisional"
        assert "claim verification" in report["score_status_note"]

    def test_failed_specialists_make_it_provisional(self, monkeypatch):
        self._wire(monkeypatch, specialists_degraded=True)
        report = self._run()
        assert report["score_status"] == "provisional"
        assert "market" in report["score_status_note"]

    def test_a_regex_fallback_extraction_makes_it_provisional(self, monkeypatch):
        self._wire(monkeypatch)
        report = self._run(extraction_method="regex_fallback")
        assert report["score_status"] == "provisional"
        assert "structured extraction" in report["score_status_note"]

    def test_the_starting_score_is_the_same_on_both_paths(self, monkeypatch):
        """The Uber defect end to end: identical deck, the two extraction
        paths, the same model_only_score."""
        self._wire(monkeypatch)
        a = self._run("llm_schema")["sections"]["venture_score"]["model_only_score"]
        b = self._run("regex_fallback")["sections"]["venture_score"]["model_only_score"]
        assert a == b
