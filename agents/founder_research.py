"""Find out who founded a company when its deck never says.

Why this exists. The pipeline's founder analysis had exactly one input: names
printed in the deck. When a deck did not name its team -- which is most decks,
and all four of Oscar Health, Nutanix, Brex and Alan in this project's own
corpus -- the report said "No founder names were submitted" and stopped. That
is a dead end dressed as a finding: the founders of these companies are a
matter of public record, and a diligence tool that cannot look them up is not
doing diligence.

So when the deck discloses no team, this searches for one.

## The anti-fabrication guard

The obvious failure mode is severe and quiet: ask a language model "who
founded Oscar Health" and it will answer from parametric memory, confidently,
whether or not the search returned anything -- and a plausible wrong name then
gets a full background check written about it, which reads exactly like a real
finding. A name is the one field where a good guess is worse than a blank,
because everything downstream inherits its authority.

Two mechanical guards, neither of which the model can talk its way past:

1. Every proposed name must appear **verbatim in the retrieved search text**.
   The model's role is reduced to picking names out of evidence it was handed,
   and any name it supplies from memory is dropped by a string check it does
   not participate in.
2. Every returned founder carries the URLs it was found in. A name with no
   surviving source is not returned at all.

When search finds nothing, or nothing survives the guards, this returns
`found: False` with the reason. "We searched and could not establish this" is
a legitimate diligence output; a plausible name is not.

## Scope

Founders and their backgrounds only. Search results about company history,
market size, funding rounds or product are read solely to identify people and
are otherwise discarded -- this module is not a general company researcher and
must not become one.
"""
from __future__ import annotations

import json
import logging
import os
import re

from agents.claim_verifier import fetch_page_text, search_web
from groq_client import note_provider_failure, MODEL, get_client, pace_for, settle_usage, describe_provider_failure

logger = logging.getLogger(__name__)

# Names that are really companies, roles or artefacts of search-result titles.
# Without this the extractor happily proposes "Oscar Health" as a person.
_NOT_A_PERSON = re.compile(
    r"\b(inc|llc|ltd|corp|corporation|company|technologies|labs|ventures|"
    r"capital|partners|group|holdings|health|bank|university|college|"
    r"linkedin|crunchbase|wikipedia|forbes|techcrunch|bloomberg|reuters)\b",
    re.IGNORECASE,
)

# A person's name as printed: two to four capitalised words, allowing
# apostrophes and hyphens (O'Brien, Sanchez-Rivera).
#
# Four, not three, because a compound name loses its hyphens in transit and
# gains a word doing so: "Jean-Charles Samuelian-Werve" comes back as four
# tokens and was rejected before grounding ever ran. Widening this is safe
# because the real filtering happens afterwards -- the name must appear as a
# whole name in the source AND have founding attributed to it there.
_PERSON_SHAPE = re.compile(r"^[A-Z][\w'’-]+(?:\s+[A-Z][\w'’.-]+){1,3}$")

MAX_FOUNDERS = 3

# Founder language must be GRAMMATICALLY ATTACHED to the name, not merely near
# it. A proximity window was tried first and is not good enough: on the dense
# aggregator pages that dominate these search results, "Acme was founded by Ada
# Lovelace. Leadership: Grace Hopper, VP Engineering" puts a founder verb
# within a few dozen characters of someone who is plainly not a founder. Any
# window wide enough to catch "founded in 2013 by <name>" is also wide enough
# to swallow the next sentence.
#
# These four shapes are how a source actually attributes founding to a person.
# `{name}` is substituted with the escaped name at match time.
_ATTRIBUTION_PATTERNS = (
    # "founded by X" / "co-founded in 2013 by A and X"
    r"\b(?:co[-\s]?)?found(?:ed|er[s]?)\b[^.;!?]{{0,90}}?\b{name}\b",
    # "X, co-founder" / "X - founder and CEO" / "X (founder)"
    r"\b{name}\b[\s,:\-–—(]{{1,6}}(?:the\s+)?(?:co[-\s]?)?founder",
    # "X founded the company" / "X co-founded Acme"
    r"\b{name}\b\s+(?:co[-\s]?)?founded\b",
)

