"""Evaluation harness for risk detection, modeled on
`ml/scripts/eval_claim_verifier.py`.

Scores three detectors against the hand-labeled benchmark in
`ml/eval/risk_benchmark.jsonl` (see `ml/scripts/build_risk_benchmark.py` for
how that file was built and labeled):

  keyword     `agents/risk_detector.detect_signals()` -- the keyword dictionary
              currently in production. Flags an excerpt if any signal matches.
  tone_model  the trained Risk/Tone model (`ml/models/risk_tone_model.txt`),
              trained but never wired in or compared against the incumbent.
              Flags an excerpt when it predicts negative tone.
  llm         `agents/risk_detector.groq_risk_analysis()` -- the LLM half of the
              production path, given the same excerpt and the same keyword
              signals the production path would hand it.

The metric that matters most here is not recall. A risk detector that flags
everything scores perfect recall and is useless, because the input it actually
sees -- SEC risk factors, safe-harbour paragraphs, accounting policy notes --
is saturated with the vocabulary of risk while disclosing nothing. So the
headline number reported alongside precision/recall/F1 is the **boilerplate
false-positive rate**: the share of the 13 hand-labeled risk-free excerpts a
detector flags anyway. That number was completely unmeasured before this file
existed.

The LLM detector is run WITHOUT the web-search step the production
`score_risk()` performs. A benchmark excerpt is a paragraph, not a company to
search for, and leaving the search in would make the comparison depend on what
DuckDuckGo returned that minute rather than on the detector. The keyword
signals passed to the LLM are exactly the ones production would pass, so the
two halves of the production path stay comparable to each other.

    python ml/scripts/eval_risk_detector.py                    # all three
    python ml/scripts/eval_risk_detector.py --detectors keyword tone_model
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: E402,F401  (imported for side effect)

BENCHMARK_PATH = ROOT / "ml" / "eval" / "risk_benchmark.jsonl"
RESULTS_PATH = ROOT / "ml" / "eval" / "risk_benchmark_results.json"
RISK_MODEL_PATH = ROOT / "ml" / "models" / "risk_tone_model.txt"
RISK_ENCODERS_PATH = ROOT / "ml" / "models" / "risk_tone_model_encoders.pkl"


def load_benchmark(path: Path | str | None = None) -> list[dict[str, Any]]:
    rows = []
    with open(path or BENCHMARK_PATH, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure function over {gold_risk, predicted_risk, subset, gold_categories,
    predicted_categories} rows. No network, no model loading -- unit-tested
    directly in tests/test_eval_risk_detector.py."""
    tp = sum(1 for r in rows if r["gold_risk"] and r["predicted_risk"])
    fp = sum(1 for r in rows if not r["gold_risk"] and r["predicted_risk"])
    fn = sum(1 for r in rows if r["gold_risk"] and not r["predicted_risk"])
    tn = sum(1 for r in rows if not r["gold_risk"] and not r["predicted_risk"])

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    boilerplate = [r for r in rows if not r["gold_risk"]]
    flagged_boilerplate = [r for r in boilerplate if r["predicted_risk"]]

    # Category agreement, reported only over the examples that genuinely carry
    # risk. Scoring categories on risk-free excerpts would double-count the
    # false-positive rate, which is already reported on its own above.
    category_hits = category_predicted = category_gold = 0
    for row in rows:
        if not row["gold_risk"]:
            continue
        gold = set(row.get("gold_categories") or [])
        predicted = set(row.get("predicted_categories") or [])
        category_hits += len(gold & predicted)
        category_predicted += len(predicted)
        category_gold += len(gold)
    category_precision = category_hits / category_predicted if category_predicted else 0.0
    category_recall = category_hits / category_gold if category_gold else 0.0

    # Ranking quality, when the detector exposes a continuous score. A
    # detector whose hard decision never fires can still rank risky text above
    # risk-free text, and that distinction decides whether the thing is broken
    # or merely mis-thresholded -- worth separating before writing either one
    # off. Plain rank-based AUC, no sklearn dependency for a 28-row list.
    auc = None
    scored = [r for r in rows if r.get("score") is not None]
    if len(scored) == len(rows) and rows:
        positives = [r["score"] for r in rows if r["gold_risk"]]
        negatives = [r["score"] for r in rows if not r["gold_risk"]]
        if positives and negatives:
            wins = sum(
                1.0 if p > n else 0.5 if p == n else 0.0
                for p in positives for n in negatives
            )
            auc = round(wins / (len(positives) * len(negatives)), 3)

    return {
        "n": len(rows),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "score_roc_auc": auc,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "accuracy": round((tp + tn) / len(rows), 3) if rows else 0.0,
        "boilerplate_false_positive_rate": round(len(flagged_boilerplate) / len(boilerplate), 3) if boilerplate else 0.0,
        "boilerplate_n": len(boilerplate),
        "boilerplate_flagged_ids": [r["id"] for r in flagged_boilerplate],
        "missed_red_flag_ids": [r["id"] for r in rows if r["gold_risk"] and not r["predicted_risk"]],
        "category_precision": round(category_precision, 3),
        "category_recall": round(category_recall, 3),
    }


