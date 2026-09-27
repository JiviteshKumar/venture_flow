"""Is this quote actually in the source, or did the model write it?

One check, used everywhere a language model is asked to point at text rather
than to compose it. It exists because the same failure keeps arriving in
different clothes:

  * a team specialist scoring "Commercial Execution 80" with an evidence line
    that reads plausibly and appears nowhere in the deck
  * a slide sweep asked for the assertion on slide 11 and returning a summary
    of what a competitive-landscape slide usually says

In both cases the output is indistinguishable from a real finding by eye, and
in both cases a string comparison settles it in microseconds. `founder_research`
already guards names this way -- a proposed founder must appear verbatim in the
retrieved pages -- and this is the same rule, factored out so the next caller
inherits it instead of reimplementing it.

WHY NOT AN EXACT SUBSTRING MATCH

Models re-punctuate, fix casing, expand an ampersand and drop the line break a
PDF put in the middle of a sentence. Requiring byte equality would reject real
quotes over a comma, and a guard that fires on honest output gets loosened or
removed. So both sides are reduced to bare lower-case words and the comparison
is made on those.

WHY SIX WORDS

A shingle of six consecutive words is far past what fluent invention produces
by chance, and short enough that a quote spanning a line break in the original
still has one clean run inside it. Below `MIN_QUOTE_WORDS` nothing is checkable
-- "strong team" appears in almost every deck -- so a quote that short fails
rather than passing on a coincidence.
"""
from __future__ import annotations

import re

_WORDS = re.compile(r"[a-z0-9]+")

#: A quote shorter than this cannot be checked meaningfully.
MIN_QUOTE_WORDS = 4

#: Consecutive words that must match for a longer quote to count as grounded.
SHINGLE = 6


def normalised_words(text: str) -> list[str]:
    """Bare lower-case words, with punctuation and layout thrown away."""
    return _WORDS.findall((text or "").lower())


def is_grounded(quote: str, haystack_words: list[str]) -> bool:
    """Whether `quote` really came from the text `haystack_words` was built from.

    `haystack_words` is pre-normalised by the caller because it is usually
    reused across many quotes and normalising it per quote is the whole cost.
    """
    words = normalised_words(quote)
    if len(words) < MIN_QUOTE_WORDS:
        return False

    if len(words) <= SHINGLE:
        span = len(words)
        return any(
            haystack_words[i:i + span] == words
            for i in range(max(0, len(haystack_words) - span + 1))
        )

    for start in range(len(words) - SHINGLE + 1):
        run = words[start:start + SHINGLE]
        if any(
            haystack_words[i:i + SHINGLE] == run
            for i in range(max(0, len(haystack_words) - SHINGLE + 1))
        ):
            return True
    return False


def grounded_in(quote: str, *sources: str) -> bool:
    """Convenience for a one-off check against raw text."""
    return is_grounded(quote, normalised_words(" ".join(s or "" for s in sources)))