# Kill switch, default on.
#
# This runs inline in the diligence pipeline and is the only step there that
# reaches the open web unprompted: up to six searches plus six page fetches,
# fired automatically whenever a deck names no team -- which is most decks. That
# is the right production behaviour and the wrong default for a test suite,
# where it silently attached a minutes-long network dependency to every test
# that exercised the full pipeline without opting into one. Also useful for an
# offline or air-gapped run.
#
# Off returns an honest "not attempted" rather than a fabricated absence, so a
# disabled search can never be mistaken for a search that found nothing.
RESEARCH_ENABLED = os.getenv(
    "VENTUREFLOW_FOUNDER_RESEARCH", "on"
).strip().lower() not in {"off", "0", "false", "no"}


def _context_keywords(context: str, limit: int = 5, skip: frozenset = frozenset()) -> str:
    """A few distinctive words from the deck, to disambiguate the company name.

    Not cosmetic. A one-word company name is not a searchable entity on its
    own: "Alan founders" returns seventeen results about people called Alan
    and establishes nothing, while "Alan health insurance France founders"
    finds the company on the first page. The keywords come from the deck the
    user uploaded, so this stays grounded in the submission rather than in
    anything assumed about the company.
    """
    words = [
        w
        for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", context or "")
        if w.lower() not in _CONTEXT_STOPWORDS and w.lower() not in skip
    ]
    seen: set[str] = set()
    keep: list[str] = []
    for w in words:
        key = w.lower()
        if key not in seen:
            seen.add(key)
            keep.append(w)
        if len(keep) >= limit:
            break
    return " ".join(keep)


_CONTEXT_STOPWORDS = frozenset("""
that this with from they their there which what when where would could should
have been being about into over under more most other some such only same
company startup deck slide pitch round raise raising million billion market
""".split())


def _build_queries(company: str, stage: str, deck_date: str, context: str = "") -> list[str]:
    """Queries that pin the search to the company AND its era.

    The date context matters: "Brex founders" surfaces present-day executives,
    while the deck being analysed is a 2018 Series C. Anchoring on the year
    keeps the search on the people who were actually running it then.
    """
    year = (deck_date or "").strip()[:4]
    queries = [
        f"{company} founders",
        f"who founded {company}",
        f"{company} co-founder CEO",
    ]
    keywords = _context_keywords(context, skip=frozenset({company.lower()}))
    if keywords:
        queries.insert(0, f"{company} {keywords} founders")
    if year.isdigit():
        queries.append(f"{company} founded {year} founders")
    if stage:
        queries.append(f"{company} {stage} round founders")
    return queries


def _gather_evidence(
    company: str, stage: str, deck_date: str, context: str = ""
) -> tuple[list[dict], int, int]:
    """Returns (evidence, queries_run, queries_failed).

    The counts are not diagnostics -- they decide what the report is allowed to
    say. Zero results after five successful searches means the founders are not
    readily documented; zero results after five failed searches means we do not
    know anything, and reporting the second as the first states a fact about
    the company that was never established.
    """
    seen: set[str] = set()
    evidence: list[dict] = []
    queries = _build_queries(company, stage, deck_date, context)
    failed = 0
    for query in queries:
        try:
            results = search_web(query, max_results=5, raise_on_error=True)
        except Exception:
            failed += 1
            logger.warning("Founder-discovery search failed for %r", query, exc_info=True)
            continue
        for r in results:
            url = r.get("url") or ""
            if url and url not in seen:
                seen.add(url)
                evidence.append(r)

    # Snippets alone are not enough to establish a founder's name, and this is
    # not an edge case. Searching "Alan health insurance France founders"
    # returns exactly the right pages -- the company's own leadership page,
    # Crunchbase, an EU-Startups funding article -- and not one of their search
    # snippets contains a founder's name, because a snippet is chosen to match
    # the query rather than to answer it. The grounding guard then correctly
    # rejected every proposed name and the module reported "not found" for a
    # company whose founders were one click away.
    #
    # So the page body is fetched for the most promising results and becomes
    # part of both the evidence shown to the model AND the haystack the
    # grounding check searches. Best-effort: a page that will not load simply
    # contributes nothing.
    for r in evidence[:6]:
        try:
            body = fetch_page_text(r["url"], max_chars=2500)
        except Exception:
            body = ""
        if body:
            r["page_text"] = body
    return evidence, len(queries) - failed, failed


def _evidence_text(evidence: list[dict]) -> str:
    blocks = []
    for i, r in enumerate(evidence[:12], 1):
        body = (r.get("page_text") or "")[:1200]
        blocks.append(
            f"[{i}] {r.get('title', '')}\n"
            f"URL: {r.get('url', '')}\n"
            f"{r.get('snippet', '')}"
            + (f"\nPAGE TEXT: {body}" if body else "")
        )
    return "\n\n".join(blocks)


