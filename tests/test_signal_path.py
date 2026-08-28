"""Real deck content must reach whatever consumes it -- every field, every hop.

THE BUG CLASS THIS EXISTS TO CATCH

Three instances have now shipped silently, none of which raised an error,
failed a test, or produced an implausible number:

  * `stage` hardcoded to None in the pipeline -- 42 points of the score model's
    range, discarded on every analysis ever run.
  * `description` truncated to 1,200 characters, flattening `desc_len` (a real
    model feature) to a near-constant across every deck.
  * `burn_rate` extracted by the regex extractor, then dropped by
    `PDFExtractResponse` because Pydantic discards undeclared keys, and then
    overwritten anyway by a literal `burn_rate: null` in the UI. Two
    independent layers of the same defect on one field.

A field being *declared* somewhere proves nothing. These tests walk the actual
chain -- extractor, upload response, UI payload, request model, pipeline -- and
fail if any hop drops a field something downstream reads.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import deck_metadata
from structured_extractor import _regex_fallback

DECK = (
    "Northwind Robotics - Seed Round. B2B enterprise SaaS developer tools for "
    "logistics operators. We closed $2.4M ARR, up from $310K, across 62 "
    "customers. Monthly burn $410K against $1.1M cash. 18 months runway. "
    "Team of 14. github.com/northwind-robotics  northwindrobotics.com"
)


# ── The audit itself, as a test ────────────────────────────────────────────


@pytest.fixture(scope="module")
def audit():
    subprocess.run(
        [sys.executable, "-W", "ignore", str(ROOT / "ml" / "scripts" / "audit_signal_path.py")],
        capture_output=True, text=True, cwd=str(ROOT), timeout=600,
    )
    path = ROOT / "ml" / "eval" / "signal_path_audit.json"
    if not path.exists():
        pytest.fail("signal path audit produced no report")
    return json.loads(path.read_text(encoding="utf-8"))


def test_no_consumed_field_is_dropped_on_the_way_to_its_consumer(audit):
    broken = [f for f in audit["fields"] if f["breaks_at"]]
    assert not broken, "fields that never reach their consumer:\n" + json.dumps(
        [{"field": f["field"], "breaks_at": f["breaks_at"]} for f in broken], indent=2
    )


def test_the_ui_hardcodes_no_field_it_was_handed(audit):
    """The `burn_rate: null` defect, generalised."""
    hardcoded = [f["field"] for f in audit["fields"] if f["ui_hardcoded"]]
    assert not hardcoded, f"UI writes a literal over extracted values: {hardcoded}"


def test_every_field_the_score_model_leans_on_is_covered(audit):
    covered = {f["field"] for f in audit["fields"]}
    for field in ("stage", "sector", "revenue", "burn_rate", "runway_months"):
        assert field in covered, f"{field} is not audited"


# ── Extraction: abstain rather than guess ──────────────────────────────────


def test_metadata_is_extracted_from_a_deck_that_states_it():
    meta = deck_metadata.extract(DECK, company="Northwind Robotics")
    assert meta.stage == "Seed"
    assert meta.sector == "B2B"
    assert meta.team_size == 14
    assert meta.github_url == "https://github.com/northwind-robotics"
    assert meta.domain == "northwindrobotics.com"


def test_a_deck_that_says_nothing_yields_none_not_a_default():
    """The whole point. A fabricated stage moves the score 42 points on the
    strength of an invention, and the report cannot tell the reader that."""
    meta = deck_metadata.extract(
        "We are building the future of work. Our team is passionate.",
        company="Vague Co",
    )
    assert meta.stage is None
    assert meta.sector is None
    assert meta.team_size is None
    assert meta.github_url is None
    assert meta.domain is None


def test_a_progression_phrase_is_not_read_as_the_round_being_raised():
    """Front's Series A deck was labelled Seed because it says 'record of
    capital efficiency Seed to Series A' -- a history line, not the ask."""
    stage, evidence = deck_metadata.extract_stage(
        "A record of capital efficiency: Seed to Series A on $3.1m raised."
    )
    assert stage == "Early", f"got {stage} from a progression phrase"
    assert "progression" in evidence


def test_a_single_passing_mention_is_not_a_sector():
    """Uber's 2008 consumer deck was labelled B2B on one occurrence of
    'infrastructure' inside a sentence about something else."""
    sector, _ = deck_metadata.extract_sector(
        "A location-based service. Extend infrastructure to other LBS applications."
    )
    assert sector is None


def test_a_competitors_domain_is_not_attributed_to_the_company():
    """Airbnb's deck yielded 'couchsurfing.com' -- a competitor on the market
    slide. With a company name supplied, an uncorroborated host is refused."""
    domain, _ = deck_metadata.extract_domain(
        "Competitors include couchsurfing.com and craigslist.org.",
        company="Airbnb",
    )
    assert domain is None


def test_an_aggregator_watermark_is_not_the_companys_domain():
    domain, _ = deck_metadata.extract_domain(
        "Editable PowerPoint version at PitchDeckCoach.com", company="Airbnb",
    )
    assert domain is None


def test_a_placeholder_contact_domain_is_refused():
    domain, _ = deck_metadata.extract_domain(
        "sales@company.com support@company.com", company="Front",
    )
    assert domain is None


def test_an_implausible_headcount_is_refused():
    """A 'team' of five thousand in a seed deck is a market figure."""
    size, _ = deck_metadata.extract_team_size("Our team of 50000 serves the market.")
    assert size is None


def test_the_regex_fallback_emits_the_metadata_fields():
    info = _regex_fallback(DECK, company="Northwind Robotics")
    for field in ("stage", "sector", "team_size", "github_url", "domain", "burn_rate"):
        assert field in info, f"{field} missing from the extractor's output"
    assert info["stage"] == "Seed"
    assert info["burn_rate"] is not None


def test_extraction_records_its_evidence():
    """A structured field that moves the score must be checkable by a reader."""
    meta = deck_metadata.extract(DECK, company="Northwind Robotics")
    assert meta.evidence.get("stage")
    assert "seed" in meta.evidence["stage"].lower()


# ── The frontend payload, checked as text ──────────────────────────────────


def test_the_frontend_sends_no_hardcoded_null_over_an_extracted_value():
    """Checked against the source, because no Python-side assertion could see
    a literal written in TypeScript."""
    source = (ROOT / "frontend" / "src" / "context" / "AppContext.tsx").read_text(
        encoding="utf-8", errors="replace"
    )
    match = re.search(r"startAnalysis\(\{(.*?)\n\s*\}\)", source, re.DOTALL)
    assert match, "could not find the analyze payload in AppContext.tsx"
    body = match.group(1)
    for field in ("revenue", "burn_rate", "runway_months"):
        assigned = re.search(rf"^\s*{field}:\s*(.+?),\s*$", body, re.MULTILINE)
        assert assigned, f"{field} is not in the analyze payload"
        value = assigned.group(1).strip()
        assert value != "null", (
            f"{field} is hardcoded to null in the UI, discarding whatever the "
            f"extractor found"
        )
