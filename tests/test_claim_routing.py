"""Claims are routed before they are checked, and a checked claim is remembered.

Of the 128 distinct claims this product had checked and stored, 108 came back
NOT_ENOUGH_INFO. Most of them come from synthetic test decks -- companies that
do not exist, so their claims can never be corroborated -- but read one by one
the rest were four fixable problems: private metrics no public source can
settle, general market facts searched with the company's name glued on,
extraction fragments, and duplicates. Separately, the same claim could get a
different verdict on a re-run, because retrieval returns different pages each
time. See agents/claim_router.py and agents/claim_cache.py.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents import claim_router as router  # noqa: E402
from agents.claim_router import COMPANY, GARBLED, INTERNAL, MARKET  # noqa: E402


# ── classification ─────────────────────────────────────────────────────────
class TestPrivateMetricsAreRecognised:
    """0 of 10 such claims in the stored reports ever received a verdict."""

    @pytest.mark.parametrize("claim,company", [
        ("ARR $11.4M (was $3.9M 12 months ago)", "FlowDesk"),
        ("ARR $5.1M", "ShieldAI"),
        ("We have 40 enterprise customers", "ComplyForge AI"),
        ("55,000 users, growing 40% per month", "Buffer"),
        ("$2 million USD per day in transaction volume", "Coinbase"),
        ("AgroPulse is raising a $3M seed round.", "AgroPulse"),
        ("VitalPulse is deployed across 6 partner hospitals.", "2 VitalPulse HealthTech"),
    ])
    def test_internal(self, claim, company):
        assert router.classify(claim, company).kind == INTERNAL


class TestPublicCompanyFactsStayCheckable:
    @pytest.mark.parametrize("claim", [
        "Employer pricing is $8 per employee per month.",
        "Raised $4.2M from In-Q-Tel and Paladin Capital.",
        "Cleared by the FDA under a 510(k) in 2023.",
    ])
    def test_company(self, claim):
        assert router.classify(claim, "Calmwell").kind == COMPANY

    def test_a_growth_rate_is_not_a_price(self):
        """'per month' after a percentage is growth, not pricing."""
        assert router.classify("55,000 users, growing 40% per month", "Buffer").kind != COMPANY


class TestGeneralStatementsAreSearchedWithoutTheAnchor:
    @pytest.mark.parametrize("claim", [
        "There are over 2 million mid-size farms in the US.",
        "Top 4 players combined only 22% of revenues.",
        "Car services transfers average over $60 + tax.",
        "Carbon removal is the only pathway to net-zero.",
    ])
    def test_market(self, claim):
        routed = router.classify(claim, "AgroPulse")
        assert routed.kind == MARKET
        assert routed.search == router.SEARCH_BOTH

    def test_a_claim_naming_the_company_stays_anchored(self):
        assert router.classify("UberCab is described as the NetJets of car services",
                               "Uber").search == router.SEARCH_COMPANY

    def test_first_person_is_about_the_company(self):
        assert router.classify("We take a 10% commission on each transaction.",
                               "Airbnb").search == router.SEARCH_COMPANY

    def test_a_tagline_without_the_name_is_searched_both_ways(self):
        routed = router.classify("FDA-cleared AI diagnostics, detecting disease earlier at scale.",
                                 "NovaMed AI")
        assert routed.search == router.SEARCH_BOTH


class TestFragmentsAreNotChecked:
    @pytest.mark.parametrize("claim", [
        "Classroom pacing leaves both Quality 1-on-1 tutoring costs ₹500- Parents rarely know where a child is struggling",
        "This is a faithful reproduc1on of the",
        "Growth is driven by",
        "Market",
    ])
    def test_garbled(self, claim):
        assert router.classify(claim, "LearnLoop").kind == GARBLED


class TestCleaning:
    def test_trailing_money_figures_are_removed(self):
        assert router.clean(
            "D2C apparel brands are capturing share from legacy retail chains. $1,400M $45M"
        ) == "D2C apparel brands are capturing share from legacy retail chains."

    def test_a_trailing_year_is_part_of_the_claim(self):
        """An earlier pattern turned this into '...industry by'."""
        claim = "Growing to a $3.5B industry by 2010"
        assert router.clean(claim) == claim

    def test_a_short_metric_keeps_its_figure(self):
        assert router.clean("ARR $11.4M") == "ARR $11.4M"


class TestCompanyMentions:
    def test_a_leading_number_in_the_name_is_ignored(self):
        assert router.mentions_company("2 VitalPulse HealthTech", "VitalPulse is deployed")

    def test_generic_words_in_the_name_do_not_count(self):
        """"HealthTech" appearing in a claim is not the company being named."""
        assert not router.mentions_company("2 VitalPulse HealthTech",
                                           "HealthTech adoption is rising in India")

    def test_punctuation_in_the_name(self):
        assert router.mentions_company("ThreadAndCo", "Thread & Co. has shipped 60,000 garments")


# ── selection ──────────────────────────────────────────────────────────────
class TestPrioritise:
    def test_duplicates_are_dropped(self):
        """AgroPulse's market claim was checked twice, differing only in a
        non-breaking hyphen."""
        out = router.prioritise([
            "The addressable market for precision‑ag tools for mid‑size operations is $1.1B.",
            "The addressable market for precision-ag tools for mid-size operations is $1.1B.",
        ], "AgroPulse")
        assert len(out["selected"]) == 1
        assert out["skipped"][0]["reason"].startswith("duplicate")

    def test_fragments_are_skipped_with_a_reason(self):
        out = router.prioritise(["This is a faithful reproduc1on of the"], "Airbnb")
        assert out["selected"] == []
        assert out["skipped"][0]["kind"] == GARBLED

    def test_checkable_claims_go_first(self):
        out = router.prioritise([
            "ARR $11.4M (was $3.9M 12 months ago)",
            "We have 40 enterprise customers",
            "There are over 2 million mid-size farms in the US.",
            "Employer pricing is $8 per employee per month.",
        ], "FlowDesk")
        kinds = [rc.kind for rc in out["selected"]]
        assert kinds == [MARKET, COMPANY, INTERNAL, INTERNAL]

    def test_only_five_are_selected_and_the_rest_are_explained(self):
        claims = [f"There are over {n} million farms in the US." for n in range(2, 10)]
        out = router.prioritise(claims, "AgroPulse", slots=5)
        assert len(out["selected"]) == 5
        assert all("most checkable" in s["reason"] for s in out["skipped"])

    def test_extractor_order_is_kept_within_a_kind(self):
        first = "There are over 2 million mid-size farms in the US."
        second = "Droughts have reduced California yields by 23% in the last decade."
        out = router.prioritise([first, second], "AgroPulse")
        assert [rc.claim for rc in out["selected"]] == [first, second]


# ── retrieval ──────────────────────────────────────────────────────────────
class TestSearchModes:
    def test_both_mode_searches_with_and_without_the_company(self):
        from agents.claim_verifier import build_queries

        queries = build_queries("Medallions cost ~$500k, drivers make 31k", company="Uber",
                                search="both")
        assert '"Medallions cost ~$500k, drivers make 31k"' in queries
        assert any(q.startswith('"Uber"') for q in queries)
        assert not any("startup company news" in q for q in queries), (
            "company-news templates retrieve the company, not the claim"
        )

    def test_company_mode_is_unchanged(self):
        from agents.claim_verifier import build_queries

        assert build_queries("ARR grew 4x", company="Acme")[:5] == [
            '"Acme" ARR grew 4x', "Acme ARR grew 4x", '"ARR grew 4x"',
            '"Acme" funding revenue customers announcement', "Acme startup company news",
        ]

    def test_both_mode_judges_relevance_against_the_claim(self, monkeypatch):
        import agents.claim_verifier as cv

        seen = {}
        monkeypatch.setattr(cv, "search_web_with_provenance", lambda q, max_results=5: {
            "results": [], "provider": "duckduckgo", "attempts": [], "errors": []})
        monkeypatch.setattr(cv, "filter_sources",
                            lambda items, context="", company="": (seen.update(context=context) or ([], [])))
        cv.collect_evidence("Medallions cost ~$500k", company="Uber",
                            context="a long deck description", search="both")
        assert seen["context"] == "Medallions cost ~$500k"


# ── the verdict cache ──────────────────────────────────────────────────────
class FakeCacheDB:
    """Just enough of a connection for claim_cache: one table, keyed rows."""

    def __init__(self):
        self.rows = {}
        self.fail = False

    def connection(self):
        db = self

        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *a): return False

            def execute(self, sql, params):
                if db.fail:
                    raise RuntimeError("database unreachable")
                self._sql, self._params = sql, params
                if sql.lstrip().upper().startswith("INSERT"):
                    import json
                    key, _claim, _company, result = params
                    db.rows[key] = {"result": json.loads(result), "created_at": "2026-09-12T00:00:00"}

            def fetchone(self):
                return db.rows.get(self._params[0])

        class Conn:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def cursor(self): return Cursor()
            def commit(self): pass

        return Conn()


@pytest.fixture
def cache(monkeypatch):
    import agents.claim_cache as claim_cache
    import db as real_db

    fake = FakeCacheDB()
    monkeypatch.setattr(claim_cache, "ENABLED", True)
    monkeypatch.setattr(real_db, "connection", fake.connection)
    return claim_cache, fake


VERDICT = {"claim": "c", "verdict": "SUPPORTS", "confidence": 0.9, "reasoning": "r",
           "key_evidence": "", "sources": ["https://x"], "total_sources": 3}


class TestTheCache:
    def test_a_stored_verdict_comes_back_marked_as_cached(self, cache):
        claim_cache, _ = cache
        assert claim_cache.put("c", "Acme", "2011", "company", dict(VERDICT))
        got = claim_cache.get("c", "Acme", "2011", "company")
        assert got["verdict"] == "SUPPORTS"
        assert got["cached"] is True and got["cached_at"]

    @pytest.mark.parametrize("flag", ["_degraded", "evidence_degraded"])
    def test_a_degraded_verdict_is_never_stored(self, cache, flag):
        claim_cache, fake = cache
        assert not claim_cache.put("c", "Acme", "", "company", {**VERDICT, flag: True})
        assert fake.rows == {}

    @pytest.mark.parametrize("other", [
        ("c", "Other Co", "2011", "company"),
        ("c", "Acme", "2012", "company"),
        ("c", "Acme", "2011", "both"),
    ])
    def test_every_input_that_changes_the_answer_changes_the_key(self, cache, other):
        claim_cache, _ = cache
        claim_cache.put("c", "Acme", "2011", "company", dict(VERDICT))
        assert claim_cache.get(*other) is None

    def test_a_new_verifier_version_stops_serving_old_verdicts(self, cache, monkeypatch):
        claim_cache, _ = cache
        claim_cache.put("c", "Acme", "", "company", dict(VERDICT))
        monkeypatch.setattr(claim_cache, "VERSION", "next")
        assert claim_cache.get("c", "Acme", "", "company") is None

    def test_an_unreachable_database_is_a_miss_not_a_failure(self, cache):
        claim_cache, fake = cache
        fake.fail = True
        assert claim_cache.get("c", "Acme", "", "company") is None
        assert claim_cache.put("c", "Acme", "", "company", dict(VERDICT)) is False

    def test_evidence_text_is_not_stored(self, cache):
        claim_cache, fake = cache
        claim_cache.put("c", "Acme", "", "company", {**VERDICT, "evidence_text": "x" * 5000})
        assert "evidence_text" not in next(iter(fake.rows.values()))["result"]

    def test_a_recheck_returns_the_same_verdict_without_searching(self, cache, monkeypatch):
        """The run-to-run determinism this exists for."""
        import agents.claim_verifier as cv

        calls = {"search": 0, "judge": 0}

        def evidence(*a, **k):
            calls["search"] += 1
            return {"snippets": [{"title": "t", "url": "https://x", "snippet": "s"}],
                    "full_texts": [], "sources": ["https://x"], "dropped": [],
                    "retrieved_before_filter": 1, "providers": {"duckduckgo": 1},
                    "general_web_unavailable": False}

        def judge(*a, **k):
            calls["judge"] += 1
            return {"verdict": "SUPPORTS" if calls["judge"] == 1 else "REFUTES",
                    "confidence": 0.9, "reasoning": "r", "key_evidence": ""}

        monkeypatch.setattr(cv, "collect_evidence", evidence)
        monkeypatch.setattr(cv, "groq_judge", judge)

        first = cv.verify_claim("c", verbose=False, company="Acme")
        second = cv.verify_claim("c", verbose=False, company="Acme")
        assert first["verdict"] == second["verdict"] == "SUPPORTS"
        assert calls == {"search": 1, "judge": 1}
        assert second["cached"] is True


# ── the score ──────────────────────────────────────────────────────────────
class TestPrivateMetricsDoNotCountAgainstTheCompany:
    def _features(self, claims):
        from ml.evidence_fusion import extract_features
        return extract_features(claims, risk_result=None, specialist_results=None)

    def test_a_private_metric_nobody_could_confirm_is_not_a_penalty(self):
        f = self._features([{"claim": "ARR $5M", "verdict": "NOT_ENOUGH_INFO",
                             "claim_kind": "internal"}])
        assert f.n_claims == 0 and f.unsupported_fraction == 0.0

    def test_a_private_metric_that_was_confirmed_still_counts(self):
        f = self._features([{"claim": "ARR $5M", "verdict": "SUPPORTS", "claim_kind": "internal"}])
        assert f.n_claims == 1 and f.supported_fraction == 1.0

    def test_an_unconfirmed_public_claim_still_counts(self):
        f = self._features([{"claim": "Raised $4M", "verdict": "NOT_ENOUGH_INFO",
                             "claim_kind": "company"}])
        assert f.unsupported_fraction == 1.0


# ── end to end ─────────────────────────────────────────────────────────────
class TestThePipelineRoutesClaims:
    def _wire(self, monkeypatch, seen):
        import ventureflow_agent as agent

        def claim(text, **kw):
            seen.append((text, kw.get("search")))
            return {"claim": text, "verdict": "NOT_ENOUGH_INFO", "confidence": 0.5,
                    "reasoning": "r", "key_evidence": "", "sources": [],
                    "total_sources": 2, "full_pages_read": 0}

        monkeypatch.setattr(agent, "verify_claim", claim)
        monkeypatch.setattr(agent, "score_risk", lambda *a, **k: {
            "risk_level": "LOW", "overall_score": 20, "key_concerns": [],
            "positive_factors": [], "red_flags": [], "total_signals": 0,
            "disclosure_severity": 0.2, "deck_signals": []})
        monkeypatch.setattr(agent, "run_investment_agents", lambda **k: {
            "market": {"confidence": 0.7, "signals": []}})
        monkeypatch.setattr(agent, "build_context", lambda *a: {"relevant_reports": []})
        monkeypatch.setattr(agent, "format_context_for_llm", lambda *a: "")
        monkeypatch.setattr(agent, "get_client", lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="memo"))],
                usage=SimpleNamespace(total_tokens=10))))))

    def test_selection_kinds_and_skips_reach_the_report(self, monkeypatch):
        import ventureflow_agent as agent

        seen: list = []
        self._wire(monkeypatch, seen)
        report = agent.run_due_diligence(
            "AgroPulse",
            company_description="Precision agriculture software for mid-size farms.",
            claims_to_verify=[
                "ARR $1.2M (was $300K a year ago)",
                "There are over 2 million mid-size farms in the US.",
                "There are over 2 million mid‑size farms in the US.",
                "This is a faithful reproduc1on of the",
                "Mid Farm tier priced at $349 per month for up to 1,000 acres.",
            ],
            filing_text="AgroPulse builds precision agriculture software. " * 10,
            sector="B2B", stage="Seed",
        )
        claims = report["sections"]["claims"]
        checked = [d["claim"] for d in claims["details"]]

        assert checked[0].startswith("There are over 2 million"), "market fact not first"
        assert len(checked) == 3, checked
        assert {d["claim_kind"] for d in claims["details"]} == {MARKET, COMPANY, INTERNAL}
        reasons = " ".join(s["reason"] for s in claims["skipped"])
        assert "duplicate" in reasons and "fragment" in reasons
        assert ("There are over 2 million mid-size farms in the US.", "both") in seen


class TestShortRealClaimsAreKept:
    """None of the 132 stored claims was under four words, but a real short
    claim silently left unchecked is the expensive mistake."""

    @pytest.mark.parametrize("claim", [
        "SOC 2 certified", "FDA cleared", "ISO 27001 certified", "YC-backed",
        "Series A funded", "ARR $5.1M",
    ])
    def test_not_a_fragment(self, claim):
        assert router.classify(claim, "Acme").kind != GARBLED

    @pytest.mark.parametrize("claim", ["claim one", "a claim", "Market", "x"])
    def test_still_a_fragment(self, claim):
        assert router.classify(claim, "Acme").kind == GARBLED

