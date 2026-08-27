"""Can every trained artifact actually be loaded and used by the application?

WHY THIS EXISTS

The risk severity model was silently dead. Its custom transformer was defined
inside the training script, so pickle saved it as
`__main__.DeckFeatureTransformer` -- a path that resolves in no other process.
`agents/risk_disclosure` loaded the file, hit the unpickling error, and behaved
exactly as its degradation contract promises: `available: False`, and `None` for
every severity score.

The dangerous part is what did NOT happen. Nothing crashed. No test failed. Every
benchmark number stayed identical, because the evaluation harness re-TRAINS the
model rather than re-LOADING it. The only reason it was caught at all is that
someone happened to call `is_available()` by hand.

Fixing that one model proves nothing about the others, so this checks all of
them the same way, and checks the property that actually matters: not "does the
file exist" but **"can a fresh process load it and get a number out of it"**.

Each artifact is loaded in a SUBPROCESS with a clean interpreter, because a
module already imported in this process can mask exactly the `__main__`
reference problem being looked for.

    python ml/scripts/check_model_artifacts.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: F401  (Windows cp1252 guard)

# (label, file(s) that must exist, snippet that loads AND exercises it)
#
# Every snippet must produce a real output value, not merely import. "Loads" and
# "works" are different claims and only the second one matters.
CHECKS: list[tuple[str, list[str], str]] = [
    (
        "VentureFlow Score (ml/venturescore.py)",
        ["ml/models/venturescore_model.pkl"],
        """
from ml.venturescore import score_company
out = score_company(description="An AI developer tools platform for enterprise "
                                "engineering teams that automates code review.",
                    one_liner="AI code review", industry="B2B",
                    stage=None, location=None)
assert out.get("available"), out.get("reason")
assert 0 <= out["venture_score"] <= 100, out
print("venture_score=%s confidence=%s" % (out["venture_score"], out["confidence"]))
""",
    ),
    (
        "Outcome Model (ml/inference.py)",
        ["ml/models/outcome_model_combined.txt", "ml/models/outcome_model_encoders.pkl"],
        """
from ml.inference import is_available, score_company
assert is_available(), "outcome model reports itself unavailable"
out = score_company(text="An AI developer tools platform for enterprise engineering "
                         "teams that automates code review.",
                    industry="B2B", stage="Seed")
assert isinstance(out, dict) and out.get("available"), out
# NB the key name. ml/inference.py calls this `probability_survives_or_exits`
# while ml/venturescore.py calls the same quantity
# `probability_exit_or_survive`. Harmless here, but a caller reaching for the
# wrong one gets None and no error, which is the shape of several bugs already
# found in this codebase.
probability = out.get("probability_survives_or_exits")
assert probability is not None and 0.0 <= float(probability) <= 1.0, out
print("outcome probability=%.4f band=%s" % (float(probability), out.get("band")))
""",
    ),
    (
        "Risk disclosure model (agents/risk_disclosure.py)",
        ["ml/models/risk_disclosure_model.pkl"],
        """
from agents import risk_disclosure
assert risk_disclosure.is_available(), risk_disclosure.model_metadata()
p = risk_disclosure.severity("There is substantial doubt about our ability to "
                             "continue as a going concern.")
assert p is not None and 0.0 <= p <= 1.0, p
meta = risk_disclosure.model_metadata()
assert meta["available"] is True
print("severity(going concern)=%.3f uses_deck_features=%s" % (p, meta["uses_deck_features"]))
""",
    ),
    (
        "Text embedder (embeddings.py)",
        ["ml/models/text_embedder.pkl"],
        """
import embeddings
assert embeddings.is_available(), "embedder not loadable"
v = embeddings.embed_text("An AI developer tools platform for enterprise teams.")
assert v is not None and len(v) == embeddings.DIMENSIONS, (v is None, len(v or []))
print("embedding dims=%d" % len(v))
""",
    ),
    (
        "Comparables corpus (comparables.py)",
        ["ml/data/outcome_dataset.jsonl", "ml/models/text_embedder.pkl"],
        """
from comparables import find_comparables
out = find_comparables("An AI developer tools platform for enterprise teams.")
assert out.get("available"), out.get("reason")
assert out["comparables"], "no comparables returned"
assert out["population"]["n"] == 1560, out["population"]
print("comparables=%d population=%d" % (len(out["comparables"]), out["population"]["n"]))
""",
    ),
    (
        "Claim model (retired baseline, must still load)",
        ["ml/models/claim_model.txt", "ml/models/claim_model_encoders.pkl"],
        """
import lightgbm, pickle
booster = lightgbm.Booster(model_file="ml/models/claim_model.txt")
with open("ml/models/claim_model_encoders.pkl", "rb") as fh:
    enc = pickle.load(fh)
print("claim model trees=%d encoders=%s" % (booster.num_trees(), type(enc).__name__))
""",
    ),
    (
        "Risk/Tone model (retired, kept as documented negative result)",
        ["ml/models/risk_tone_model.txt", "ml/models/risk_tone_model_encoders.pkl"],
        """
import lightgbm, pickle
booster = lightgbm.Booster(model_file="ml/models/risk_tone_model.txt")
with open("ml/models/risk_tone_model_encoders.pkl", "rb") as fh:
    enc = pickle.load(fh)
print("risk/tone trees=%d encoders=%s" % (booster.num_trees(), type(enc).__name__))
""",
    ),
]


def run_check(label: str, files: list[str], snippet: str) -> dict:
    missing = [f for f in files if not (ROOT / f).exists()]
    if missing:
        return {"artifact": label, "status": "MISSING", "detail": f"absent: {missing}"}

    program = (
        "import sys, warnings\n"
        "warnings.filterwarnings('ignore')\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import console_safety\n"
        + snippet
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True, text=True, cwd=str(ROOT), timeout=300,
    )
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()
        return {"artifact": label, "status": "FAILED",
                "detail": tail[-1] if tail else "no stderr",
                "is_main_reference": "__main__" in (result.stderr or "")}
    return {"artifact": label, "status": "OK", "detail": (result.stdout or "").strip()}


def main() -> int:
    print("Loading each artifact in a CLEAN SUBPROCESS -- an already-imported")
    print("module in this process would mask the __main__ reference problem.\n")

    rows = [run_check(*check) for check in CHECKS]
    width = max(len(r["artifact"]) for r in rows)
    for row in rows:
        marker = {"OK": "  ok  ", "FAILED": " FAIL ", "MISSING": " GONE "}[row["status"]]
        print(f"[{marker}] {row['artifact']:<{width}}  {row['detail'][:90]}")
        if row.get("is_main_reference"):
            print(f"{'':>{width + 11}}  ^ __main__ reference: pickled inside a script, "
                  f"unloadable elsewhere")

    failed = [r for r in rows if r["status"] == "FAILED"]
    missing = [r for r in rows if r["status"] == "MISSING"]
    print(f"\n{len(rows) - len(failed) - len(missing)}/{len(rows)} artifacts load and "
          f"produce output in a fresh process.")

    out = ROOT / "ml" / "eval" / "model_artifact_check.json"
    out.write_text(json.dumps({
        "what_this_checks": (
            "That every trained artifact can be LOADED AND USED by a fresh "
            "interpreter, not merely that the file exists. Written after the risk "
            "severity model was found silently unloadable outside its trainer, "
            "with no test or benchmark reflecting the fact."
        ),
        "results": rows,
    }, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
