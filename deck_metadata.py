"""Extract the structured deck facts nothing was populating.

WHY THIS FILE EXISTS

`ml/scripts/audit_signal_path.py` traced every field the scoring model and
report consume, hop by hop, from PDF text to the number a user sees. Six of
twelve never arrived. Five of those six were never extracted from the deck at
all -- the field existed on the request model, was threaded through the
pipeline, and was read by a consumer, but nothing upstream ever filled it.

Two of them are the most consequential inputs the score model has:

    stage    42 points of range   (Seed / Early / Growth)
    sector   24 points of range   (B2B / Consumer / Fintech / ...)

So every analysis ever run scored decks with the model's two largest levers set
to "unknown". That is the same defect as the `stage=None` hardcode found last
session -- fixed one layer down and still broken one layer up.

WHAT THIS DELIBERATELY DOES NOT DO

It does not guess. Every function returns `None` when the deck does not say,
and `None` travels onward as "unknown" rather than as a default. A fabricated
stage would be worse than no stage: it would move the score 42 points on the
strength of an invention, and the report would present it identically to a
stage the deck actually stated.

Every extraction also returns the evidence it matched, so a reader can check it
and the report can show its work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DeckMetadata:
    stage: str | None = None
    sector: str | None = None
    team_size: int | None = None
    github_url: str | None = None
    domain: str | None = None
    evidence: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "sector": self.sector,
            "team_size": self.team_size,
            "github_url": self.github_url,
            "domain": self.domain,
            "evidence": dict(self.evidence),
        }


# Round language -> the stage vocabulary the score model was trained on. The
# model's categorical encoder was fitted on YC's own values, so mapping into
# that vocabulary is required; inventing a new label would encode to "unknown"
# and waste the extraction entirely.
_STAGE_PATTERNS: list[tuple[str, str]] = [
    (r"\b(?:pre[\s-]?seed|preseed)\b", "Seed"),
    (r"\bseed\s*(?:round|deck|financing|funding)?\b", "Seed"),
    (r"\bangel\s*round\b", "Seed"),
    (r"\bseries\s*a\b", "Early"),
    (r"\bseries\s*b\b", "Growth"),
    (r"\bseries\s*[c-f]\b", "Growth"),
    (r"\bgrowth\s*(?:round|equity)\b", "Growth"),
    (r"\bmezzanine\b", "Growth"),
]

# Sector language -> YC industry vocabulary, same reasoning as stage.
_SECTOR_PATTERNS: list[tuple[str, str]] = [
    # "infrastructure" was removed after it matched Uber's 2008 consumer deck
    # on the single phrase "Extend infrastructure to other LBS applications".
    # A word that appears once, in passing, inside a sentence about something
    # else is not evidence of a company's sector.
    (r"\b(?:b2b|enterprise\s+saas|saas\s+platform|developer\s+tools?|"
     r"devtools?|api\s+platform)\b", "B2B"),
    (r"\b(?:fintech|payments?|banking|lending|insurtech|neobank)\b", "Fintech"),
    (r"\b(?:healthcare|healthtech|biotech|medical|clinical|diagnostics?|"
     r"telemedicine|digital\s+health)\b", "Healthcare"),
    (r"\b(?:consumer\s+app|marketplace|social\s+network|e-?commerce|"
     r"direct[\s-]to[\s-]consumer|d2c)\b", "Consumer"),
    (r"\b(?:logistics|supply\s+chain|manufacturing|robotics|industrial|"
     r"warehouse\s+automation)\b", "Industrials"),
    (r"\b(?:edtech|education\s+platform)\b", "Education"),
    (r"\b(?:proptech|real\s+estate|construction\s+tech)\b", "Real Estate and Construction"),
]


def _window(text: str, match: re.Match, width: int = 60) -> str:
    start = max(0, match.start() - width // 2)
    return re.sub(r"\s+", " ", text[start:match.end() + width // 2]).strip()


def extract_stage(text: str) -> tuple[str | None, str]:
    """The round being raised, or None when the deck does not say.

    Searched in the opening 4,000 characters first, because a deck states its
    round on the cover or the ask slide, while a later mention is usually
    history ("we raised a seed in 2019") describing a *previous* round.
    """
    if not text:
        return None, ""
    head = text[:4000]

    # A progression phrase names two rounds and is describing history, not the
    # round being raised. Front's Series A deck was labelled "Seed" because it
    # contains the line "record of capital efficiency Seed to Series A" -- the
    # first pattern matched and won. Any deck saying "X to Y" is claiming
    # to have travelled from X, so Y is the more recent round.
    progression = re.search(
        r"\b(pre[\s-]?seed|seed|series\s*[a-f])\b\s*(?:to|->|-|through)\s*"
        r"\b(pre[\s-]?seed|seed|series\s*[a-f])\b",
        text, re.IGNORECASE,
    )
    if progression:
        later = progression.group(2).lower()
        for pattern, stage in _STAGE_PATTERNS:
            if re.fullmatch(pattern.replace(r"\s*(?:round|deck|financing|funding)?", ""),
                            later, re.IGNORECASE) or re.search(pattern, later, re.IGNORECASE):
                return stage, (
                    f"progression phrase, taking the later round: "
                    f"{_window(text, progression)}"
                )

    for pattern, stage in _STAGE_PATTERNS:
        match = re.search(pattern, head, re.IGNORECASE)
        if match:
            return stage, _window(head, match)
    # Fall back to the whole document, accepting the higher error rate rather
    # than discarding a real signal.
    for pattern, stage in _STAGE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return stage, _window(text, match)
    return None, ""


def extract_sector(text: str) -> tuple[str | None, str]:
    """The industry, by the most frequently-evidenced category.

    Counts matches rather than taking the first, because a deck mentions many
    domains in passing and the first mention is not usually the company's own.
    """
    if not text:
        return None, ""
    best: tuple[str, int, str] | None = None
    for pattern, sector in _SECTOR_PATTERNS:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if not matches:
            continue
        count = len(matches)
        if best is None or count > best[1]:
            best = (sector, count, _window(text, matches[0]))
    if best is None:
        return None, ""
    # A single passing mention is not a sector. Requiring corroboration is what
    # separates "this deck is about fintech" from "this deck used the word once
    # while describing something else" -- the error that labelled Uber's 2008
    # consumer deck B2B.
    if best[1] < 2:
        return None, ""
    return best[0], f"{best[1]} mention(s); e.g. {best[2]}"


def extract_team_size(text: str) -> tuple[int | None, str]:
    """Headcount, only where the deck states it as a team count.

    Deliberately narrow. A bare number near the word "team" is far more often a
    market size, a year, or a slide number, and a wrong headcount is worse than
    none because it silently changes a scored feature.
    """
    if not text:
        return None, ""
    patterns = [
        r"\bteam\s+of\s+(\d{1,4})\b",
        r"\b(\d{1,4})\s+(?:full[\s-]?time\s+)?employees\b",
        r"\b(\d{1,4})\s+person\s+team\b",
        r"\bheadcount[:\s]+(\d{1,4})\b",
        r"\bwe\s+are\s+(\d{1,4})\s+people\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                value = int(match.group(1))
            except ValueError:
                continue
            # A "team" of 5,000 in a seed deck is a market figure, not headcount.
            if 1 <= value <= 2000:
                return value, _window(text, match)
    return None, ""


def extract_github_url(text: str) -> tuple[str | None, str]:
    """A GitHub org or repo URL, if the deck prints one.

    `technical_scoring.py` has been fully built and wired since the third pass
    and has never once executed, because nothing ever supplied this.
    """
    if not text:
        return None, ""
    match = re.search(
        r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})"
        r"(?:/([A-Za-z0-9._-]{1,100}))?",
        text, re.IGNORECASE,
    )
    if not match:
        return None, ""
    org = match.group(1)
    repo = match.group(2)
    url = f"https://github.com/{org}" + (f"/{repo}" if repo else "")
    return url, _window(text, match)


def _name_tokens(company: str) -> set[str]:
    """Distinctive lowercase tokens from a company name."""
    stop = {"inc", "llc", "ltd", "corp", "co", "the", "company", "labs", "ai", "app"}
    return {
        t for t in re.findall(r"[a-z0-9]+", (company or "").lower())
        if len(t) >= 3 and t not in stop
    }


def extract_domain(text: str, company: str = "") -> tuple[str | None, str]:
    """The company's OWN website, used for portfolio comparison.

    Requires the host to corroborate the company name when a name is supplied.

    Without that check this returns whichever plausible domain appears first,
    which on real decks is frequently somebody else's: Airbnb's 2009 deck
    yielded "couchsurfing.com" (a competitor named on the market slide) and
    Mint's yielded "emetrics.org" (a conference). Handing either to portfolio
    matching would be a wrong claim about the company, made silently -- the
    exact failure class this pass exists to eliminate. When nothing
    corroborates, None is the honest answer.
    """
    if not text:
        return None, ""
    skip = {
        "github.com", "twitter.com", "x.com", "linkedin.com", "facebook.com",
        "instagram.com", "youtube.com", "gmail.com", "google.com", "medium.com",
        "slideshare.net", "scribd.com", "genppt.com", "media.genppt.com",
        "crunchbase.com", "angel.co", "ycombinator.com",
        # Aggregator watermarks. Airbnb's deck was labelled with the domain
        # "pitchdeckcoach.com" because the re-hosting site stamps
        # "editable PowerPoint version at PitchDeckCoach.com" onto the slides.
        # The deck's own domain must not be read off whoever republished it.
        "pitchdeckcoach.com", "slidebean.com", "upmetrics.co", "failory.com",
        "bestpitchdeck.com", "pitchdeckexamples.com", "visme.co", "piktochart.com",
        # Placeholder addresses printed on template contact slides.
        "company.com", "example.com", "yourcompany.com", "domain.com",
        "email.com", "website.com",
    }
    tokens = _name_tokens(company)
    fallback: tuple[str, str] | None = None
    for match in re.finditer(
        r"\b(?:https?://)?(?:www\.)?([a-z0-9][a-z0-9-]{1,61}\.(?:com|io|ai|co|app|dev|net|org))\b",
        text, re.IGNORECASE,
    ):
        host = match.group(1).lower()
        if host in skip or any(host.endswith("." + s) for s in skip):
            continue
        stem = host.rsplit(".", 1)[0].replace("-", "")
        if tokens and any(t in stem or stem in t for t in tokens):
            return host, _window(text, match)
        if fallback is None:
            fallback = (host, _window(text, match))

    if tokens:
        # A name was supplied and nothing corroborated it. Returning the
        # first plausible host here is how a competitor's domain gets
        # attributed to the company being analysed.
        return None, ""
    if fallback:
        return fallback[0], fallback[1] + "  [UNCORROBORATED: no company name supplied]"
    return None, ""


def extract(text: str, company: str = "") -> DeckMetadata:
    """All of the above. Every value is None unless the deck actually says."""
    stage, stage_evidence = extract_stage(text)
    sector, sector_evidence = extract_sector(text)
    team_size, team_evidence = extract_team_size(text)
    github_url, github_evidence = extract_github_url(text)
    domain, domain_evidence = extract_domain(text, company)

    evidence = {}
    for name, value in (
        ("stage", stage_evidence), ("sector", sector_evidence),
        ("team_size", team_evidence), ("github_url", github_evidence),
        ("domain", domain_evidence),
    ):
        if value:
            evidence[name] = value

    return DeckMetadata(
        stage=stage, sector=sector, team_size=team_size,
        github_url=github_url, domain=domain, evidence=evidence,
    )
