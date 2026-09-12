"""What the headline number means, stated next to it -- one source for UI and PDF.

WHY THIS EXISTS

The VentureFlow Score is a weak predictor of a narrow outcome, and nothing in
this product can make it a strong predictor of a different one (see
PROJECT_OVERVIEW sections 4.1 and 8, and ml/scripts/build_yc_comparables_corpus.py:
an outsized outcome is not separable from a quiet survivor, AUC 0.5892 with an
interval touching chance). What CAN be fixed is the number being read as
something it is not. Three things were being misread:

  * THE BAND. "Above / Near / Below comparable base rate" came from fixed
    thresholds (65 and 45), not from the model's own interval. A 64 whose
    interval is 58-70 read "Near" although it sits clearly above a 49% base
    rate; a 46 whose whole interval lies below 49 also read "Near". The band is
    now read off the interval against the actual base rate.

  * THE BASE RATE. 49% is the share that exited among Y Combinator companies
    whose fate is already settled -- exited or shut down. It excludes the 70%
    still operating. Read as "how often a company like this exits", it
    overstates the real figure (15%) by more than three times. The headline
    showed it without saying so.

  * THE OUTCOME. The label is exit-or-shutdown: acquired or public counts as a
    success, shut down as a failure, and companies still operating are dropped
    from training because their outcome is not yet known. So a modest acquisition
    and a fund-returning IPO score the same. The comparables
    corpus already grades outcomes in four tiers (shut down / still operating /
    exit / outsized), but none of that reached the headline. Now the outcome mix
    of the nearest real comparables is stated beside the number: for Uber's 2008
    deck, 1 exit, 1 still operating and 3 shut down among the five nearest.

Built once, server-side, and rendered by both the UI and the PDF, so the two
cannot describe the same score differently.
"""

from __future__ import annotations

from typing import Any

ABOVE, WITHIN, BELOW = "above", "within", "below"

BAND_LABELS = {
    ABOVE: "Above the base rate",
    WITHIN: "Within range of the base rate",
    BELOW: "Below the base rate",
}

MEASURES = (
    "The estimated chance that a company with these characteristics was acquired "
    "or went public rather than shutting down, learned from Y Combinator companies "
    "whose outcome is already settled; companies still operating are left out, "
    "because their outcome is not yet known. It is not a forecast of returns: a "
    "small acquisition and a fund-returning IPO count the same."
)

# Highest tier first, so the sentence leads with the best outcome present.
_OUTCOME_ORDER = ["Outsized outcome", "Exit", "Acquired", "Still operating", "Shut down"]


def _as_points(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number * 100 if number <= 1 else number


def band_for(score: float, low: float | None, high: float | None,
             base: float | None) -> tuple[str, str]:
    """(band, one-line reason). Reads the interval when there is one."""
    if base is not None and low is not None and high is not None:
        if low > base:
            return ABOVE, (f"its likely range, {low:.0f}-{high:.0f}, sits entirely "
                           f"above the {base:.0f}% base rate")
        if high < base:
            return BELOW, (f"its likely range, {low:.0f}-{high:.0f}, sits entirely "
                           f"below the {base:.0f}% base rate")
        return WITHIN, (f"its likely range, {low:.0f}-{high:.0f}, includes the "
                        f"{base:.0f}% base rate, so it cannot be told apart from it")
    # No interval: the old fixed thresholds, stated as such.
    if score >= 65:
        return ABOVE, "no interval was available; judged on the score alone"
    if score >= 45:
        return WITHIN, "no interval was available; judged on the score alone"
    return BELOW, "no interval was available; judged on the score alone"


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


_PHRASES = {
    "Outsized outcome": ("had an outsized outcome", "had outsized outcomes"),
    "Exit": ("exited", "exited"),
    "Acquired": ("was acquired", "were acquired"),
    "Still operating": ("is still operating", "are still operating"),
    "Shut down": ("shut down", "shut down"),
}


def comparable_mix(comparables: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in comparables or []:
        label = (row or {}).get("outcome") or "Unknown"
        counts[label] = counts.get(label, 0) + 1
    n = sum(counts.values())
    if not n:
        return {"n": 0, "counts": {}, "sentence": ""}
    ordered = sorted(counts, key=lambda k: _OUTCOME_ORDER.index(k) if k in _OUTCOME_ORDER else 99)
    parts = []
    for label in ordered:
        one, many = _PHRASES.get(label, (f"had outcome '{label}'", f"had outcome '{label}'"))
        parts.append(f"{counts[label]} {one if counts[label] == 1 else many}")
    joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return {
        "n": n,
        "counts": {label: counts[label] for label in ordered},
        "sentence": (f"Of the {_plural(n, 'most similar company', 'most similar companies')} "
                     f"with a recorded outcome, {joined}."),
    }


def base_rate_note(base: float | None, outcome_rates: dict[str, Any] | None) -> str:
    if base is None:
        return ""
    rates = (outcome_rates or {}).get("rates") or {}
    n = (outcome_rates or {}).get("n")
    exit_rate = (outcome_rates or {}).get("exit_rate")
    outsized = (outcome_rates or {}).get("outsized_rate")
    operating = rates.get("operating")
    if None in (n, exit_rate, outsized, operating):
        return (f"The {base:.0f}% base rate is the share that exited among companies "
                f"whose fate is already settled; it excludes those still operating.")
    return (f"The {base:.0f}% base rate is the share that exited among Y Combinator "
            f"companies whose fate is already settled -- exited or shut down. It "
            f"leaves out the {operating:.0%} still operating, so it is not how often "
            f"a company like this exits: across all {n:,} Y Combinator companies, "
            f"{exit_rate:.0%} exited and {outsized:.1%} had an outsized outcome.")


def build_score_context(venture_score: dict[str, Any] | None,
                        market_comparables: dict[str, Any] | None) -> dict[str, Any]:
    vs = venture_score or {}
    if not vs.get("available") or vs.get("venture_score") is None:
        return {"available": False}
    score = float(vs["venture_score"])
    interval = vs.get("score_range") or [None, None]
    low = _as_points(interval[0]) if len(interval) > 0 else None
    high = _as_points(interval[1]) if len(interval) > 1 else None
    base = _as_points(vs.get("base_rate"))

    band, reason = band_for(score, low, high, base)
    mc = market_comparables or {}
    mix = comparable_mix(mc.get("comparables") or []) if mc.get("available") else comparable_mix([])
    return {
        "available": True,
        "score": score,
        "band": band,
        "band_label": BAND_LABELS[band],
        "band_reason": f"{BAND_LABELS[band]}: {reason}.",
        "measures": MEASURES,
        "base_rate": base,
        "base_rate_note": base_rate_note(base, mc.get("outcome_rates")),
        "comparable_mix": mix,
    }
