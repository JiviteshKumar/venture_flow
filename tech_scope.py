"""Is this a tech startup? VentureFlow only analyses tech startups.

WHY A GATE AT ALL

Every number this product produces is calibrated on technology companies. The
VentureFlow Score is trained on Y Combinator's software portfolio; its features
are literally YC's own taxonomy. The base rates it compares against are tech
base rates. The Outcome Model, the risk-disclosure model and the comparable
company search are all built on the same population.

Point a tool like that at a restaurant group or a mining company and it will
still return a number, formatted exactly like the number it returns for a SaaS
company, with the same confidence interval printed underneath. Nothing in the
output would say the model has never seen a business of that kind. That is a
worse failure than refusing, because it is invisible: the user gets a
plausible-looking score whose meaning is undefined.

So this refuses, and says why.

WHICH WAY TO FAIL

The two errors here are not symmetric.

Wrongly BLOCKING a real tech startup breaks the product for the user in front of
it. They have a legitimate deck, the tool refuses it, and there is nothing they
can do -- rewriting the deck to please a classifier is not a reasonable ask.

Wrongly ALLOWING a non-tech startup produces an analysis whose score is
uncalibrated. That is bad, but the report is still built from the deck's own
content, and the coverage and provenance blocks still describe it honestly.

So the gate is deliberately reluctant. It blocks only on positive evidence that
a company is something else, and abstains -- allowing the analysis -- whenever
the evidence is thin, contradictory, or absent. "I could not tell" resolves to
allow, never to block. `confidence` and `reason` are returned either way so the
caller can show what the decision rested on.

HOW IT DECIDES

Two independent passes, deliberately in this order:

1. **Signals.** Counts software-core evidence and non-tech evidence in the
   deck's own words, and records which phrases it matched. Cheap, deterministic,
   and it is the whole decision when no LLM is reachable.

2. **Adjudication.** The LLM is asked to classify only when the signals are
   contested -- non-tech evidence present alongside software evidence, or
   neither present. A clear software deck never spends a token, and an LLM
   outage never blocks anybody, because a failed adjudication falls back to
   allow.

The vocabulary below is shared with `ml/scripts/prepare_venturescore_dataset.py`,
which applies the same test when selecting training rows. That is on purpose:
the population the model is trained on and the population it accepts should be
described by one definition rather than two that drift apart.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

ENABLED = os.getenv("VENTUREFLOW_TECH_SCOPE_GATE", "on").strip().lower() not in {
    "off", "0", "false", "no",
}

# Evidence that the company's core product is software or hardware technology.
#
# Matched on word boundaries, never as substrings. That is not a detail: the
# first version of this matched substrings, and "api" duly matched inside
# "working capital", which handed a construction company one software signal
# and let it through the gate. It is the same name-match-mistaken-for-an-
# identity-match failure that this codebase has now hit in the deck scraper, in
# founder grounding, and here.
SOFTWARE_CORE = (
    "software", "saas", "platform", "mobile app", "web app", "application",
    "api", "sdk", "developer", "algorithm", "machine learning",
    "artificial intelligence", "ai", "deep learning", "neural network",
    "cloud", "data platform", "analytics", "dashboard", "automation",
    "automate", "marketplace", "e-commerce", "ecommerce", "online platform",
    "web-based", "browser", "ios", "android", "open source", "database",
    "infrastructure", "devops", "cybersecurity", "encryption", "blockchain",
    "fintech", "healthtech", "edtech", "proptech", "insurtech", "digital",
    "users", "monthly active", "daily active", "arr", "mrr", "churn",
    "subscription", "engineering team", "product-led", "integration",
    "semiconductor", "chip", "robotics", "hardware", "firmware", "sensor",
    "device", "internet of things", "iot", "network", "telemetry",
)

# Evidence that the company is something else. These are the *core business*,
# not a customer segment: a SaaS product sold to restaurants is a tech startup,
# and that is what `_is_serving_not_being` guards against below.
NON_TECH_CORE = (
    "restaurant", "cafe", "coffee shop", "bakery", "brewery", "winery",
    "distillery", "farm", "farming", "agriculture", "livestock", "orchard",
    "vineyard", "mine", "mining", "quarry", "drilling", "oil field",
    "hotel", "resort", "hostel", "spa", "salon", "barbershop", "gym",
    "fitness studio", "clinic", "dental practice", "law firm",
    "accounting firm", "consultancy", "consulting firm", "staffing agency",
    "construction company", "contractor", "plumbing", "roofing", "landscaping",
    "clothing brand", "apparel brand", "fashion label", "jewellery", "jewelry",
    "furniture", "cosmetics brand", "skincare brand", "beverage brand",
    "snack brand", "food truck", "catering", "grocery store", "retail store",
    "car dealership", "trucking", "haulage", "logistics fleet", "warehouse space",
    "real estate developer", "property development", "hedge fund",
    "private equity fund", "insurance broker", "travel agency", "tour operator",
    "publishing house", "record label", "film studio", "talent agency",
)

# A tech company frequently names the industry it SELLS to. "Software for
# restaurants" contains "restaurant" and is a tech startup. These markers
# recognise the selling relationship so the industry word is not counted as
# evidence about what the company is.
#
# Matched by GRAMMATICAL ADJACENCY, not by a proximity window, and the
# distinction is the whole of it. The first version scanned the 60 characters
# before the industry word for any of these markers, with bare "for" and "to"
# among them -- and "for" or "to" occurs within 60 characters of almost
# everything in English. "We are raising to open two further restaurant
# locations" was read as a company selling to restaurants; so was
# "farm-to-table restaurants". The effect was that NO non-tech evidence ever
# survived, and the gate silently could not refuse anything.
#
# (The same correction was made to founder-name grounding for the same reason:
# a window wide enough to be useful is wide enough to swallow the next clause.)
_SERVING_MARKERS = (
    r"for", r"serving", r"serves", r"sold\s+to", r"used\s+by", r"built\s+for",
    r"designed\s+for", r"helps?", r"helping", r"enables?", r"enabling",
    r"powers?", r"powering", r"customers?\s+(?:are|include)", r"clients?\s+(?:are|include)",
)

# At most two words may separate the marker from the industry word. "software
# for restaurants" (0), "a platform for independent restaurants" (1), "built for
# small local restaurants" (2) are all selling relationships; by three the
# connection is gone, which is what admitted "to open two further restaurant
# locations".
_MAX_WORDS_BETWEEN_MARKER_AND_INDUSTRY = 2

# The other shape a customer reference takes: the industry word followed by a
# noun naming the people who buy. "restaurant owners", "900 restaurant
# customers", "dental practice managers" are all references to a market, and a
# vendor's deck is full of them -- far more often than it says "for
# restaurants" once and never again.
#
# Without this, the very copy a genuine vertical-SaaS company writes counts as
# evidence that it IS a restaurant.
_CUSTOMER_NOUNS = (
    r"owners?", r"operators?", r"customers?", r"clients?", r"managers?",
    r"partners?", r"businesses", r"chains?", r"brands?", r"groups?",
    r"staff", r"teams?", r"industry", r"sector", r"market",
)

MIN_CHARS_TO_JUDGE = 200


def _plural_alternation(phrase: str) -> str:
    """A regex fragment matching `phrase` in the singular or the plural.

    Word-boundary matching fixed the substring bug ("api" inside "capital") but
    is too strict in the other direction: `\brestaurant\b` does not match
    "restaurants", and a deck about restaurants almost always says
    "restaurants". Only the final word inflects -- "dental practice" becomes
    "dental practices", never "dentals practice".
    """
    head, _, last = phrase.rpartition(" ")
    prefix = re.escape(head) + r"\s+" if head else ""
    if last.endswith("y"):
        return prefix + re.escape(last[:-1]) + r"(?:y|ies)"
    if last.endswith(("s", "x", "ch", "sh")):
        return prefix + re.escape(last) + r"(?:es)?"
    return prefix + re.escape(last) + r"s?"


def _compile(vocabulary: tuple[str, ...]) -> dict[str, re.Pattern]:
    """One word-boundary pattern per phrase, matching singular or plural.

    The boundaries are what stop "ai" matching inside "email" and "api" inside
    "capital"; the inflection is what stops "restaurant" missing "restaurants".
    Both are needed, and each one alone is a bug.
    """
    return {
        phrase: re.compile(r"\b" + _plural_alternation(phrase) + r"\b", re.IGNORECASE)
        for phrase in vocabulary
    }


_SOFTWARE_PATTERNS: dict[str, re.Pattern] = {}
_NON_TECH_PATTERNS: dict[str, re.Pattern] = {}


def _matches(text: str, vocabulary: tuple[str, ...]) -> list[str]:
    """Every phrase from `vocabulary` present in `text`, as whole words.

    The two production vocabularies are compiled once and cached; anything else
    is compiled on the spot, which keeps this usable from a test.
    """
    global _SOFTWARE_PATTERNS, _NON_TECH_PATTERNS
    if vocabulary is SOFTWARE_CORE:
        if not _SOFTWARE_PATTERNS:
            _SOFTWARE_PATTERNS = _compile(SOFTWARE_CORE)
        patterns = _SOFTWARE_PATTERNS
    elif vocabulary is NON_TECH_CORE:
        if not _NON_TECH_PATTERNS:
            _NON_TECH_PATTERNS = _compile(NON_TECH_CORE)
        patterns = _NON_TECH_PATTERNS
    else:
        patterns = _compile(vocabulary)
    return [phrase for phrase, pattern in patterns.items() if pattern.search(text)]


def _is_serving_not_being(text: str, phrase: str) -> bool:
    """True when EVERY mention of `phrase` refers to a market rather than to the
    company itself.

    A mention counts as a market reference in either of two shapes:

        "booking software FOR restaurants"     a serving marker just before it
        "900 RESTAURANT OWNERS use it"         a customer noun just after it

    "Every" rather than "any", deliberately. One mention in neither shape means
    the deck is saying what the company IS, and a restaurant group that happens
    to mention "software for restaurants" once is still a restaurant group.
    """
    inflected = _plural_alternation(phrase.lower())
    before = re.compile(
        r"\b(?:" + "|".join(_SERVING_MARKERS) + r")\s+"
        r"(?:[\w-]+[\s-]+){0," + str(_MAX_WORDS_BETWEEN_MARKER_AND_INDUSTRY) + r"}"
        + inflected + r"\b",
        re.IGNORECASE,
    )
    after = re.compile(
        r"\b" + inflected + r"\s+(?:" + "|".join(_CUSTOMER_NOUNS) + r")\b",
        re.IGNORECASE,
    )

    mentions = list(re.finditer(r"\b" + inflected + r"\b", text, re.IGNORECASE))
    if not mentions:
        return False

    market_ends = {m.end() for m in before.finditer(text)}
    market_starts = {m.start() for m in after.finditer(text)}
    return all(
        m.end() in market_ends or m.start() in market_starts
        for m in mentions
    )


_PROMPT = """You are classifying a company for a due-diligence tool that only
covers TECHNOLOGY startups.

