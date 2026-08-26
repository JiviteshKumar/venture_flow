"""Read the financial state of a company out of pitch-deck prose.

Two measured failures motivate this module, and they turn out to be the same
failure.

**One.** `agents/risk_detector.RISK_SIGNALS` is a dictionary of SEC-filing
vocabulary -- "going concern", "material weakness", "customer concentration",
"executive departure". Measured on ml/eval/risk_benchmark.jsonl it scores F1
0.815 overall and misses **all three pitch-deck red flags**:
`deck_customer_concentration`, `deck_runway_crunch`,
`deck_founder_departure_ip`. It misses them because a founder does not write
"customer concentration"; a founder writes *"our anchor customer represents
$1.9M of that figure"*. The risk is stated as arithmetic, not as vocabulary.

**Two.** The pipeline's understanding of a company's financial position came
entirely from three optional numbers -- revenue, burn_rate, runway_months --
which an LLM extractor may or may not return. Nothing computed the relationship
between them, so a deck disclosing $410K monthly burn against $1.1M cash was
processed as two unrelated figures rather than as **2.7 months of runway**,
which is the single most consequential fact on the page.

The response to both is the same: parse the quantities, then compute the
relationships. This module is deliberately deterministic -- regex and
arithmetic, no LLM -- for three reasons. It runs before and independently of
any provider, so a quota outage cannot remove a company's financial position
from its own report. Its errors are inspectable: every extracted figure carries
the text span it came from, so a wrong number can be traced to the sentence that
produced it rather than to a model's judgement. And an LLM that hallucinates a
runway figure is far more dangerous than a regex that fails to find one, because
the first is confidently wrong and the second is visibly absent.

Nothing here is inferred. A metric that is not stated is `None`, and a derived
value is produced only when every input it needs was actually found.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── Money parsing ──────────────────────────────────────────────────────────
# Handles the forms decks actually use: $2.4M, $310K, 1.9 million, USD 4.1B,
# £250k, €1,200,000. Bare integers are NOT money -- "62 customers" and "2030"
# would both parse as dollars, and a market-size slide is full of years.
_SCALES = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mm": 1e6, "million": 1e6, "mn": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
    "t": 1e12, "trillion": 1e12,
}
_CURRENCY = r"[$€£]|USD|EUR|GBP"
_MONEY_RE = re.compile(
    rf"(?:(?P<cur>{_CURRENCY})\s*)"
    r"(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<scale>k|thousand|mm|m|mn|million|bn|b|billion|t|trillion)?\b",
    re.IGNORECASE,
)
# The same number written without a currency symbol, e.g. "2.4M in ARR".
# Requires an explicit scale word so that plain integers cannot match.
# The lookbehind must exclude a preceding digit or decimal point, not just word
# characters. Without the "." this pattern matched the "4M" INSIDE "$2.4M" --
# producing a phantom $4,000,000 three characters away from the real $2,400,000,
# which then won the nearest-to-anchor contest and was reported as the company's
# ARR. The excerpt said $2.4M; the tool said $4.0M, and every ratio derived from
# it inherited the error silently.
_SCALED_RE = re.compile(
    r"(?<![\w$€£.])(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<scale>k|mm|m|mn|bn|b|thousand|million|billion|trillion)\b",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"(?P<num>\d{1,3}(?:\.\d+)?)\s*%")


def parse_money(text: str) -> float | None:
    """First monetary amount in `text`, in units, or None.

    Prefers a currency-marked amount; falls back to an explicitly scaled one
    ("2.4M"). Returns None for a bare integer on purpose -- see the note above.
    """
    match = _MONEY_RE.search(text or "")
    if match is None:
        match = _SCALED_RE.search(text or "")
    if match is None:
        return None
    try:
        value = float(match.group("num").replace(",", ""))
    except (ValueError, AttributeError):
        return None
    scale = (match.groupdict().get("scale") or "").lower()
    return value * _SCALES.get(scale, 1.0)


def _all_money(text: str) -> list[float]:
    values = []
    for match in _MONEY_RE.finditer(text or ""):
        try:
            value = float(match.group("num").replace(",", ""))
        except ValueError:
            continue
        values.append(value * _SCALES.get((match.group("scale") or "").lower(), 1.0))
    return values


# ── Labelled metric extraction ─────────────────────────────────────────────
# Each metric is anchored on the words a deck uses for it, and the amount must
# appear within a short window of that anchor. The window is what stops a
# market-size slide's "$4.1B" from being read as the company's revenue.
_WINDOW = 120


@dataclass
class Metric:
    """One extracted quantity, with the text it came from."""

    value: float
    label: str
    span: str

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "label": self.label, "evidence": self.span}


ANCHORS: dict[str, tuple[str, ...]] = {
    "arr": ("arr", "annual recurring revenue", "annual run rate",
            "annual revenue run", "run rate revenue"),
    "mrr": ("mrr", "monthly recurring revenue", "monthly recognised revenue",
            "monthly recognized revenue", "monthly revenue", "per month in revenue"),
    "revenue": ("revenue", "sales", "topline", "top line", "bookings"),
    "burn_monthly": ("monthly burn", "burn rate", "burn is", "net burn",
                     "cash burn", "monthly spend"),
    "cash_on_hand": ("cash on hand", "cash in the bank", "cash balance",
                     "cash position", "we have cash", "bank balance"),
    "raise_amount": ("raising", "we are raising", "seeking", "round size",
                     "target raise", "raise a", "seed round", "series a",
                     "series b"),
    "valuation": ("valuation", "pre-money", "post-money", "cap of"),
}

# Metrics that are *rates* -- a monthly figure must not be read as an annual one
# and vice versa. Recorded so `derive_state` can normalise before dividing.
_MONTHLY = {"mrr", "burn_monthly"}


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")


def _sentence_around(text: str, index: int) -> tuple[int, int]:
    """Character bounds of the sentence containing `index`.

    Sentence scoping is the whole trick. Deck slides are runs of consecutive
    short sentences that each contain money, so any fixed character window
    around an anchor reaches into a neighbouring figure. Two real errors, both
    from the benchmark's runway excerpt, came from exactly that:

        "Monthly burn is currently $410K against $38K in monthly recognised
         revenue. Cash on hand at the end of last month was $1.1M."

    A backward window read `cash_on_hand` as **$38K** from the previous
    sentence, reporting 0.1 months of runway instead of 2.7 -- wrong by a factor
    of thirty in the most decisive figure on the page. Switching to a
    forward-only window fixed that and immediately broke the opposite ordering,
    "We closed $2.4M in ARR this year, up from $310K", where the amount belongs
    *before* its label and forward-scanning read ARR as $310K.

    Neither direction is right, because direction was never the question. The
    amount belongs to the clause the label is in.
    """
    left = 0
    right = len(text)
    for match in _SENTENCE_SPLIT.finditer(text):
        if match.end() <= index:
            left = match.end()
        else:
            right = match.start()
            break
    return left, right


def _money_positions(text: str) -> list[tuple[int, float]]:
    """(position, value) for every monetary amount in `text`."""
    found: list[tuple[int, float]] = []
    claimed: list[tuple[int, int]] = []
    for pattern in (_MONEY_RE, _SCALED_RE):
        for match in pattern.finditer(text or ""):
            # Span-overlap dedupe, not proximity. A currency-marked amount and a
            # bare scaled one can legitimately sit three characters apart
            # ("$2.4M, 310K"), so a distance threshold either misses real
            # neighbours or admits fragments of the match it already made.
            if any(match.start() < end and start < match.end()
                   for start, end in claimed):
                continue
            try:
                value = float(match.group("num").replace(",", ""))
            except (ValueError, AttributeError):
                continue
            value *= _SCALES.get((match.group("scale") or "").lower(), 1.0)
            claimed.append((match.start(), match.end()))
            found.append((match.start(), value))
    return sorted(found)


def _find_metric(text: str, keys: tuple[str, ...], *, exclude: tuple[str, ...] = ()) -> Metric | None:
    """The amount nearest to any of `keys`, within that key's own sentence.

    `exclude` drops a match whose sentence disqualifies it -- used to stop the
    annual `revenue` anchor from claiming "monthly recognised revenue", which
    otherwise assigns a monthly figure to an annual field and throws every
    ratio computed from it out by 12x.
    """
    lowered = text.lower()
    for key in keys:
        start = 0
        while True:
            index = lowered.find(key, start)
            if index == -1:
                break
            start = index + len(key)

            left, right = _sentence_around(text, index)
            sentence = text[left:right]
            if any(term in sentence.lower() for term in exclude):
                continue

            anchor_offset = index - left
            candidates = _money_positions(sentence)
            if not candidates:
                continue
            position, value = min(
                candidates, key=lambda pair: abs(pair[0] - anchor_offset)
            )
            return Metric(value=value, label=key, span=" ".join(sentence.split()))
    return None


def extract_metrics(text: str) -> dict[str, Metric]:
    """Every labelled financial quantity this module can find in `text`."""
    found: dict[str, Metric] = {}
    for name, keys in ANCHORS.items():
        # "revenue" is a substring of "monthly recognised revenue", so without
        # this the annual figure silently takes on a monthly value and every
        # ratio computed from it is out by 12x.
        exclude = ("monthly", "per month", "/mo", "mrr") if name == "revenue" else ()
        metric = _find_metric(text, keys, exclude=exclude)
        if metric is not None:
            found[name] = metric
    return found


# ── Derived company state ──────────────────────────────────────────────────


@dataclass
class CompanyState:
    """What the numbers, taken together, say about the company.

    Every field is None unless it was computed from figures actually found. A
    diligence tool that guesses runway is worse than one that reports it cannot
    determine runway, because the reader cannot tell the two apart.
    """

    runway_months: float | None = None
    runway_source: str | None = None
    monthly_burn: float | None = None
    cash_on_hand: float | None = None
    arr: float | None = None
    mrr: float | None = None
    revenue: float | None = None
    burn_multiple: float | None = None
    largest_customer_share: float | None = None
    growth_multiple: float | None = None
    annual_revenue: float | None = None
    evidence: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runway_months": self.runway_months,
            "runway_source": self.runway_source,
            "monthly_burn": self.monthly_burn,
            "cash_on_hand": self.cash_on_hand,
            "arr": self.arr,
            "mrr": self.mrr,
            "revenue": self.revenue,
            "annual_revenue": self.annual_revenue,
            "burn_multiple": self.burn_multiple,
            "largest_customer_share": self.largest_customer_share,
            "growth_multiple": self.growth_multiple,
            "evidence": self.evidence,
        }


_STATED_RUNWAY_RE = re.compile(
    r"(?P<num>\d{1,3}(?:\.\d+)?)\s*months?\s*(?:of\s*)?runway"
    r"|runway\s*(?:of|is|:)?\s*(?P<num2>\d{1,3}(?:\.\d+)?)\s*months?",
    re.IGNORECASE,
)

# "our anchor customer represents $1.9M of that figure" -- concentration stated
# as arithmetic rather than as the phrase "customer concentration".
_CONCENTRATION_PHRASES = (
    "anchor customer", "largest customer", "biggest customer", "top customer",
    "single customer", "one customer", "largest client", "anchor client",
    "top account", "largest account",
)


def _largest_customer_share(text: str, revenue_hint: float | None) -> tuple[float | None, str]:
    """Share of revenue attributable to the biggest customer, as a fraction.

    Two ways a deck states it, both handled: as a percentage ("78% of revenue
    comes from one customer") and as an amount against a stated total ("we
    closed $2.4M ARR ... our anchor customer represents $1.9M of that figure").
    The second form is the one the keyword detector could never see.
    """
    lowered = text.lower()
    for phrase in _CONCENTRATION_PHRASES:
        index = lowered.find(phrase)
        if index == -1:
            continue
        # Sentence-scoped for the same reason as _find_metric. A wider window
        # reached back into "We closed $2.4M in ARR" and read the TOTAL as the
        # share, reporting 100% concentration where the truth was 79% -- an
        # impossible number in place of a serious-but-real one.
        left, right = _sentence_around(text, index)
        window = text[left:right]

        percent = _PERCENT_RE.search(window)
        if percent:
            try:
                return float(percent.group("num")) / 100.0, " ".join(window.split())
            except ValueError:
                pass

        amount = parse_money(window)
        if amount is not None and revenue_hint:
            share = amount / revenue_hint
            # A share equal to the total is the signature of having matched the
            # total itself, so it is rejected rather than reported as 100%.
            if 0.0 < share < 0.999:
                return share, " ".join(window.split())
    return None, ""


_DEPARTURE_RE = re.compile(
    r"\b(?:founding|co-?founder|founder|chief\s+\w+\s+officer|cto|ceo|coo|cfo|vp)\b"
    r"[^.]{0,120}?\b(?:left|departed|stepped\s+down|resigned|exited|"
    r"is\s+no\s+longer|transitioned\s+out|moved\s+on)\b",
    re.IGNORECASE,
)
_IP_UNRESOLVED_RE = re.compile(
    r"\b(?:assignment\s+agreement|ip\s+assignment|invention\s+assignment|"
    r"intellectual\s+property)\b[^.]{0,160}?"
    r"\b(?:still\s+being|unresolved|not\s+been|has\s+not|pending|negotiat|"
    r"disputed|in\s+dispute|outstanding)\w*",
    re.IGNORECASE,
)


def derive_state(text: str, metrics: dict[str, Metric] | None = None) -> CompanyState:
    """Compute what the extracted figures imply about the company."""
    metrics = metrics if metrics is not None else extract_metrics(text)
    state = CompanyState()

    for name in ("arr", "mrr", "revenue", "cash_on_hand"):
        if name in metrics:
            setattr(state, name, metrics[name].value)
            state.evidence[name] = metrics[name].span
    if "burn_monthly" in metrics:
        state.monthly_burn = metrics["burn_monthly"].value
        state.evidence["monthly_burn"] = metrics["burn_monthly"].span

    # Runway: prefer what the deck states, fall back to computing it. Both are
    # recorded, and which one was used is reported, because a stated runway is
    # a claim to verify while a computed one is a derivation to check.
    stated = _STATED_RUNWAY_RE.search(text or "")
    if stated:
        raw = stated.group("num") or stated.group("num2")
        try:
            state.runway_months = float(raw)
            state.runway_source = "stated in deck"
            state.evidence["runway_months"] = " ".join(
                text[max(0, stated.start() - 80): stated.end() + 80].split()
            )
        except (TypeError, ValueError):
            pass
    if state.runway_months is None and state.monthly_burn and state.cash_on_hand:
        if state.monthly_burn > 0:
            state.runway_months = round(state.cash_on_hand / state.monthly_burn, 1)
            state.runway_source = "computed from cash on hand / monthly burn"
            state.evidence["runway_months"] = (
                f"cash {state.cash_on_hand:,.0f} / burn {state.monthly_burn:,.0f} per month"
            )

    # Burn multiple (Sacks): net burn divided by net new ARR. Only computable
    # when both an annualised revenue figure and a burn figure exist.
    # Annualise before comparing. MRR x 12 is the only correct way to put a
    # monthly figure next to an annual burn; using it raw understated revenue
    # 12-fold and produced a burn multiple of 129x where the truth was 10.8x.
    annual_revenue = state.arr or (state.mrr * 12 if state.mrr else None) or state.revenue
    state.annual_revenue = annual_revenue
    if state.monthly_burn and annual_revenue and annual_revenue > 0:
        state.burn_multiple = round((state.monthly_burn * 12) / annual_revenue, 2)

    share, span = _largest_customer_share(text, annual_revenue)
    if share is not None:
        state.largest_customer_share = round(share, 4)
        state.evidence["largest_customer_share"] = span

    # Growth: "up from" is how decks state it -- "$2.4M in ARR this year, up
    # from $310K".
    growth = re.search(r"up\s+from\s+([^.,;]{0,40})", text or "", re.IGNORECASE)
    if growth and annual_revenue:
        previous = parse_money(growth.group(1))
        if previous and previous > 0:
            state.growth_multiple = round(annual_revenue / previous, 2)
            state.evidence["growth_multiple"] = " ".join(growth.group(0).split())

    return state


# ── Deck-native risk signals ───────────────────────────────────────────────
# Thresholds are stated, not learned, and are conventional early-stage
# diligence lines rather than anything fitted: under 6 months of runway is the
# point at which a raise becomes forced rather than chosen, and 30% of revenue
# in one account is the usual concentration disclosure trigger. They are here
# so a reader can disagree with a number instead of with a black box.
RUNWAY_CRITICAL_MONTHS = 6.0
RUNWAY_WARNING_MONTHS = 12.0
CONCENTRATION_THRESHOLD = 0.30


def deck_risk_signals(text: str, state: CompanyState | None = None) -> list[dict[str, Any]]:
    """Plain-language deck risks, detected by arithmetic rather than vocabulary.

    Returns the same shape the keyword detector produces, so this composes with
    `detect_signals()` instead of replacing it. The keyword dictionary remains
    the better detector on filing prose, which is what it was built for; this
    covers the register it is blind to.
    """
    state = state if state is not None else derive_state(text)
    signals: list[dict[str, Any]] = []

    if state.runway_months is not None:
        if state.runway_months < RUNWAY_CRITICAL_MONTHS:
            signals.append({
                "category": "financial_risk",
                "signal": f"runway of {state.runway_months:g} months",
                "severity": "HIGH",
                "context": state.evidence.get("runway_months", ""),
                "detector": "deck_financials",
                "why": (f"below the {RUNWAY_CRITICAL_MONTHS:g}-month line at which a "
                        f"raise becomes forced rather than chosen"),
            })
        elif state.runway_months < RUNWAY_WARNING_MONTHS:
            signals.append({
                "category": "financial_risk",
                "signal": f"runway of {state.runway_months:g} months",
                "severity": "MEDIUM",
                "context": state.evidence.get("runway_months", ""),
                "detector": "deck_financials",
                "why": f"under {RUNWAY_WARNING_MONTHS:g} months leaves little margin",
            })

    if state.largest_customer_share is not None and state.largest_customer_share >= CONCENTRATION_THRESHOLD:
        signals.append({
            "category": "operational_risk",
            "signal": f"largest customer is {state.largest_customer_share:.0%} of revenue",
            "severity": "HIGH" if state.largest_customer_share >= 0.5 else "MEDIUM",
            "context": state.evidence.get("largest_customer_share", ""),
            "detector": "deck_financials",
            "why": (f"at or above the {CONCENTRATION_THRESHOLD:.0%} concentration line; "
                    f"losing this account would remove most of the revenue"),
        })

    departure = _DEPARTURE_RE.search(text or "")
    if departure:
        signals.append({
            "category": "management_risk",
            "signal": "founder or executive departure disclosed",
            "severity": "MEDIUM",
            "context": " ".join(
                (text[max(0, departure.start() - 60): departure.end() + 120]).split()
            ),
            "detector": "deck_financials",
            "why": "key-person loss stated in plain language, not filing vocabulary",
        })

    ip_issue = _IP_UNRESOLVED_RE.search(text or "")
    if ip_issue:
        signals.append({
            "category": "legal_risk",
            "signal": "unresolved intellectual-property assignment",
            "severity": "HIGH",
            "context": " ".join(
                (text[max(0, ip_issue.start() - 60): ip_issue.end() + 120]).split()
            ),
            "detector": "deck_financials",
            "why": "ownership of core technology is not established",
        })

    if state.burn_multiple is not None and state.burn_multiple > 3.0:
        signals.append({
            "category": "financial_risk",
            "signal": f"burn multiple of {state.burn_multiple:g}x",
            "severity": "MEDIUM",
            "context": state.evidence.get("monthly_burn", ""),
            "detector": "deck_financials",
            "why": "annualised burn is more than 3x revenue",
        })

    return signals


def analyse(text: str) -> dict[str, Any]:
    """Everything this module can say about `text`, in one call."""
    metrics = extract_metrics(text)
    state = derive_state(text, metrics)
    return {
        "metrics": {name: metric.to_dict() for name, metric in metrics.items()},
        "state": state.to_dict(),
        "signals": deck_risk_signals(text, state),
    }
