"""Find the companies a startup actually competes with.

## The problem this exists for

`comparables.py` matches a deck against 5,603 companies with a recorded
outcome, using the TF-IDF+SVD embedder from `embeddings.py`. That similarity is
**lexical**: it scores shared wording, not shared business. The module says so
in its own docstring and the report says so on the page.

Saying so is not the same as being useful. Canva's deck returned Boardcave (a
surf gear store), Fuzzwich, Jobspice, Lingt and Atmos at 55-61% -- not one of
them a design tool, and the tab they appeared under is called Competitor
Insights. A reader who does not stop to read the caveat concludes the product
cannot tell a design tool from a surfboard shop, and a reader who does read it
is left wondering what the table is for.

Both readings are fair. The corpus table answers "which companies in our
outcome corpus use similar words", which is a real question -- it is how the
outcome base rate is computed and that base rate is the score's anchor. It is
just not the question "who does this company compete with".

So that question gets its own answer, from the web, where it is documented.

## What keeps it honest

The same rule `founder_research.py` applies to names, for the same reason: ask
a language model "who competes with Canva" and it will answer from memory,
fluently, whether or not the search returned anything -- and a plausible wrong
competitor is indistinguishable from a real one on the page.

  1. Every proposed competitor must appear **verbatim in the retrieved search
     text**. The model's job is reduced to picking names out of evidence it was
     handed; anything it supplies from memory is removed by a string check it
     does not participate in (see `grounding.py`).
  2. Every returned competitor carries the URLs it was found in. One with no
     surviving source is not returned.
  3. When search fails, this returns `available: False` with the reason, never
     an empty list that reads as "this company has no competitors".

## What it is not

It is not a market census and does not claim to be one. It reports who the
public record names as competing with this company, which is a starting point
for diligence and not a finding about market structure. It carries no
similarity score, because the honest answer to "how similar" here is "these
sources put them in the same category", and a percentage would invent a
precision that nothing behind it supports.
"""
from __future__ import annotations

import json
import logging
import re

from agents.claim_verifier import fetch_page_text, search_web
from grounding import normalised_words, is_grounded
from groq_client import MODEL, get_client, pace_for, settle_usage

logger = logging.getLogger(__name__)

# Things a competitor-listing page is full of that are not companies: the
# listicle's own furniture, the publications hosting it, and category words.
_NOT_A_COMPANY = re.compile(
    r"^(?:top|best|the|a|an|our|other|more|view|see|read|compare|compared|"
    r"alternatives?|competitors?|companies|company|startups?|platforms?|"
    r"tools?|software|apps?|products?|reviews?|pricing|features|home|about|"
    r"blog|news|guide|list|vs|versus|and|or|for|with|\d+)$",
    re.IGNORECASE,
)

# Publications and aggregators that show up as "names" in competitor listings.
_PUBLISHERS = {
    "g2", "capterra", "crunchbase", "forbes", "techcrunch", "wikipedia",
    "linkedin", "reddit", "quora", "medium", "gartner", "trustradius",
    "producthunt", "product hunt", "getapp", "softwareadvice", "slashdot",
    "sourceforge", "owler", "zoominfo", "pitchbook", "cbinsights", "statista",
}

_PROMPT = """From the search results below, list the companies named as COMPETITORS of or ALTERNATIVES to the subject company.

Return ONLY a JSON object:
{"competitors": [{"name": "<company name exactly as written in the text>", "what_it_does": "<a phrase from the text describing it, or empty>"}]}

Rules:
- Copy each name exactly as it appears in the text. Every name is checked against
  the text word for word afterwards and dropped if it is not found there.
- Only name companies the text presents as competing with, or as an alternative
  to, the subject. Do not list the subject itself.
- Do not list the websites hosting the article (G2, Capterra, Crunchbase,
  Forbes, TechCrunch and the like) -- those are publishers, not competitors.
- Never add a company you know of that is not named in this text. A competitor
  you supply from memory is indistinguishable from a real finding on the page
  and is worse than a short list.
- Return an empty list if the text names none.
- At most 12.

SUBJECT COMPANY: {company}
WHAT IT DOES: {description}

SEARCH RESULTS:
"""


def _queries(company: str, description: str, sector: str) -> list[str]:
    """The phrasings that actually surface a competitor set.

    "X competitors" alone is thin for a young company; "alternatives to X" hits
    the review-site listings, and a sector-qualified query catches the case
    where the name is ambiguous ("Atmos" is four companies).
    """
    queries = [
        f"{company} competitors",
        f"alternatives to {company}",
    ]
    if sector:
        queries.append(f"{company} {sector} competitors")
    if description:
        words = [w for w in re.findall(r"[A-Za-z]{4,}", description)][:6]
        if words:
            queries.append(f"companies like {company} {' '.join(words[:4])}")
    return queries