A company IS in scope when its core product is software, or hardware whose value
is in its technology: SaaS, marketplaces, apps, developer tools, AI/ML products,
fintech, healthtech, edtech, cybersecurity, semiconductors, robotics, devices.

A company IS in scope when it sells technology INTO a traditional industry.
Booking software for restaurants is a tech company. Practice-management software
for dentists is a tech company. The industry it serves does not decide this.

A company is NOT in scope when its core business is operating in a traditional
industry itself: running restaurants, farming, mining, a clothing label, a
construction firm, a law practice, a hotel chain, a fund.

Company name: {name}

Deck text:
---
{text}
---

Reply with JSON and nothing else:
{{"is_tech": true or false,
  "sector": "<short sector label>",
  "confidence": <0.0 to 1.0>,
  "reason": "<one sentence, quoting the deck where you can>"}}

If the text is too short or too vague to tell, answer is_tech true with a
confidence at or below 0.5 and say so in the reason. Do not guess a company into
being out of scope."""


def _adjudicate(text: str, company_name: str) -> dict[str, Any] | None:
    """Ask the LLM. Returns None on any failure, which the caller treats as
    "no opinion" and therefore as allow."""
    try:
        import json

        from groq_client import MODEL, get_client, note_provider_failure, pace_for

        prompt = _PROMPT.format(name=company_name or "(not given)", text=text[:6000])
        pace_for(len(prompt), 800)
        response = get_client().chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            # 800, not 300. At 300 the provider returned
            # json_validate_failed -- "max completion tokens reached before
            # generating a valid document" -- because this model emits
            # reasoning tokens before the JSON. A truncated response is
            # indistinguishable here from an unreachable model, so the gate
            # silently fell back to keyword-only on decks it should have
            # adjudicated.
            max_tokens=800,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        if "is_tech" not in parsed:
            return None
        return {
            "is_tech": bool(parsed["is_tech"]),
            "sector": str(parsed.get("sector", ""))[:80],
            "confidence": max(0.0, min(1.0, float(parsed.get("confidence", 0.5)))),
            "reason": str(parsed.get("reason", ""))[:400],
        }
    except Exception as exc:
        note_provider_failure(exc)
        logger.warning("Tech-scope adjudication failed; defaulting to in-scope",
                       exc_info=True)
        return None


def classify(text: str, company_name: str = "") -> dict[str, Any]:
    """Decide whether `text` describes a tech startup. Never raises.

    Returns a dict with `in_scope`, `confidence`, `sector`, `reason`, `method`,
    and the matched `software_signals` / `non_tech_signals`. `in_scope` is False
    only when there is positive evidence the company is something else.
    """
    text = (text or "").strip()

    if not ENABLED:
        return _verdict(True, 0.0, "", "The tech-scope gate is disabled by "
                                      "configuration.", "disabled", [], [])

    if len(text) < MIN_CHARS_TO_JUDGE:
        # Too little to judge. Allowing is the correct call: a short deck is
        # already flagged as thin by extraction coverage, and refusing it here
        # would blame the user for our own inability to read it.
        return _verdict(
            True, 0.0, "",
            f"Only {len(text)} characters were available, too little to judge "
            f"the company's sector. Allowed through rather than refused.",
            "insufficient_text", [], [],
        )

    software = _matches(text, SOFTWARE_CORE)
    non_tech_raw = _matches(text, NON_TECH_CORE)
    # Drop the industries that only ever appear as a market being sold to.
    non_tech = [p for p in non_tech_raw if not _is_serving_not_being(text, p)]

    # Unambiguously technology: plenty of software evidence, nothing pointing
    # elsewhere. Decided here so the common case costs nothing.
    if software and not non_tech:
        return _verdict(
            True, 0.9, "technology",
            f"The deck describes a technology product: matched "
            f"{', '.join(repr(s) for s in software[:5])}.",
            "signals", software, non_tech,
        )

    verdict = _adjudicate(text, company_name)
    if verdict is None:
        # No LLM. Fall back to the signal counts, and only block when the
        # non-tech evidence stands alone.
        if non_tech and not software:
            return _verdict(
                False, 0.6, non_tech[0],
                f"The deck describes a business in a traditional industry "
                f"({', '.join(repr(s) for s in non_tech[:4])}) with no sign of a "
                f"software or hardware product. Note that this was decided "
                f"without the language model, which was unreachable.",
                "signals_only_llm_unavailable", software, non_tech,
            )
        return _verdict(
            True, 0.3, "",
            "The sector could not be determined: the language model was "
            "unreachable and the deck's wording is mixed. Allowed through "
            "rather than refused.",
            "signals_only_llm_unavailable", software, non_tech,
        )

    if verdict["is_tech"]:
        return _verdict(True, verdict["confidence"], verdict["sector"],
                        verdict["reason"], "llm", software, non_tech)

    # The model says out of scope. Require it to be confident AND require the
    # deck's own wording to agree, so a single mis-read cannot block a real tech
    # company.
    #
    # "Agree" is not "no software signal at all". That was the first rule, and it
    # let a construction company through on one incidental keyword against six
    # non-tech ones. It is enough that the non-tech evidence outweighs the
    # software evidence -- a genuine tech deck is dense with software vocabulary,
    # not level-pegging with it.
    evidence_agrees = not software or len(non_tech) > len(software)
    if verdict["confidence"] >= 0.7 and evidence_agrees:
        return _verdict(False, verdict["confidence"], verdict["sector"],
                        verdict["reason"], "llm", software, non_tech)

    return _verdict(
        True, verdict["confidence"], verdict["sector"],
        f"Classified as outside the tech scope ({verdict['reason']}) but allowed "
        f"through: "
        + (f"the deck's own wording contains as much software evidence ("
           + ", ".join(repr(s) for s in software[:4]) + ") as non-technology evidence."
           if software and len(non_tech) <= len(software) else
           f"the classification was not confident enough "
           f"({verdict['confidence']:.2f} < 0.70)."),
        "llm_low_confidence", software, non_tech,
    )


def _verdict(in_scope, confidence, sector, reason, method, software, non_tech):
    return {
        "in_scope": bool(in_scope),
        "confidence": round(float(confidence), 2),
        "sector": sector or "",
        "reason": reason,
        "method": method,
        "software_signals": software[:12],
        "non_tech_signals": non_tech[:12],
        "scope_statement": (
            "VentureFlow analyses technology startups only. Its scoring model is "
            "trained on technology companies, so a score for a business outside "
            "that scope would have no calibrated meaning."
        ),
    }
