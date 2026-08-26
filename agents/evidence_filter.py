"""A cheap, non-LLM gate that drops off-topic retrieved pages before the LLM
judges them.

Why this exists, measured rather than assumed. `build_queries()` used to
receive only the claim text -- `verify_claim()` had no company parameter at
all, so the company name never entered the search query. Combined with the
template "is it true that {claim}", retrieval returned dictionary and
fact-check noise: across 97 real claims the most frequent domains included
merriam-webster.com (6), dictionary.cambridge.org (3), youtube.com (3) and
snopes.com (3). The worked example that made it concrete: ClaimFlow's claim
"Seed round target is $8M" retrieved merriam-webster, youtube, cambridge
dictionary, truemfg.com and trueccu.com -- the last two being companies with
"true" in the name, matched from the word "true" in the query template.

Fixing the queries is the first half. This module is the second: even a good
query returns some unrelated pages, and every unrelated page handed to the
judge is an opportunity for it to reason about the wrong company. A VC tool
that cites a same-named business as evidence about the startup in front of it
is worse than one that says it found nothing.

Deliberately NOT an LLM call. Three reasons: it runs on every retrieved page
(5-15 per claim, 5 claims per deck, so 25-75 extra calls per report against a
200,000 token/day free tier); an LLM relevance judge would be the same class of
component it is supposed to protect; and the signal needed here -- "is this page
even about this company/topic" -- is a similarity question that TF-IDF answers
adequately. `embeddings.py` already ships a trained TF-IDF+SVD embedder.

Degradation contract, which matters more here than usual: when the embedder is
unavailable this module falls back to lexical overlap, and when that cannot be
computed it KEEPS the source. A relevance filter that silently drops everything
would turn a missing model file into "no evidence exists", which is exactly the
class of bug -- infrastructure failure reported as a finding -- that this
codebase has already been burned by once.
"""

from __future__ import annotations

import logging
import math
import re
from urllib.parse import urlparse

import embeddings

logger = logging.getLogger(__name__)

# Domains that are never evidence about a startup's claims. Kept short and
# specific: this is a list of site *categories* observed polluting real runs,
# not a general-purpose blocklist. Anything genuinely arguable stays out of it
# and is left to the similarity gate, which is measurable.
NOISE_DOMAINS = frozenset({
    # Dictionaries / thesauri / word lookups -- the single largest observed
    # noise category, caused by the removed query templates.
    "merriam-webster.com", "dictionary.cambridge.org", "dictionary.com",
    "thesaurus.com", "collinsdictionary.com", "oxfordlearnersdictionaries.com",
    "vocabulary.com", "wordreference.com", "wiktionary.org",
    "urbandictionary.com", "yourdictionary.com", "thefreedictionary.com",
    "macmillandictionary.com", "ldoceonline.com",
    # Generic fact-check desks. Excellent sources about viral public claims,
    # and never about a seed-stage startup's ARR.
    "snopes.com", "politifact.com", "factcheck.org", "fullfact.org",
    # Video/social platforms: fetch_page_text() cannot retrieve a transcript,
    # so these contribute a title and nothing checkable.
    "youtube.com", "youtu.be", "tiktok.com", "facebook.com", "instagram.com",
    "pinterest.com", "quora.com",
})

# Sites that republish pitch decks. Blocked because citing them is CIRCULAR: the
# question is whether a deck's claim is true, and these return the deck.
#
# Found by reading the verdicts from seven real decks. Buffer's "$150,000 annual
# revenue run rate" was marked SUPPORTS at 0.96 confidence on the strength of
# pitchdeckinspo.com, failory.com and slideshare.net -- all three of which are
# hosting Buffer's own 2011 pitch deck. Intercom's claim was "confirmed" by two
# Scribd copies of the Intercom deck. The tool had verified a document against
# itself and reported the result as independent corroboration, which is worse
# than returning NOT_ENOUGH_INFO because it manufactures confidence a reader
# will act on.
DECK_MIRROR_DOMAINS = frozenset({
    "slideshare.net", "scribd.com", "pitchdeckinspo.com", "failory.com",
    "genppt.com", "media.genppt.com", "pitchdeckcoach.com", "mypitchdecks.com",
    "billiondollarpitchdecks.com", "slidebean.com", "deckary.com",
    "startupfundraising.com", "pitchdeckhunt.com", "bestpitchdeck.com",
    "piktochart.com", "visme.co", "alexanderjarvis.com", "docsend.com",
    "sequoiacap.com/wp-content", "pitch.com", "canva.com", "prezi.com",
})

_WORD = re.compile(r"[a-z0-9]+")

# Words carrying no topical signal, so their overlap is not evidence of
# relevance. Kept minimal -- an aggressive stoplist would quietly become a
# second, unmeasured relevance model.
_STOP = frozenset("""
a an the and or but if of for to in on at by with from as is are was were be
been being it its this that these those we our us you your they their he she
has have had do does did will would can could should may might must not no
than then so such about into over under more most other some any each which
who whom what when where why how all both few own same too very just
""".split())

# Corporate suffixes and category words stripped before name matching, so that
# "Inc" or "AI" cannot carry a match on their own. Without this, every AI
# startup matches every page containing the word "AI".
_NAME_NOISE = frozenset({
    "inc", "llc", "ltd", "limited", "corp", "corporation", "co", "company",
    "gmbh", "plc", "sa", "ag", "bv", "pty", "labs", "lab", "technologies",
    "technology", "tech", "ai", "io", "app", "group", "holdings", "systems",
    "solutions", "software", "platform", "deck", "pitch",
})