def _clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "")).strip(" .,:;\"'()[]")


def find_competitors(
    company: str, description: str = "", sector: str = "", max_results: int = 10
) -> dict:
    """Never raises. Returns `available`, and when True also `competitors` and
    `sources_consulted`.

    `available: False` with a reason is a real result and must not be rendered
    as "no competitors found" -- the two are different claims about the world.
    """
    company = (company or "").strip()
    if not company:
        return {"available": False, "reason": "No company name to search for."}

    evidence: list[dict] = []
    seen_urls: set[str] = set()
    failures = 0
    queries = _queries(company, description, sector)

    for query in queries:
        try:
            results = search_web(query, max_results=5, raise_on_error=True)
        except Exception:
            failures += 1
            logger.warning("Competitor search failed for %r", query, exc_info=True)
            continue
        for result in results:
            url = result.get("url") or ""
            if url and url not in seen_urls:
                seen_urls.add(url)
                evidence.append(result)

    if failures == len(queries):
        return {
            "available": False,
            "reason": (
                "Every competitor search failed, so this is not evidence that the "
                "company has no competitors -- the search did not run."
            ),
        }
    if not evidence:
        return {
            "available": False,
            "reason": f"Searched public sources for competitors of {company} and found no usable pages.",
            "sources_consulted": [],
        }

    # Snippets are chosen to match the query, not to answer it, so the bodies of
    # the most promising results are fetched too -- and they become part of the
    # haystack the grounding check searches, not just of what the model reads.
    for result in evidence[:5]:
        try:
            body = fetch_page_text(result["url"], max_chars=2500)
        except Exception:
            body = ""
        if body:
            result["page_text"] = body

    blocks = []
    for result in evidence[:10]:
        blocks.append(
            f"[{result.get('url', '')}]\n"
            f"{result.get('title', '')}\n"
            f"{result.get('snippet', result.get('body', ''))}\n"
            f"{result.get('page_text', '')[:1200]}"
        )
    corpus = "\n\n".join(blocks)
    haystack = normalised_words(corpus)

    prompt = (
        _PROMPT.replace("{company}", company)
        .replace("{description}", (description or "")[:300])
        + corpus[:5500]
    )

    try:
        pace_for(len(prompt), 800)
        response = get_client().chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": (
                    "You extract competitor company names from search results. "
                    "Output valid JSON only. Never name a company that is not in the text."
                )},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=800,
            response_format={"type": "json_object"},
        )
        settle_usage(response, len(prompt), 800)
        payload = json.loads(response.choices[0].message.content or "{}")
    except Exception as exc:
        logger.warning("Competitor extraction did not run: %s", exc)
        return {
            "available": False,
            "reason": "Competitor pages were retrieved but the model that reads them did not run.",
            "sources_consulted": list(seen_urls),
        }

    subject = company.lower()
    competitors: list[dict] = []
    seen_names: set[str] = set()

    for item in payload.get("competitors") or []:
        if not isinstance(item, dict):
            continue
        name = _clean_name(str(item.get("name") or ""))
        if not name or len(name) > 60:
            continue
        low = name.lower()
        if low == subject or low in seen_names:
            continue
        if low in _PUBLISHERS or _NOT_A_COMPANY.match(low):
            continue
        # The guard: a name the model supplied from memory is not in the pages.
        if not is_grounded(name, haystack) and name.lower() not in corpus.lower():
            logger.info("Dropped ungrounded competitor %r for %s", name, company)
            continue

        # Which pages actually mention it, so the row can be checked.
        sources = [
            r.get("url") for r in evidence
            if name.lower() in (
                f"{r.get('title','')} {r.get('snippet', r.get('body',''))} {r.get('page_text','')}"
            ).lower() and r.get("url")
        ][:4]
        if not sources:
            continue

        seen_names.add(low)
        competitors.append({
            "name": name,
            "what_it_does": _clean_name(str(item.get("what_it_does") or ""))[:160],
            "sources": sources,
        })
        if len(competitors) >= max_results:
            break

    if not competitors:
        return {
            "available": False,
            "reason": (
                f"Searched {len(seen_urls)} public source(s) for competitors of {company}. "
                "No competitor could be established from them."
            ),
            "sources_consulted": list(seen_urls),
        }

    return {
        "available": True,
        "competitors": competitors,
        "sources_consulted": list(seen_urls),
        "note": (
            "Named as competitors or alternatives by the public sources listed. "
            "This is where to start, not a market census."
        ),
    }