class ProposalUnavailable(RuntimeError):
    """The model that picks names out of the evidence could not run.

    Distinct from "it ran and found nobody", and the distinction is the whole
    point: both used to return an empty list, so a provider outage was reported
    to the user as "Searched 14 public source(s) for the founders of Uber. No
    founder name could be established from them."

    Every clause of that was misleading. The sources included Garrett Camp's
    own Wikipedia page; what failed was our call to the language model, not the
    search and not the evidence.
    """


def _propose_names(company: str, evidence_block: str) -> list[str]:
    """Ask the model to pick founder names OUT OF the supplied evidence."""
    prompt = f"""Below are public web search results about the company "{company}".

Identify the people named in these results as FOUNDERS or CO-FOUNDERS of
"{company}" (a founding CEO/CTO counts; a later-hired executive, an investor,
a board member or a journalist does not).

SEARCH RESULTS:
{evidence_block}

Hard rules:
- Only return a name that appears LITERALLY in the search results above.
- Do NOT use anything you know about this company from outside these results.
  If the results do not name the founders, return an empty list. That is a
  correct and useful answer.
- Return people, never company names or job titles.
- At most {MAX_FOUNDERS} names.

Respond with ONLY valid JSON:
{{"founders": [{{"name": "<full name exactly as written above>", "role": "<founding role stated, or empty string>"}}]}}"""

    # max_tokens is generous relative to the ~60-token answer because
    # openai/gpt-oss-120b emits reasoning tokens ahead of its content, and they
    # are charged against the same ceiling. At 400 the model ran out mid-thought
    # and Groq rejected the whole call with `json_validate_failed:
    # "max completion tokens reached before generating a valid document"` --
    # which this module's own error handling then reported, correctly but
    # uselessly, as "no founder name could be established".
    try:
        pace_for(len(prompt), 1200)
        response = get_client().chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract founder names from supplied search results. "
                        "You never use outside knowledge. JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=1200,
            response_format={"type": "json_object"},
        )
        # Return the completion budget this call reserved but did not use.
        # Bookkeeping only -- it cannot change what the model said, and it
        # stops the next call waiting on tokens nobody spent.
        settle_usage(response, len(prompt), 1200)
        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Founder-discovery returned unparseable JSON")
        raise ProposalUnavailable("the model's reply could not be parsed") from None
    except Exception as exc:
        logger.warning("Founder-discovery model call failed", exc_info=True)
        note_provider_failure(exc)
        detail = describe_provider_failure(exc)
        raise ProposalUnavailable(detail) from exc

    names: list[str] = []
    for item in (parsed.get("founders") or [])[:MAX_FOUNDERS]:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]).strip())
        elif isinstance(item, str):
            names.append(item.strip())
    return names


def _normalise(text: str) -> str:
    """Lowercase, and flatten the punctuation that splits compound names.

    Hyphens and apostrophes are the difference between a correct founder and a
    dropped one. Alan's co-founder is written "Jean-Charles Samuelian-Werve" in
    every source; the model returned "Jean Charles Samuelian Werve", the literal
    check found no match, and a real founder was discarded as ungrounded. The
    guard is supposed to reject names the sources do not support, not names
    whose hyphens were normalised away in transit.
    """
    return re.sub(r"[-‐‑‒–—’'`]+", " ", (text or "").lower())


def _name_regex(name: str) -> str:
    """The name as a pattern tolerant of internal whitespace/punctuation."""
    parts = [re.escape(p) for p in _normalise(name).split() if p]
    return r"\s+".join(parts)


# A maximal run of capitalised words, which is how a person's full name appears
# in prose. Hyphenated and apostrophed segments stay inside one run so
# "Jean-Charles Samuelian-Werve" is a single name, not four.
_NAME_RUN = re.compile(r"\b[A-Z][\w'’\-‐‑–]*(?:\s+[A-Z][\w'’\-‐‑–]*){1,3}\b")


def _names_in(text: str) -> set[str]:
    """Every whole name the text contains, normalised.

    Maximal runs, deliberately: matching a substring would let a truncated name
    ground itself inside a longer one, and a truncated name is a different
    person than the source actually named.
    """
    return {_normalise(m.group(0)) for m in _NAME_RUN.finditer(text or "")}