def domain_of(url: str) -> str:
    """Host for `url`, lowercased, without a leading www."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _host_in(url: str, domains: frozenset[str]) -> bool:
    host = domain_of(url)
    if not host:
        return False
    # Suffix match so subdomains (en.wiktionary.org) are caught too.
    return any(host == d or host.endswith("." + d) for d in domains)


def is_noise_domain(url: str) -> bool:
    return _host_in(url, NOISE_DOMAINS)


def is_deck_mirror(url: str) -> bool:
    """Whether `url` is a site that republishes pitch decks -- see
    DECK_MIRROR_DOMAINS. Verifying a deck claim against a copy of the deck is
    circular, and it is the failure mode that produced this project's most
    confidently wrong SUPPORTS verdicts."""
    return _host_in(url, DECK_MIRROR_DOMAINS)


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower())
            if w not in _STOP and len(w) > 2}


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _lexical_overlap(context: str, candidate: str) -> float:
    """Fallback used when the trained embedder is unavailable.

    Asymmetric on purpose: the question is "how much of the context does this
    page cover", not "how similar are these two texts". A long page that
    mentions the topic properly should not be penalised for its length.
    """
    ctx, cand = _tokens(context), _tokens(candidate)
    if not ctx or not cand:
        return 0.0
    return len(ctx & cand) / len(ctx)


def relevance(context: str, candidate: str) -> tuple[float, str]:
    """Similarity of `candidate` to `context` in [0, 1], plus the method used.

    The method is returned rather than only logged, because it changes how the
    score must be read: the embedder and the lexical fallback are not on the
    same scale, and a threshold tuned for one is meaningless for the other.
    """
    if not (context or "").strip() or not (candidate or "").strip():
        return 1.0, "no_context"
    context_vector = embeddings.embed_text(context)
    candidate_vector = embeddings.embed_text(candidate)
    if context_vector is not None and candidate_vector is not None:
        # SVD components are signed, so cosine lands in [-1, 1]. Negative means
        # "unrelated", not "anti-related", so it is clamped rather than scaled.
        return max(0.0, _cosine(context_vector, candidate_vector)), "embedding"
    return _lexical_overlap(context, candidate), "lexical"


def mentions_company(company: str, text: str) -> bool:
    """Whether `text` plausibly refers to `company`.

    Matches on the distinctive tokens of the name rather than the whole string,
    because retrieved pages write "Acme Robotics, Inc." and "Acme's" for a
    company stored as "Acme Robotics".
    """
    distinctive = [t for t in _tokens(company) if t not in _NAME_NOISE]
    if not distinctive:
        # A name made entirely of category words ("AI Labs") has no
        # distinctive token to match on, so claiming a match would be
        # meaningless. Say no and let the similarity gate decide.
        return False
    haystack = _tokens(text)
    return all(token in haystack for token in distinctive)


# Thresholds chosen to be permissive. Dropping a genuinely relevant source
# costs a wrongly-unverified claim, which the pipeline already treats as a
# serious outcome; keeping a marginal one costs the judge seeing a weak page
# among stronger ones. Those costs are asymmetric, so the threshold belongs
# near the floor, catching only the clearly unrelated. Measured, not guessed --
# see ml/scripts/eval_retrieval_quality.py.
MIN_RELEVANCE_EMBEDDING = 0.12
MIN_RELEVANCE_LEXICAL = 0.06


def filter_sources(
    items: list[dict],
    *,
    context: str = "",
    company: str = "",
    min_relevance: float | None = None,
) -> tuple[list[dict], list[dict]]:
    """Split retrieved `items` into (kept, dropped).

    Each item needs a `url` and is scored on its `title` + `snippet` (or
    `text`). Every dropped item carries a `_drop_reason` so the report can state
    what was discarded and why, rather than quietly showing fewer sources.

    A source that explicitly names the company is always kept regardless of
    similarity: an exact name match is stronger evidence of aboutness than any
    TF-IDF score, and that case is the one this whole change exists to serve.
    """
    kept: list[dict] = []
    dropped: list[dict] = []

    for item in items:
        url = item.get("url", "")
        text = " ".join(filter(None, [
            item.get("title", ""),
            item.get("snippet", ""),
            (item.get("text") or "")[:1500],
        ]))

        if is_noise_domain(url):
            dropped.append({**item, "_drop_reason": "noise domain (%s)" % domain_of(url)})
            continue

        if is_deck_mirror(url):
            dropped.append({
                **item,
                "_drop_reason": "circular: %s republishes pitch decks, so this is the "
                                "claim's own source" % domain_of(url),
            })
            continue

        if company and mentions_company(company, text):
            kept.append({**item, "_relevance": 1.0, "_relevance_method": "company_name"})
            continue

        score, method = relevance(context, text)
        if method == "no_context":
            # Nothing to compare against. Keeping is the honest default -- see
            # the degradation contract in this module's docstring.
            kept.append({**item, "_relevance": None, "_relevance_method": method})
            continue

        threshold = min_relevance if min_relevance is not None else (
            MIN_RELEVANCE_EMBEDDING if method == "embedding" else MIN_RELEVANCE_LEXICAL
        )
        if score >= threshold:
            kept.append({**item, "_relevance": round(score, 4), "_relevance_method": method})
        else:
            dropped.append({
                **item,
                "_relevance": round(score, 4),
                "_relevance_method": method,
                "_drop_reason": "off-topic (%s similarity %.3f < %.3f)" % (method, score, threshold),
            })

    return kept, dropped
