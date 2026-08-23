"""Score the trained TF-IDF Claim Model against the claim benchmark, on the
same evidence the LLM verifier saw.

Why this exists: `ml/models/claim_model_report.json` records a clean negative
result -- 45% accuracy, REFUTES F1 0.05 -- but that number is against SciFact's
own held-out split, which is scientific abstracts. Comparing it to the LLM
verifier's number on startup claims would be comparing two different tasks and
calling one better. This runs the same model against the same 150-example
benchmark the LLM verifier is scored on, so the two numbers are actually about
the same thing.

The evidence is not re-retrieved. `ml/scripts/eval_claim_verifier.py` persists
the exact web evidence its LLM judged on each row, and this reads it back. Two
models fed different search results are not a comparison of the models -- and
DuckDuckGo returns different results minute to minute, so re-retrieving would
have made the difference partly a measure of search variance.

The model expects "CLAIM: ... EVIDENCE: ..." exactly as
`ml/scripts/train_claim_model.py` builds it at training time. Using a different
template here would handicap the baseline by evaluating it off-distribution,
which would make the LLM look better for the wrong reason.

    python ml/scripts/eval_claim_model_baseline.py
    python ml/scripts/eval_claim_model_baseline.py \\
        --verifier-results ml/eval/claim_benchmark_results_v1_30.json \\
        --out ml/eval/claim_baseline_results_v1_30.json

Requires `ml/models/claim_model.txt` + `claim_model_encoders.pkl`, which are
gitignored (see .gitignore) and regenerate in about a minute with
`python ml/scripts/train_claim_model.py`.
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: E402,F401  (imported for side effect)

from ml.scripts.eval_claim_verifier import compute_metrics  # noqa: E402

MODEL_PATH = ROOT / "ml" / "models" / "claim_model.txt"
ENCODERS_PATH = ROOT / "ml" / "models" / "claim_model_encoders.pkl"
DEFAULT_VERIFIER_RESULTS = ROOT / "ml" / "eval" / "claim_benchmark_results.json"
DEFAULT_PARTIAL = ROOT / "ml" / "eval" / "claim_benchmark_results.partial.jsonl"
DEFAULT_OUT = ROOT / "ml" / "eval" / "claim_baseline_results.json"


def load_verifier_rows(results_path: Path, partial_path: Path) -> list[dict[str, Any]]:
    """Rows from a finished results file, or from the partial log of a run that
    has not finished yet.

    The partial path matters in practice: the 150-example run is rate-limited
    by a free-tier daily token ceiling and completes across sessions, and there
    is no reason the baseline cannot be scored on whatever subset has real
    evidence attached so far -- as long as the comparison is stated on that
    same subset, which is what `benchmark_subset` in the output records.
    """
    if results_path.exists():
        payload = json.loads(results_path.read_text(encoding="utf-8"))
        return payload.get("rows", [])
    if partial_path.exists():
        rows = []
        for line in partial_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows
    raise SystemExit(
        f"Neither {results_path.name} nor {partial_path.name} exists. "
        "Run ml/scripts/eval_claim_verifier.py first -- this script scores the "
        "baseline on the evidence that run retrieved."
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Score the TF-IDF Claim Model on the claim benchmark.")
    parser.add_argument("--verifier-results", default=str(DEFAULT_VERIFIER_RESULTS))
    parser.add_argument("--partial", default=str(DEFAULT_PARTIAL))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    if not MODEL_PATH.exists() or not ENCODERS_PATH.exists():
        raise SystemExit(
            f"{MODEL_PATH.name} is missing (it is gitignored). Regenerate it with:\n"
            "    python ml/scripts/train_claim_model.py"
        )

    import lightgbm as lgb

    booster = lgb.Booster(model_file=str(MODEL_PATH))
    with open(ENCODERS_PATH, "rb") as handle:
        encoders = pickle.load(handle)
    tfidf, svd, label_encoder = encoders["tfidf"], encoders["svd"], encoders["label_encoder"]

    verifier_rows = load_verifier_rows(Path(args.verifier_results), Path(args.partial))
    scored = [row for row in verifier_rows if (row.get("evidence") or "").strip()]
    skipped = [row["id"] for row in verifier_rows if not (row.get("evidence") or "").strip()]

    if not scored:
        raise SystemExit(
            "No rows carry retrieved evidence. Re-run ml/scripts/eval_claim_verifier.py; "
            "evidence capture was added on 23 Aug 2026 and older result files predate it."
        )

    texts = [
        # Exactly train_claim_model.py's template, including the 1,500-character
        # evidence cap it trained under.
        f"CLAIM: {row['claim']}  EVIDENCE: {row['evidence'][:1500]}"
        for row in scored
    ]
    features = svd.transform(tfidf.transform(texts))
    probabilities = booster.predict(features)
    classes = list(label_encoder.classes_)

    baseline_rows = []
    llm_rows = []
    for row, probability in zip(scored, probabilities):
        ranked = dict(zip(classes, (float(p) for p in probability)))
        predicted = max(ranked, key=ranked.get)
        baseline_rows.append({
            "id": row["id"],
            "subset": row.get("subset", ""),
            "gold": row["gold"],
            "predicted": predicted,
            # The model's own probability for the class it chose, used as its
            # confidence so the calibration check means the same thing for both
            # systems.
            "confidence": round(ranked[predicted], 3),
            "probabilities": {k: round(v, 3) for k, v in ranked.items()},
        })
        llm_rows.append({
            "id": row["id"],
            "subset": row.get("subset", ""),
            "gold": row["gold"],
            "predicted": row["predicted"],
            "confidence": row.get("confidence"),
        })

    baseline_metrics = compute_metrics(baseline_rows)
    llm_metrics = compute_metrics(llm_rows)

    output = {
        "benchmark_subset": {
            "n_scored": len(scored),
            "n_skipped_no_evidence": len(skipped),
            "skipped_ids": skipped,
            "note": (
                "Both systems are scored on exactly these rows and on exactly the "
                "same retrieved evidence, so the two metric blocks below are "
                "directly comparable."
            ),
        },
        "tfidf_claim_model": {
            "model": "ml/models/claim_model.txt (LightGBM over TF-IDF+SVD, trained on SciFact)",
            "metrics": baseline_metrics,
            "rows": baseline_rows,
        },
        "llm_web_search_verifier": {
            "model": "agents/claim_verifier.py (DuckDuckGo retrieval + openai/gpt-oss-120b judge)",
            "metrics": llm_metrics,
        },
    }
    Path(args.out).write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"Scored both systems on {len(scored)} benchmark claims "
          f"({len(skipped)} skipped for having no retrieved evidence)\n")
    header = f"{'system':<26}{'acc':>7}{'SUP F1':>9}{'REF F1':>9}{'NEI F1':>9}"
    print(header)
    print("-" * len(header))
    for label, metrics in (("TF-IDF Claim Model", baseline_metrics),
                           ("LLM + web search", llm_metrics)):
        per_class = metrics["per_class"]
        print(f"{label:<26}{metrics['accuracy']:>7}"
              f"{per_class['SUPPORTS']['f1']:>9}"
              f"{per_class['REFUTES']['f1']:>9}"
              f"{per_class['NOT_ENOUGH_INFO']['f1']:>9}")
    print(f"\nFull results saved to {args.out}")


if __name__ == "__main__":
    main()