def _grounded(name: str, evidence: list[dict]) -> list[str]:
    """URLs that name this person AS A FOUNDER. Empty means ungrounded.

    This is the guard that makes the whole module safe: it runs on raw strings
    and the model has no say in it, so a name recalled from training data
    rather than read from the evidence cannot survive.

    Mere presence is not enough. Aggregator company profiles list founders,
    executives, investors, board members and sometimes the analyst who wrote
    the page, all in the same markup, so a presence-only check cannot tell
    "founded this company" from "appears on a page about this company". The
    failure that produces is not an invented name but an invented
    RELATIONSHIP: a real person attached to a claim no source made, which
    reads exactly as authoritative and is harder to spot than a hallucinated
    name.

    (The case that prompted this check turned out, on reading the sources, to
    be correctly attributed after all -- both pages did say "founded by". The
    check is kept because the reasoning holds regardless of that one example,
    and because it is cheap; but no specific person is cited here as a
    misattribution, because doing so would write an unsourced claim about a
    real individual into this file.)

    So a source counts only when it attributes founding to this person in one
    of the shapes in `_ATTRIBUTION_PATTERNS`. Still a pure string operation the
    model cannot influence.
    """
    if not _PERSON_SHAPE.match(name) or _NOT_A_PERSON.search(name):
        return []

    target = _normalise(name)
    patterns = [
        re.compile(p.format(name=_name_regex(name)), re.IGNORECASE | re.DOTALL)
        for p in _ATTRIBUTION_PATTERNS
    ]

    urls = []
    for r in evidence:
        raw = f"{r.get('title', '')} {r.get('snippet', '')} {r.get('page_text', '')}"
        url = r.get("url") or ""
        if not url:
            continue

        # Two independent conditions, both required.
        #
        # 1. The source must name this person as a WHOLE name. Comparing against
        #    maximal capitalised runs rather than searching for a substring is
        #    what stops "Charles Samuelian" grounding itself inside
        #    "Jean-Charles Samuelian-Werve" -- a truncated name is a different
        #    person, and reporting one is the same misattribution the
        #    attribution patterns exist to prevent.
        # 2. Founding must be attributed to them here, not merely mentioned
        #    nearby.
        if target not in _names_in(raw):
            continue
        if any(p.search(_normalise(raw)) for p in patterns):
            urls.append(url)
    return urls


