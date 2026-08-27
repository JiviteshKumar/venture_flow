"""Every trained artifact must load in a process that did not train it.

The regression this locks down: the risk severity model was pickled as
`__main__.DeckFeatureTransformer` and could not be loaded anywhere except its
own trainer. Nothing crashed, no test failed, and every benchmark number stayed
identical -- because the evaluation harness re-TRAINS rather than re-LOADS. The
product had silently lost a model while all the evidence said it was fine.

Fixing one model proved nothing about the others, so all seven are checked, and
the check is a test rather than only a script so it runs on every commit.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCRIPT = ROOT / "ml" / "scripts" / "check_model_artifacts.py"


@pytest.fixture(scope="module")
def artifact_report():
    result = subprocess.run(
        [sys.executable, "-W", "ignore", str(SCRIPT)],
        capture_output=True, text=True, cwd=str(ROOT), timeout=900,
    )
    path = ROOT / "ml" / "eval" / "model_artifact_check.json"
    if not path.exists():
        pytest.fail(f"artifact check produced no report:\n{result.stdout}\n{result.stderr}")
    return json.loads(path.read_text(encoding="utf-8"))


def test_no_artifact_fails_to_load(artifact_report):
    failed = [r for r in artifact_report["results"] if r["status"] == "FAILED"]
    assert not failed, "artifacts that will not load: " + json.dumps(failed, indent=2)


def test_no_artifact_was_pickled_with_a_main_reference(artifact_report):
    """The specific defect, named. A class defined in a script run as __main__
    is pickled by reference to a path that resolves in no other process."""
    offenders = [r for r in artifact_report["results"] if r.get("is_main_reference")]
    assert not offenders, (
        "pickled inside a training script and unloadable elsewhere: "
        + json.dumps(offenders, indent=2)
    )


def test_the_check_exercises_each_model_not_merely_imports_it(artifact_report):
    """"Loads" and "works" are different claims. Every passing row must carry
    real output -- a score, a probability, a dimension count."""
    for row in artifact_report["results"]:
        if row["status"] == "OK":
            assert row["detail"].strip(), f"{row['artifact']} produced no output"


def test_every_expected_artifact_is_covered(artifact_report):
    covered = " ".join(r["artifact"] for r in artifact_report["results"]).lower()
    for expected in ("ventureflow score", "outcome model", "risk disclosure",
                     "text embedder", "comparables"):
        assert expected in covered, f"{expected} is not checked"
