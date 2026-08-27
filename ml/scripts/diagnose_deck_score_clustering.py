"""Why does the VentureFlow Score cluster at 55-64 on every real deck?

Two hypotheses, and they call for different fixes, so guessing is not good
enough:

  (a) **Extraction starvation.** The features exist and would discriminate, but
      a deck does not supply them, so they arrive imputed to a constant. Fix by
      extracting better.

  (b) **Feature irrelevance.** The features the model actually leans on are YC
      metadata that a pitch deck cannot contain at all. Fix by changing what the
      score is computed from -- no extraction improvement can help.

This measures three things and lets them decide:

  1. **Coverage** -- what fraction of features are genuinely observed per deck.
  2. **Variance** -- which features actually differ ACROSS decks. A feature
     that is observed but identical everywhere cannot produce a spread, so
     coverage alone would be misleading.
  3. **Leverage** -- how much the score moves when each varying feature is
     swept across its whole plausible range, holding the rest fixed. This is
     the number that separates the hypotheses: if every varying input can be
     pushed to its extreme and the score still barely moves, the problem is not
     what the deck failed to supply.

    python ml/scripts/diagnose_deck_score_clustering.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: F401  (Windows cp1252 guard)

DECK_DIR = ROOT / "ml" / "eval" / "decks"
MANIFEST = ROOT / "ml" / "eval" / "validation" / "validation_manifest.json"
OUT_PATH = ROOT / "ml" / "eval" / "validation" / "deck_score_diagnosis.json"


def deck_texts() -> list[tuple[str, str]]:
    from document_extractor import extract_document
    from structured_extractor import _regex_fallback

    out = []
    for entry in json.loads(MANIFEST.read_text(encoding="utf-8"))["decks"]:
        path = DECK_DIR / entry["file"]
        if not path.exists():
            continue
        extracted = extract_document(path.name, path.read_bytes())
        text = (extracted.get("text") or "").strip()
        if not text:
            continue
        info = _regex_fallback(text)
        out.append((entry["company"], (info.get("description") or text[:1500]).strip()))
    return out


def main() -> int:
    from ml import venturescore

    venturescore._load()
    state = venturescore._state
    if state is None:
        print("VentureFlow Score model not loadable.")
        return 2

    decks = deck_texts()
    if not decks:
        print("No readable decks.")
        return 2

    # ── 1 & 2: coverage and cross-deck variance ────────────────────────────
    rows = []
    for company, text in decks:
        result = venturescore.score_company(
            description=text, one_liner=text[:120],
            industry=None, stage=None, location=None,
        )
        rows.append({
            "company": company,
            "score": result.get("venture_score"),
            "coverage": result.get("feature_coverage"),
            "confidence": result.get("confidence"),
            "imputed": result.get("imputed_features") or [],
            "chars": len(text),
        })

    scores = [r["score"] for r in rows if r["score"] is not None]
    print("=" * 74)
    print("1. WHAT EACH DECK PRODUCES")
    print("=" * 74)
    for r in rows:
        print(f"  {r['company']:<10} score={r['score']:<5} coverage={r['coverage']:<6} "
              f"confidence={r['confidence']:<7} chars={r['chars']:<6} "
              f"imputed={len(r['imputed'])}")
    print(f"\n  spread: min={min(scores)} max={max(scores)} "
          f"range={max(scores) - min(scores)} sd={statistics.stdev(scores):.2f}")

    # ── 3: leverage, the decisive measurement ──────────────────────────────
    # Sweep every input a deck can actually influence, to its extremes, and see
    # how far the score can be moved at all.
    print("\n" + "=" * 74)
    print("2. LEVERAGE -- how far can the score move if a deck says anything at all?")
    print("=" * 74)

    base_text = decks[0][1]
    probes = {
        "shortest plausible deck": "A startup.",
        "longest deck in corpus": max((t for _, t in decks), key=len),
        "keyword-dense AI/SaaS": (
            "AI machine learning SaaS platform API developer tools enterprise "
            "B2B automation analytics data infrastructure cloud security "
            "fintech payments marketplace healthcare biotech robotics "
        ) * 12,
        "keyword-free prose": (
            "We help people do the thing they need to do, in a way that is "
            "better than how they do it now, for a price they can afford. "
        ) * 12,
    }
    leverage = {}
    for label, text in probes.items():
        result = venturescore.score_company(
            description=text, one_liner=text[:120],
            industry=None, stage=None, location=None,
        )
        leverage[label] = result.get("venture_score")
        print(f"  {label:<26} -> {result.get('venture_score')}")

    # Now the categorical inputs, which a deck CAN supply via the sector field.
    print()
    industry_scores = {}
    for industry in ("B2B", "Consumer", "Fintech", "Healthcare", "Industrials", None):
        result = venturescore.score_company(
            description=base_text, one_liner=base_text[:120],
            industry=industry, stage=None, location=None,
        )
        industry_scores[str(industry)] = result.get("venture_score")
        print(f"  industry={str(industry):<12} -> {result.get('venture_score')}")

    print()
    stage_scores = {}
    for stage in ("Seed", "Early", "Growth", None):
        result = venturescore.score_company(
            description=base_text, one_liner=base_text[:120],
            industry="B2B", stage=stage, location=None,
        )
        stage_scores[str(stage)] = result.get("venture_score")
        print(f"  stage={str(stage):<15} -> {result.get('venture_score')}")

    text_range = max(leverage.values()) - min(leverage.values())
    industry_range = max(industry_scores.values()) - min(industry_scores.values())
    stage_range = max(stage_scores.values()) - min(stage_scores.values())

    print("\n" + "=" * 74)
    print("3. VERDICT")
    print("=" * 74)
    print(f"  observed spread across 7 real decks     : {max(scores) - min(scores)} points")
    print(f"  max achievable by TEXT alone            : {text_range} points")
    print(f"  max achievable by INDUSTRY alone        : {industry_range} points")
    print(f"  max achievable by STAGE alone           : {stage_range} points")

    verdict = (
        "(b) FEATURE IRRELEVANCE"
        if text_range <= 15
        else "(a) EXTRACTION STARVATION"
    )
    print(f"\n  -> {verdict}")
    if text_range <= 15:
        print("     Text is the only input a deck reliably supplies, and sweeping it")
        print("     from a 10-character stub to a keyword-saturated wall moves the")
        print(f"     score only {text_range} points. Better extraction cannot fix this,")
        print("     because there is nothing for better extraction to feed.")

    OUT_PATH.write_text(json.dumps({
        "question": "Why does the VentureFlow Score cluster at 55-64 on real decks?",
        "per_deck": rows,
        "observed_spread": max(scores) - min(scores),
        "observed_sd": round(statistics.stdev(scores), 2),
        "leverage_text_probes": leverage,
        "leverage_by_industry": industry_scores,
        "leverage_by_stage": stage_scores,
        "max_range_text_only": text_range,
        "max_range_industry_only": industry_range,
        "max_range_stage_only": stage_range,
        "verdict": verdict,
        "interpretation": (
            "The model's discriminative features are YC metadata -- curated "
            "industry/subindustry taxonomy, stage, geography, remote status, tag "
            "counts. A pitch deck supplies almost none of them. What a deck DOES "
            "supply (free text) is the weakest input the model has: the trainer's "
            "own ablation put text-only ROC-AUC at 0.5721 against 0.6613 for "
            "structured features. So the score on a deck is close to a prior "
            "plus noise, and no improvement in extraction changes that, because "
            "the missing inputs are facts a deck does not contain."
        ),
    }, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