# --------------------------------------------------------------------------
# Detectors. Each returns (flagged, categories, detail) for one excerpt.
# --------------------------------------------------------------------------

def detector_keyword(row: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    from agents.risk_detector import detect_signals

    signals = detect_signals(row["text"])
    matched = sorted(signals)
    total = sum(len(v) for v in signals.values())
    return bool(signals), matched, {
        "signals": {category: [s["signal"] for s in hits] for category, hits in signals.items()},
        "total_signals": total,
        "score": float(total),
    }


def detector_keyword_plus_financials(row: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    """The SEC keyword dictionary composed with the deterministic deck reader.

    Kept as a separate arm rather than folded into `detector_keyword`, so that
    `keyword` remains an unmoved control. The point of the comparison is that
    the dictionary is not being replaced -- it is genuinely the stronger
    detector on filing prose, which is what it was built from -- but it is blind
    to the register a pitch deck is written in. Measured on this benchmark it
    missed all three deck red flags (`deck_customer_concentration`,
    `deck_runway_crunch`, `deck_founder_departure_ip`), each of which states its
    risk as arithmetic rather than as a term of art.

    The number to watch is NOT recall. It is the false-positive rate on the 13
    deliberately hard risk-free negatives -- safe-harbour paragraphs, ASC 606
    notes, a critical audit matter -- because a detector that flags everything
    scores perfect recall and is worthless on documents that are mostly hedged
    legal prose.
    """
    from agents.deck_financials import deck_risk_signals
    from agents.risk_detector import detect_signals

    signals = detect_signals(row["text"])
    deck = deck_risk_signals(row["text"])
    for entry in deck:
        signals.setdefault(entry["category"], []).append({
            "signal": entry["signal"], "context": entry["context"],
        })

    total = sum(len(v) for v in signals.values())
    return bool(signals), sorted(signals), {
        "signals": {category: [s["signal"] for s in hits] for category, hits in signals.items()},
        "total_signals": total,
        "score": float(total),
        "deck_signals": [entry["signal"] for entry in deck],
    }


_tone_state: dict[str, Any] | None = None


def _load_tone_model() -> dict[str, Any]:
    global _tone_state
    if _tone_state is None:
        import pickle

        import lightgbm as lgb

        if not RISK_MODEL_PATH.exists():
            raise FileNotFoundError(
                f"{RISK_MODEL_PATH} is missing -- it is gitignored (see .gitignore). "
                "Regenerate with: python ml/scripts/train_risk_model.py"
            )
        with open(RISK_ENCODERS_PATH, "rb") as handle:
            encoders = pickle.load(handle)
        _tone_state = {
            "booster": lgb.Booster(model_file=str(RISK_MODEL_PATH)),
            **encoders,
        }
    return _tone_state


def detector_tone_model(row: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    """The trained Risk/Tone model, used the only way it can be used here.

    It predicts negative/neutral/positive *tone*, not a risk category, so it
    contributes no categories -- category precision/recall are reported as
    zero for it by construction, which is a property of the model and not a
    measurement failure. Flag = the model calls the excerpt negative.
    """
    state = _load_tone_model()
    features = state["svd"].transform(state["tfidf"].transform([row["text"][:4000]]))
    probabilities = state["booster"].predict(features)[0]
    classes = list(state["label_encoder"].classes_)
    scores = dict(zip(classes, (float(p) for p in probabilities)))
    predicted = max(scores, key=scores.get)
    return predicted == "negative", [], {
        "predicted_tone": predicted,
        "probabilities": {k: round(v, 3) for k, v in scores.items()},
        "score": round(scores.get("negative", 0.0), 4),
    }


def _llm_detector(row: dict[str, Any], flag_levels: set[str]) -> tuple[bool, list[str], dict[str, Any]]:
    from agents.risk_detector import detect_signals, groq_risk_analysis

    company = row["source"].split("|")[0].strip() or "the company"
    text_signals = detect_signals(row["text"])
    result = groq_risk_analysis(
        company=company,
        text_signals=text_signals,
        web_signals={},
        # Empty on purpose: no web-search step in the benchmark, see the module
        # docstring. The prompt already handles the no-web-data case.
        web_snippets=[],
        source_text=row["text"],
    )
    level = str(result.get("overall_risk_level") or result.get("risk_level") or "UNKNOWN").upper()
    # The LLM returns free-text concerns, not category labels, so categories are
    # recovered by matching its concern text against the same five category
    # names the keyword dictionary uses.
    from agents.risk_detector import RISK_SIGNALS

    blob = " ".join(
        str(x) for x in (result.get("key_concerns") or []) + (result.get("red_flags") or [])
    ).lower()
    categories = [
        category for category, keywords in RISK_SIGNALS.items()
        if any(keyword.lower() in blob for keyword in keywords)
    ]
    raw_score = result.get("overall_score")
    return level in flag_levels, categories, {
        "risk_level": level,
        "overall_score": raw_score,
        "score": float(raw_score) if isinstance(raw_score, (int, float)) else None,
        "key_concerns": result.get("key_concerns"),
        "red_flags": result.get("red_flags"),
    }


def detector_llm_medium_plus(row: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    return _llm_detector(row, {"MEDIUM", "HIGH", "CRITICAL"})


def detector_llm_high_only(row: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    return _llm_detector(row, {"HIGH", "CRITICAL"})


DETECTORS: dict[str, Callable[[dict[str, Any]], tuple[bool, list[str], dict[str, Any]]]] = {
    "keyword": detector_keyword,
    "keyword_plus_financials": detector_keyword_plus_financials,
    "tone_model": detector_tone_model,
    "llm_medium_plus": detector_llm_medium_plus,
    "llm_high_only": detector_llm_high_only,
}

# llm_medium_plus and llm_high_only are two thresholds over the SAME LLM call.
# Running the detector twice would double the token spend and introduce
# sampling noise between two numbers that are meant to differ only by
# threshold, so the second is derived from the first's cached raw output.
_llm_cache: dict[str, dict[str, Any]] = {}


def _cache_path(out_path: Path) -> Path:
    return out_path.with_suffix(".llm_cache.jsonl")


def load_llm_cache(out_path: Path) -> None:
    """Reload LLM judgements scored by an earlier, interrupted run.

    Without this the cache lived only in memory, so a run killed by an
    exhausted quota threw away every excerpt it had already paid for. That is
    affordable when tokens are plentiful and not otherwise: on the free tier
    the daily cap releases roughly 8,760 tokens/hour against ~2,250 needed per
    excerpt, so one excerpt costs about a quarter-hour of waiting and a lost
    run costs hours. The claim harness already resumes from a partial log for
    exactly this reason; this is the same idea applied to the same constraint.
    """
    path = _cache_path(out_path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue  # a run killed mid-write leaves one truncated line
        _llm_cache[entry["id"]] = entry["detail"]
    if _llm_cache:
        print(f"Reusing {len(_llm_cache)} cached LLM judgement(s) from {path.name}")


def _append_llm_cache(out_path: Path, excerpt_id: str, detail: dict[str, Any]) -> None:
    with open(_cache_path(out_path), "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"id": excerpt_id, "detail": detail}) + "\n")


def run_detector(
    name: str,
    benchmark: list[dict[str, Any]],
    sleep_s: float = 0.0,
    provider_retries: int = 5,
    retry_wait_s: float = 120.0,
    out_path: Path | None = None,
) -> dict[str, Any]:
    rows = []
    for position, item in enumerate(benchmark, 1):
        if name.startswith("llm_"):
            cached = _llm_cache.get(item["id"])
            if cached is None:
                flagged, categories, detail = detector_llm_medium_plus(item)
                # Wait out a rate limit before giving up. Groq's free tier caps
                # tokens per day on a rolling window, so quota trickles back
                # rather than arriving all at once, and one excerpt costs about
                # 1,600 tokens -- a few minutes of accumulated allowance. Same
                # reasoning as the claim harness.
                for attempt in range(1, provider_retries + 1):
                    if not (detail.get("risk_level") == "UNKNOWN" and detail.get("overall_score") == 30):
                        break
                    print(f"    provider unavailable; waiting {retry_wait_s:.0f}s "
                          f"(attempt {attempt}/{provider_retries})")
                    time.sleep(retry_wait_s)
                    flagged, categories, detail = detector_llm_medium_plus(item)
                # Refuse to score a provider outage. groq_risk_analysis degrades
                # to this exact fallback on any exception, including a 429, and
                # a run that records it produces a detector that "flags nothing"
                # -- a statement about Groq's daily quota, not about the
                # detector. This was not hypothetical: the first post-fix run of
                # this harness hit the free tier's 200k-tokens-per-day ceiling
                # and reported precision 0.0 / recall 0.0 across all 28 rows.
                if detail.get("risk_level") == "UNKNOWN" and detail.get("overall_score") == 30:
                    raise RuntimeError(
                        f"The LLM risk detector reported itself unavailable on {item['id']} "
                        "(Groq call failed -- most likely the free tier's daily token limit). "
                        "This is a provider failure, not a detection result; re-run when quota "
                        "is available rather than reporting these numbers."
                    )
                _llm_cache[item["id"]] = detail
                # Persist immediately, not at the end of the run. The whole
                # point is to survive the run being killed mid-grind.
                if out_path is not None:
                    _append_llm_cache(out_path, item["id"], detail)
                cached = detail
            level = str(cached.get("risk_level", "UNKNOWN")).upper()
            allowed = {"MEDIUM", "HIGH", "CRITICAL"} if name == "llm_medium_plus" else {"HIGH", "CRITICAL"}
            flagged = level in allowed
            from agents.risk_detector import RISK_SIGNALS
            blob = " ".join(
                str(x) for x in (cached.get("key_concerns") or []) + (cached.get("red_flags") or [])
            ).lower()
            categories = [c for c, kws in RISK_SIGNALS.items() if any(k.lower() in blob for k in kws)]
            detail = cached
        else:
            flagged, categories, detail = DETECTORS[name](item)

        rows.append({
            "id": item["id"],
            "subset": item["subset"],
            "gold_risk": item["gold_risk"],
            "gold_categories": item["gold_categories"],
            "gold_severity": item["gold_severity"],
            "predicted_risk": bool(flagged),
            "predicted_categories": categories,
            # Surfaced to the top level so compute_metrics can rank without
            # knowing any detector's internal detail shape.
            "score": detail.get("score"),
            "detail": detail,
        })
        print(f"  [{position}/{len(benchmark)}] {item['id']:<40} gold={item['gold_risk']!s:<5} pred={flagged!s:<5}")
        if sleep_s:
            time.sleep(sleep_s)
    return {"metrics": compute_metrics(rows), "rows": rows}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Score risk detectors against the labeled benchmark.")
    parser.add_argument("--benchmark", default=str(BENCHMARK_PATH))
    parser.add_argument("--out", default=str(RESULTS_PATH))
    parser.add_argument("--detectors", nargs="+", default=list(DETECTORS))
    parser.add_argument("--sleep", type=float, default=1.0,
                        help="seconds between LLM calls; the free Groq tier is 8k tokens/minute")
    parser.add_argument("--provider-retries", type=int, default=5,
                        help="how many times to wait out a provider/quota failure per excerpt")
    parser.add_argument("--retry-wait", type=float, default=120.0,
                        help="seconds to wait between those retries")
    args = parser.parse_args()

    load_llm_cache(Path(args.out))
    benchmark = load_benchmark(args.benchmark)
    print(f"Loaded {len(benchmark)} labeled excerpts "
          f"({sum(1 for r in benchmark if r['gold_risk'])} red flags / "
          f"{sum(1 for r in benchmark if not r['gold_risk'])} boilerplate)\n")

    output: dict[str, Any] = {
        "benchmark": Path(args.benchmark).name,
        "note": "LLM detector runs without the web-search step of the production score_risk(); see module docstring.",
        "detectors": {},
    }
    for name in args.detectors:
        if name not in DETECTORS:
            raise SystemExit(f"Unknown detector {name!r}; choose from {sorted(DETECTORS)}")
        print(f"--- {name} ---")
        try:
            output["detectors"][name] = run_detector(
                name, benchmark,
                args.sleep if name.startswith("llm_") else 0.0,
                provider_retries=args.provider_retries,
                retry_wait_s=args.retry_wait,
                out_path=Path(args.out),
            )
        except (FileNotFoundError, RuntimeError) as exc:
            # A missing gitignored model file, or an exhausted LLM quota, is a
            # real and reportable state -- but not a reason to throw away the
            # other detectors' numbers, and not something to write into the
            # results file as if it were a measurement.
            print(f"  SKIPPED: {exc}")
            output["detectors"][name] = {"unavailable": str(exc)}
        print()

    Path(args.out).write_text(json.dumps(output, indent=2), encoding="utf-8")

    print("=" * 78)
    header = f"{'detector':<18}{'prec':>7}{'recall':>8}{'F1':>7}{'acc':>7}{'boilerplate FP':>17}{'AUC':>8}"
    print(header)
    print("-" * 78)
    for name, result in output["detectors"].items():
        if "unavailable" in result:
            reason = result["unavailable"].split(" -- ")[0].split(". ")[0]
            print(f"{name:<18}  UNAVAILABLE: {reason[:56]}")
            continue
        m = result["metrics"]
        print(f"{name:<18}{m['precision']:>7}{m['recall']:>8}{m['f1']:>7}{m['accuracy']:>7}"
              f"{m['boilerplate_false_positive_rate']:>17}{str(m['score_roc_auc']):>8}")
    print("=" * 78)
    print(f"\nFull per-excerpt results saved to {args.out}")


if __name__ == "__main__":
    main()