def discover_founders(
    company: str,
    stage: str = "",
    deck_date: str = "",
    context: str = "",
) -> dict:
    """Search public sources for who founded `company`.

    Never raises. Returns a dict with `found`; when True, `founders` is a list
    of {name, role, discovery_sources}. When False, `reason` says why, and
    that reason is intended to be shown to the reader verbatim.
    """
    if not RESEARCH_ENABLED:
        return {
            "found": False,
            "reason": (
                "Founder research is disabled for this run "
                "(VENTUREFLOW_FOUNDER_RESEARCH=off). No search was attempted, so "
                "this is not evidence that the founders could not be found."
            ),
            "searched": False,
            "sources_consulted": [],
        }

    company = (company or "").strip()
    if not company or company.lower() in {"unknown company", "unknown"}:
        return {
            "found": False,
            "reason": "No company name was available to search on.",
            "searched": False,
            "sources_consulted": [],
        }

    evidence, ran, failed = _gather_evidence(company, stage, deck_date, context)

    # Search unavailable is NOT the same finding as search found nothing, and
    # the difference has to reach the report. One is a fact about the company;
    # the other is a fact about our connectivity, and only the first belongs in
    # a diligence memo.
    if ran == 0 and failed:
        return {
            "found": False,
            "reason": (
                f"Founder search could not be completed: all {failed} web searches "
                f"for {company} failed (network, provider error or rate limit). "
                f"NOTHING was established about this company's founders -- do not "
                f"read this as evidence that they could not be found. Retry when "
                f"search is available."
            ),
            "searched": False,
            "search_failed": True,
            "queries_failed": failed,
            "sources_consulted": [],
        }

    if not evidence:
        return {
            "found": False,
            "reason": (
                f"Searched public web sources for the founders of {company} "
                f"({ran} search(es) ran"
                + (f", {failed} failed" if failed else "")
                + f") and no results were returned. No founder names could be "
                f"established."
            ),
            "searched": True,
            "search_failed": False,
            "queries_failed": failed,
            "sources_consulted": [],
        }

    consulted = [r.get("url", "") for r in evidence if r.get("url")]
    try:
        proposed = _propose_names(company, _evidence_text(evidence))
    except ProposalUnavailable as exc:
        # A fourth state, alongside "not attempted", "search failed" and
        # "searched and found nothing": the search worked, the evidence is
        # here, and the step that reads it did not run.
        return {
            "found": False,
            "attempted": True,
            "searched": True,
            "degraded": True,
            "sources_consulted": consulted,
            "reason": (
                f"Founder research could not be completed: {exc}. "
                f"{len(consulted)} public source(s) were retrieved but never "
                f"read, so nothing was established either way. This is a fact "
                f"about this deployment, not about the company."
            ),
        }

    founders = []
    rejected = []
    by_identity: dict[str, dict] = {}
    for name in proposed:
        sources = _grounded(name, evidence)
        if sources:
            # Merge ONLY on exact identity after punctuation normalisation.
            #
            # Aggregator pages routinely list one person twice under two
            # spellings -- Tracxn's Alan profile gives both "Jean-Charles
            # Samuelian-Werve" and "Jean Charles Samuelian Werve" in the same
            # sentence -- and reporting them as two founders is plainly wrong.
            #
            # Deliberately NOT a similarity threshold. Alan is its own
            # counter-example: its two genuine founders are Charles Gorintin
            # and Jean-Charles Samuelian-Werve, who share a forename token. Any
            # fuzzy matcher tuned to catch the spelling variant is also tuned
            # to collapse those two real people into one, and silently losing a
            # founder is far worse than showing a visible duplicate. So this
            # merges only when the normalised strings are equal -- no judgement
            # is being exercised -- and anything weaker is flagged below for a
            # human instead.
            identity = _normalise(name)
            existing = by_identity.get(identity)
            if existing:
                if name not in existing["name_variants"]:
                    existing["name_variants"].append(name)
                for url in sources:
                    if url not in existing["discovery_sources"]:
                        existing["discovery_sources"].append(url)
                continue
            entry = {
                "name": name,
                "role": "",
                "discovery_sources": sources[:4],
                "name_variants": [name],
            }
            by_identity[identity] = entry
            founders.append(entry)
        else:
            # Kept for the report: a model proposing names that are not in the
            # evidence is exactly the behaviour this guard exists to catch, and
            # silently dropping it would hide a real signal about the run.
            rejected.append(name)

    if rejected:
        logger.warning(
            "Dropped %d ungrounded founder name(s) for %s: %s",
            len(rejected), company, rejected,
        )

    if not founders:
        return {
            "found": False,
            "reason": (
                f"Searched {len(consulted)} public source(s) for the founders of "
                f"{company}. No founder name could be established from them"
                + (
                    f" ({len(rejected)} candidate name(s) were proposed but did not "
                    f"appear in the retrieved sources and were rejected as "
                    f"ungrounded)."
                    if rejected
                    else "."
                )
            ),
            "searched": True,
            "sources_consulted": consulted[:8],
            "rejected_ungrounded": rejected,
        }

    for entry in founders:
        if len(entry["name_variants"]) == 1:
            entry.pop("name_variants")

    review = _possible_same_person(founders)
    if review:
        logger.info(
            "Founder names for %s may include the same person twice: %s",
            company, review,
        )

    return {
        "found": True,
        "founders": founders,
        "searched": True,
        "sources_consulted": consulted[:8],
        "rejected_ungrounded": rejected,
        # Pairs a human should look at. NOT merged -- see the note in the loop
        # above about why a similarity threshold is the wrong tool here.
        "possible_same_person": review,
    }


def _possible_same_person(founders: list[dict]) -> list[dict]:
    """Flag founder pairs that might be one person listed twice.

    Reported, never acted on. The test is a strict token-subset -- every token
    of one name also appears in the other, and the other has more -- which is
    what a truncated or middle-name-dropped variant looks like ("Charles
    Samuelian" inside "Jean Charles Samuelian Werve").

    A shared surname alone is deliberately NOT flagged: co-founders are
    frequently siblings or spouses, and flagging every such pair would train
    whoever reads this to ignore the flag.
    """
    flags = []
    for i, a in enumerate(founders):
        for b in founders[i + 1:]:
            ta, tb = set(_normalise(a["name"]).split()), set(_normalise(b["name"]).split())
            if ta == tb:
                continue
            if ta < tb or tb < ta:
                shorter, longer = (a, b) if len(ta) < len(tb) else (b, a)
                flags.append({
                    "names": [shorter["name"], longer["name"]],
                    "reason": (
                        f"Every part of {shorter['name']!r} also appears in "
                        f"{longer['name']!r}. These may be one person listed "
                        f"under two spellings, or two different people. They "
                        f"have NOT been merged -- confirm against the cited "
                        f"sources before treating either as a distinct founder."
                    ),
                })
    return flags
