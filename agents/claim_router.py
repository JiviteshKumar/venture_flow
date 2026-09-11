"""Decide what kind of claim each one is, before spending a search on it.

WHY THIS EXISTS

Of the 128 distinct claims this product had checked and stored, 108 -- 84% --
came back NOT_ENOUGH_INFO. Most of that figure is not a verifier problem at
all: the large majority of stored claims come from synthetic test decks
(FinFlow, AgroPulse, VitalPulse...), companies that do not exist and so can
never be corroborated. Read one by one, the rest fall into four kinds:

  * INTERNAL metrics no public source can confirm: "ARR $11.4M", "We have 40
    enterprise customers", "processes invoices with 99.1% accuracy", "raising a
    $3M seed round". NOT_ENOUGH_INFO is the CORRECT answer, and counting it
    against the company penalised it for keeping its numbers private -- which
    every private company does. Across the stored claims, 0 of 9 such claims
    ever received a verdict.

  * GENERAL statements -- market facts and industry claims -- searched badly:
    "There are over 2 million mid-size farms in the US", "Carbon removal is the
    only pathway to net-zero". Every query was anchored on the company name,
    which buries a general statistic under results about one small company.

  * GARBLED fragments from extraction ("...tutoring costs ₹500- Parents rarely
    know...") -- a full judge call that cannot produce a verdict.

  * DUPLICATES -- AgroPulse's $1.1B market claim and its $349 pricing claim
    were each checked twice in one report.

The routing rule that matters most is the simplest one: a claim that names the
company, or speaks as "we/our", is searched with the company anchor; any other
claim is searched BOTH ways, anchored and unanchored, and the relevance gate
decides what survives. A harder market-versus-company split was tried and did
not hold -- deck taglines ("FDA-cleared AI diagnostics, detecting disease
earlier") name no company yet are about it -- and searching both ways costs no
tokens, only a few concurrent requests.

Deliberately regex and word lists, not a model: this runs on every claim, must
cost nothing, and has to give the same answer every time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

COMPANY = "company"      # about this company
MARKET = "market"        # a general market or industry statement
INTERNAL = "internal"    # a private operating metric of this company
GARBLED = "garbled"      # an extraction fragment, not a claim

# Verification order. Market statements first: they are the most checkable, and
# a refuted market statistic is one of the most useful things diligence finds.
PRIORITY = {MARKET: 0, COMPANY: 1, INTERNAL: 2, GARBLED: 3}

SEARCH_COMPANY = "company"   # anchored on the company name only
SEARCH_BOTH = "both"         # anchored and unanchored queries together

# Only money amounts: a currency symbol, or an M/B/K suffix. A bare trailing
# number is often part of the claim -- "Growing to a $3.5B industry by 2010"
# lost its year to an earlier version of this pattern, which changed the claim.
_TRAILING_FIGURES = re.compile(r"(?:\s+(?:[$₹€£]\d[\d.,]*\s*[MBK]?|\d[\d.,]*\s*[MBK]))+\s*$")
_LINEBREAK_HYPHEN = re.compile(r"[\w₹$]-\s+[A-Z]")
# OCR damage inside a word ("reproduc1on"), and text that stops mid-sentence
# on a function word ("This is a faithful reproduction of the").
_OCR_DIGIT_IN_WORD = re.compile(r"[a-z]\d[a-z]")
_ENDS_MID_SENTENCE = re.compile(r"\b(the|a|an|of|and|or|to|by|for|with|in|on|at)\s*$", re.I)
_NUMBER = re.compile(r"\d")
# Case matters for "us": case-insensitively it matched "US" in "mid-size farms
# in the US", which turned a plain market statistic into the company speaking
# about itself -- and gave it the company anchor this module exists to remove.
_FIRST_PERSON = re.compile(r"\b(?:[Ww]e|[Ww]e're|[Ww]e've|[Oo]ur|[Oo]urs|us)\b")

_INTERNAL_METRIC = re.compile(
    r"\b(ARR|MRR|run[- ]?rate|revenue|bookings|GMV|customers?|clients?|users?|"
    r"subscribers|pilots?|deployed|deployments?|shipped|processes|accuracy|"
    r"transactions?|transaction volume|volume|"
    r"uptime|churn|retention|NPS|CAC|LTV|payback|margin|burn|runway|"
    r"raising|round target|seeking|lifespan)\b",
    re.I,
)
_MARKET = re.compile(
    r"\b(market|industry|sector|segment|globally|worldwide|nationwide|annually|"
    r"per year|each year|every year|billion|trillion|average|on average|"
    r"percent|population|households|consumers|farms|retailers|hospitals|"
    r"patients|companies|businesses|firms|enterprises|MSMEs|brands|chains|"
    r"by 20\d\d|since the \d{4}s|regulation|rules|mandates?|pathway)\b"
    r"|\d+(?:\.\d+)?\s*%\s+of\b",
    re.I,
)
# "per month" alone is not pricing -- "55,000 users, growing 40% per month" is a
# growth rate. A price needs a currency amount in front of the period.
_COMPANY_PUBLIC = re.compile(
    r"[$₹€£]\s?\d[\d,.]*\s*[kKmM]?\s*(?:/|per)\s*(?:month|mo|user|seat|year|employee|store)\b"
    r"|\b(pric\w*|tier|plan|raised|funding|investors?|backed by|"
    r"led by|partnered|partnership|launched|founded|acquired|cleared|clearance|"
    r"FDA|patent\w*|award\w*|headquartered)\b",
    re.I,
)
_PRIVATE_ONLY = re.compile(r"\b(ARR|MRR|revenue|raising|target|churn|LTV|CAC)\b", re.I)

# Words in a company name that say nothing about which company it is.
_GENERIC_NAME_WORDS = {
    "tech", "health", "healthtech", "fintech", "edtech", "climatetech", "climate",
    "fashion", "labs", "systems", "technologies", "technology", "software", "inc",
    "ltd", "llc", "corp", "company", "group", "global", "pitch", "deck", "seed",
    "series", "seriesa", "seriesb", "sample", "d2c", "cyber", "energy",
}


@dataclass(frozen=True)
class RoutedClaim:
    claim: str      # cleaned text, as it will be verified
    kind: str       # COMPANY / MARKET / INTERNAL / GARBLED
    search: str     # SEARCH_COMPANY or SEARCH_BOTH
    reason: str     # one line, for the report


def clean(claim: str) -> str:
    """Whitespace, and the stray figures extraction leaves on the end of a line
    ("...legacy retail chains. $1,400M $45M"). A short claim like "ARR $11.4M"
    is left intact, because the figure IS the claim."""
    text = " ".join((claim or "").split())
    stripped = _TRAILING_FIGURES.sub("", text).strip()
    return stripped if len(stripped.split()) >= 4 else text


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def mentions_company(company: str, text: str) -> bool:
    """Whether the claim names the company.

    Any distinctive word of the name counts, not just the first: "2 VitalPulse
    HealthTech" must match "VitalPulse is deployed across 6 partner hospitals",
    and matching on the first word ("2") never could. Squashed comparison also
    catches "Thread & Co." against a stored name of "ThreadAndCo".
    """
    name = (company or "").strip()
    if not name:
        return False
    squashed_text = _squash(text)
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name) if w]
    for word in words:
        w = word.lower()
        if len(w) >= 4 and w not in _GENERIC_NAME_WORDS and w.isascii() and not w.isdigit():
            if w in squashed_text:
                return True
    whole = _squash(name).replace("and", "")
    return len(whole) >= 5 and whole in squashed_text.replace("and", "")


def classify(claim: str, company: str = "") -> RoutedClaim:
    text = clean(claim)
    words = text.split()

    # Shortness alone does not make a fragment. "ARR $5.1M", "SOC 2 certified",
    # "FDA cleared", "YC-backed" and "Series A funded" are all real, checkable
    # claims of under four words; an earlier rule dropped every one of them.
    # A short phrase is a fragment only when it carries no figure, no acronym
    # and fewer than two capitalised words -- "claim one", "Market". None of the
    # 132 claims ever stored was under four words, so this is a guard for the
    # rare case, but it guards the expensive direction: a real claim silently
    # left unchecked.
    short_but_real = len(words) < 4 and (
        bool(_NUMBER.search(text))
        or bool(re.search(r"\b[A-Z]{2,}", text))
        or sum(1 for w in words if w[:1].isupper()) >= 2
    )
    if not short_but_real and (
            len(words) < 4 or _LINEBREAK_HYPHEN.search(text)
            or _OCR_DIGIT_IN_WORD.search(text) or _ENDS_MID_SENTENCE.search(text)):
        return RoutedClaim(text, GARBLED, SEARCH_COMPANY,
                           "looks like an extraction fragment rather than a claim")

    about_company = mentions_company(company, text) or bool(_FIRST_PERSON.search(text))
    search = SEARCH_COMPANY if about_company else SEARCH_BOTH
    has_figure = bool(_NUMBER.search(text))

    if has_figure and _INTERNAL_METRIC.search(text) and (about_company or not _MARKET.search(text)):
        if _COMPANY_PUBLIC.search(text) and not _PRIVATE_ONLY.search(text):
            return RoutedClaim(text, COMPANY, search,
                               "a company fact that is usually public (pricing, funding, partners)")
        return RoutedClaim(text, INTERNAL, search,
                           "a private operating metric; public sources rarely confirm or contradict it")

    if not about_company and _MARKET.search(text):
        return RoutedClaim(text, MARKET, SEARCH_BOTH,
                           "a general market or industry statement")

    return RoutedClaim(text, COMPANY, search,
                       "a claim about this company" if about_company
                       else "names no company; searched with and without the company name")


def prioritise(claims: list[str], company: str = "", slots: int = 5) -> dict:
    """Pick which claims to verify, in order, and say why the rest were not.

    Returns {"selected": [RoutedClaim], "skipped": [{"claim", "kind", "reason"}]}.
    Near-duplicates are dropped first; then claims are ordered by PRIORITY,
    keeping the extractor's own order within a kind (its prompt already ranks by
    how verifiable a claim is). Garbled fragments are never verified.
    """
    routed, skipped, seen = [], [], set()
    for index, raw in enumerate(claims or []):
        rc = classify(raw, company)
        key = _squash(rc.claim)
        if not key:
            continue
        if key in seen:
            skipped.append({"claim": rc.claim, "kind": rc.kind,
                            "reason": "duplicate of a claim already selected"})
            continue
        seen.add(key)
        if rc.kind == GARBLED:
            skipped.append({"claim": rc.claim, "kind": rc.kind, "reason": rc.reason})
            continue
        routed.append((PRIORITY[rc.kind], index, rc))

    routed.sort(key=lambda item: (item[0], item[1]))
    selected = [rc for _, _, rc in routed[:slots]]
    for _, _, rc in routed[slots:]:
        skipped.append({"claim": rc.claim, "kind": rc.kind,
                        "reason": f"not among the {slots} most checkable claims"})
    return {"selected": selected, "skipped": skipped}
