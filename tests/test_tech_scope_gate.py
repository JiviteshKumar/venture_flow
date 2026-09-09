"""VentureFlow analyses technology startups only.

The product's every number is calibrated on technology companies -- the score
model's features are literally Y Combinator's taxonomy. Pointed at a restaurant
group it would still return a score, formatted identically, with nothing saying
the model has never seen a business of that kind.

The asymmetry these tests encode: wrongly BLOCKING a real tech startup breaks
the product for someone holding a legitimate deck, and there is nothing they can
do about it. Wrongly ALLOWING a non-tech company produces an uncalibrated score.
The first is worse, so the gate abstains whenever it is unsure, and most of the
tests below are about the cases where it must NOT block.

Constructed decks describe shapes of business, not real companies. Nothing here
attributes anything to anyone.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
import tech_scope


@pytest.fixture(autouse=True)
def restore_enabled():
    original = tech_scope.ENABLED
    yield
    tech_scope.ENABLED = original


SAAS = (
    "Our SaaS platform gives engineering teams automated code review. The web "
    "app integrates with GitHub through our API, and the algorithm flags "
    "regressions before merge. 2,400 monthly active users on a subscription "
    "plan, $40k MRR, churn of 2%. The engineering team previously built "
    "developer tools at a cloud infrastructure company. Raising a seed round."
)

RESTAURANT_GROUP = (
    "We operate a group of four farm-to-table restaurants in Portland. Our "
    "flagship restaurant seats 90 covers and we run a catering arm for private "
    "events. We source produce from a nearby farm and bake bread in-house at our "
    "own bakery. We are raising to open two further restaurant locations and "
    "expand the catering kitchen. Each restaurant reaches profitability in about "
    "fourteen months."
)

TECH_FOR_RESTAURANTS = (
    "Booking and table-management software for restaurants. Our web app and iOS "
    "app let restaurant owners manage covers, waitlists and reservations. 900 "
    "restaurant customers, $18k MRR, integrations with major POS systems. The "
    "engineering team previously built payments infrastructure. Churn is 3% "
    "monthly and we are raising a seed round."
)


class TestWordBoundaries:
    """The first version matched substrings, and "api" matched inside "working
    capital" -- handing a construction company a software signal and letting it
    through. Same name-match-for-identity-match failure as the deck scraper and
    founder grounding."""

    def test_api_does_not_match_inside_capital(self):
        assert "api" not in tech_scope._matches(
            "Raising working capital for the next phase.", tech_scope.SOFTWARE_CORE
        )

    def test_ai_does_not_match_inside_email(self):
        assert "ai" not in tech_scope._matches(
            "Reach us by email or post.", tech_scope.SOFTWARE_CORE
        )

    def test_real_uses_still_match(self):
        matched = tech_scope._matches(
            "Our public API is used by AI teams.", tech_scope.SOFTWARE_CORE
        )
        assert "api" in matched
        assert "ai" in matched


class TestServingVersusBeing:
    """A SaaS product sold to restaurants is a tech startup. The industry a
    company sells INTO must not be read as what the company is."""

    def test_software_for_restaurants_is_in_scope(self):
        verdict = tech_scope.classify(TECH_FOR_RESTAURANTS, "Covers")

        assert verdict["in_scope"] is True
        assert "restaurant" not in verdict["non_tech_signals"], (
            "'restaurants' here is the market being sold to, not the business"
        )

    def test_a_restaurant_operator_is_not(self):
        assert tech_scope._is_serving_not_being(RESTAURANT_GROUP, "restaurant") is False


class TestMustNotBlock:
    """The expensive error. Every one of these has to pass."""

    def test_a_plain_saas_deck(self):
        verdict = tech_scope.classify(SAAS, "CodeLoop")
        assert verdict["in_scope"] is True
        assert verdict["method"] == "signals", (
            "an unambiguous software deck should not cost an LLM call"
        )

    def test_hardware_counts_as_technology(self):
        verdict = tech_scope.classify(
            "We design low-power sensors for cold-chain logistics. The device "
            "attaches to a pallet and streams temperature telemetry over a "
            "cellular network to our cloud dashboard. Firmware and hardware are "
            "designed in-house by our engineering team. 40 pilot customers.",
            "ChainSense",
        )
        assert verdict["in_scope"] is True

    def test_text_too_short_to_judge_is_allowed(self):
        verdict = tech_scope.classify("A startup.", "Tiny")

        assert verdict["in_scope"] is True
        assert verdict["method"] == "insufficient_text"
        assert verdict["confidence"] == 0.0

    def test_an_unreachable_llm_never_blocks_an_ambiguous_deck(self, monkeypatch):
        """An outage in our own model must not become a refusal aimed at the
        user. This is the whole reason adjudication failure returns None."""
        monkeypatch.setattr(tech_scope, "_adjudicate", lambda t, n: None)
        verdict = tech_scope.classify(
            "We are building something new for a large market. Our team has "
            "worked together for six years and we have strong early signals from "
            "the first cohort of customers. We are raising a seed round to grow "
            "the team and reach more of the market we have identified.",
            "Vague",
        )

        assert verdict["in_scope"] is True
        assert "llm_unavailable" in verdict["method"]

    def test_a_low_confidence_out_of_scope_call_is_not_acted_on(self, monkeypatch):
        monkeypatch.setattr(tech_scope, "_adjudicate", lambda t, n: {
            "is_tech": False, "sector": "retail", "confidence": 0.55,
            "reason": "not sure",
        })
        verdict = tech_scope.classify(RESTAURANT_GROUP, "Maybe")

        assert verdict["in_scope"] is True
        assert verdict["method"] == "llm_low_confidence"
        assert "0.55" in verdict["reason"] or "not confident" in verdict["reason"]

    def test_the_gate_can_be_turned_off_entirely(self):
        tech_scope.ENABLED = False
        verdict = tech_scope.classify(RESTAURANT_GROUP, "Anything")

        assert verdict["in_scope"] is True
        assert verdict["method"] == "disabled"


class TestMustBlock:
    def test_a_confident_call_with_agreeing_evidence_blocks(self, monkeypatch):
        monkeypatch.setattr(tech_scope, "_adjudicate", lambda t, n: {
            "is_tech": False, "sector": "hospitality", "confidence": 0.95,
            "reason": "operates restaurants",
        })
        verdict = tech_scope.classify(RESTAURANT_GROUP, "Four Tables")

        assert verdict["in_scope"] is False
        assert verdict["non_tech_signals"]

    def test_one_stray_keyword_does_not_veto_a_confident_call(self, monkeypatch):
        """The construction case. Six non-tech signals against one incidental
        software word must still block; requiring zero software signals let it
        through."""
        monkeypatch.setattr(tech_scope, "_adjudicate", lambda t, n: {
            "is_tech": False, "sector": "construction", "confidence": 0.99,
            "reason": "a construction company",
        })
        verdict = tech_scope.classify(
            "A construction company specialising in residential extensions and "
            "loft conversions. Our contractor teams handle roofing, plumbing and "
            "landscaping in-house. We completed 62 projects last year. Raising to "
            "take on larger property development contracts. We use a scheduling "
            "application internally.",
            "BuildCo",
        )

        assert verdict["in_scope"] is False

    def test_keywords_alone_can_block_when_the_llm_is_down(self, monkeypatch):
        """Deliberate: with no software evidence at all and a pile of non-tech
        evidence, the deterministic pass is allowed to refuse -- and must say
        that it decided without the model."""
        monkeypatch.setattr(tech_scope, "_adjudicate", lambda t, n: None)
        verdict = tech_scope.classify(RESTAURANT_GROUP, "Four Tables")

        assert verdict["in_scope"] is False
        assert "without the language model" in verdict["reason"]


class TestEndpointsEnforceIt:
    def test_analyze_refuses_with_a_structured_body(self, monkeypatch):
        """The UI needs the reason and the evidence, not a bare error string."""
        monkeypatch.setattr(tech_scope, "_adjudicate", lambda t, n: {
            "is_tech": False, "sector": "hospitality", "confidence": 0.95,
            "reason": "operates restaurants",
        })
        client = TestClient(api.app)
        response = client.post("/analyze", json={
            "company_name": "Four Tables",
            "company_description": RESTAURANT_GROUP,
        })

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["error"] == "out_of_scope"
        assert detail["scope_check"]["in_scope"] is False
        assert detail["scope_check"]["reason"]
        assert detail["scope_check"]["scope_statement"]

    def test_analyze_accepts_a_tech_startup(self, monkeypatch):
        """The job is stubbed, and that is the whole point of this test.

        Without the stub, TestClient runs the queued BackgroundTask inline, so
        asserting "the gate let this through" quietly performed a complete
        analysis of a company called CodeLoop: roughly 30,000 Groq tokens --
        about 15% of the free tier's daily budget -- several minutes of
        wall-clock time, and a permanent report row in the production database,
        on every run of the suite.

        What this test is about is the gate's verdict on an in-scope
        description. Everything after the 202 belongs to other tests.
        """
        submitted: dict = {}
        monkeypatch.setattr(api, "create_analysis_job",
                            lambda payload: (submitted.update(payload), "job-1")[1])
        monkeypatch.setattr(api, "count_active_jobs", lambda: 0)

        client = TestClient(api.app)
        response = client.post("/analyze", json={
            "company_name": "CodeLoop",
            "company_description": SAAS,
        })

        assert response.status_code == 202, response.text
        assert submitted["company_name"] == "CodeLoop", (
            "the request was accepted but never reached the queue"
        )

    def test_the_gate_is_not_only_at_upload(self, monkeypatch):
        """A gate a user can walk around by editing a text field is not a gate.

        The frontend lets the extracted description be edited before submission,
        and /analyze is reachable directly, so checking only at upload would
        leave the real entry point open.
        """
        monkeypatch.setattr(tech_scope, "_adjudicate", lambda t, n: {
            "is_tech": False, "sector": "hospitality", "confidence": 0.9,
            "reason": "operates restaurants",
        })
        client = TestClient(api.app)
        # Straight to /analyze, never touching /upload-pdf.
        response = client.post("/analyze", json={
            "company_name": "Four Tables",
            "company_description": RESTAURANT_GROUP,
        })

        assert response.status_code == 422
