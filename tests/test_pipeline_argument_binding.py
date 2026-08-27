"""The API must invoke the pipeline with the arguments it thinks it is passing.

Regression tests for three bugs found by static analysis in the same call path,
none of which produced an error, a log line, or a failing test.

The API called `run_due_diligence` with twelve POSITIONAL arguments ending in
`on_stage`. The twelfth parameter is `deck_date`. So on every production
analysis:

  * `deck_date` received the stage callback -- a truthy function object -- which
    flowed into `as_of=deck_date or _infer_deck_vintage(...)` and was formatted
    into the claim-verification prompt as "<function record_stage at 0x...>";
  * `on_stage` fell back to None, so the `stage` column added in migration 008
    was never written outside tests.

And `_infer_deck_vintage` could not have saved it, because its regex contained
two LITERAL BACKSPACE BYTES where word-boundary escapes belong -- so it returned
"" for every deck ever analysed.

Together those meant the temporal grounding built to stop the verifier calling
four true historical claims lies at 0.96 confidence **never ran for a single
real user**. It worked only in ml/scripts/run_real_deck_corpus.py, which passes
deck_date by keyword -- which is exactly why the offline corpus results looked
correct while the product was broken.
"""

import inspect
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api
import ventureflow_agent


def test_the_year_regex_contains_no_control_characters():
    """The bug was invisible in every diff because a backspace renders as
    nothing. Assert on the bytes, not on appearance."""
    pattern = ventureflow_agent._YEAR_RE.pattern
    assert "\x08" not in pattern, "literal backspace byte back in the year regex"
    assert all(ord(ch) >= 32 or ch in "\t" for ch in pattern), (
        f"control character in year regex: {pattern!r}"
    )
    assert pattern.startswith("\\b") and pattern.endswith("\\b")


def test_no_source_file_contains_a_stray_backspace_byte():
    """Sweep the whole backend for the same accident. A control character in
    source is never intentional here and is undetectable by eye."""
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in root.rglob("*.py"):
        if any(part in {".venv", "__pycache__", "legacy", "node_modules"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            if any(ord(ch) < 32 and ch not in "\t" for ch in line):
                offenders.append(f"{path.relative_to(root)}:{number}")
    assert not offenders, f"control characters found in: {offenders}"


@pytest.mark.parametrize("text,expected", [
    ("Airbnb pitch deck 2009 seed round", "2009"),
    ("Founded in 2011, we now serve 800 paying users", "2011"),
    ("Q4 2016 traction update", "2016"),
    ("no year here at all", ""),
    ("version 20050 units shipped", ""),      # word boundary must reject this
    ("SKU 12009 in stock", ""),
])
def test_deck_vintage_inference_actually_works(text, expected):
    assert ventureflow_agent._infer_deck_vintage(text) == expected


def test_the_api_binds_every_pipeline_argument_by_keyword():
    """The structural fix. Positional binding is what allowed `on_stage` to land
    in `deck_date`; if this call ever reverts to positional args, a future
    parameter insertion silently re-creates the bug."""
    source = inspect.getsource(api._perform_analysis)
    call = source[source.index("run_due_diligence"):]
    call = call[: call.index(")\n") + 1]
    # No bare `request.x,` positional arguments -- every one must be `name=...`.
    positional = re.findall(r"^\s+(request\.\w+),\s*$", call, flags=re.MULTILINE)
    assert not positional, f"positional arguments passed to the pipeline: {positional}"
    assert "company_name=" in call and "deck_date=" in call and "on_stage=" in call


def test_every_pipeline_parameter_the_api_passes_actually_exists():
    """Catches a keyword typo, which is the one failure mode keyword binding
    introduces in exchange for the one it removes."""
    source = inspect.getsource(api._perform_analysis)
    call = source[source.index("run_due_diligence"):]
    call = call[: call.index(")\n") + 1]
    passed = set(re.findall(r"^\s+(\w+)=", call, flags=re.MULTILINE))
    accepted = set(inspect.signature(ventureflow_agent.run_due_diligence).parameters)
    assert passed <= accepted, f"unknown pipeline parameters: {sorted(passed - accepted)}"


def test_deck_date_reaches_the_pipeline_as_a_year_not_a_callable():
    """End-to-end binding check: what run_due_diligence would actually receive."""
    import functools

    request = api.DiligenceRequest(
        company_name="Acme", company_description="d" * 200,
        claims=["a claim"], deck_date="2011",
    )

    def on_stage(label):
        return None

    bound = inspect.signature(ventureflow_agent.run_due_diligence).bind(
        **functools.partial(
            lambda **kw: kw,
            company_name=request.company_name,
            company_description=request.company_description,
            claims_to_verify=request.claims,
            filing_text=request.filing_text,
            revenue=request.revenue,
            burn_rate=request.burn_rate,
            runway_months=request.runway_months,
            sector=request.sector,
            team_size=request.team_size,
            github_url=request.github_url,
            founders=request.founders,
            deck_date=request.deck_date,
            on_stage=on_stage,
        )()
    )
    bound.apply_defaults()
    assert bound.arguments["deck_date"] == "2011"
    assert callable(bound.arguments["on_stage"])
    assert not callable(bound.arguments["deck_date"]), (
        "deck_date received a callable -- the original bug"
    )


@pytest.mark.parametrize("bad", ["not-a-year", "12", "3025", "2011-06", "20115"])
def test_a_malformed_deck_date_is_rejected(bad):
    with pytest.raises(Exception):
        api.DiligenceRequest(
            company_name="X", company_description="y" * 200, deck_date=bad,
        )


@pytest.mark.parametrize("good", ["1998", "2009", "2011", "2026"])
def test_a_plausible_deck_year_is_accepted(good):
    assert api.DiligenceRequest(
        company_name="X", company_description="y" * 200, deck_date=good,
    ).deck_date == good


def test_an_absent_deck_date_stays_empty_rather_than_guessing():
    """Empty is honest. The pipeline falls back to inferring from deck text, and
    when that finds nothing the verifier is told the vintage is unknown rather
    than handed a fabricated year."""
    request = api.DiligenceRequest(company_name="X", company_description="y" * 200)
    assert request.deck_date == ""
