"""Turn a filename into something you can actually search for.

WHY THIS EXISTS

The upload form pre-fills the company name from the uploaded filename, by
stripping the extension and replacing hyphens and underscores with spaces. A
file called `02 uber.pdf` therefore became the company name **"02 uber"**, and
that string was then used verbatim as the subject of every web lookup the
product makes.

The damage, from a real run on Uber's 2008 deck:

  * Founder research searched for "the founders of 02 uber" and consulted,
    among fourteen sources, the Wikipedia articles for Delta Air Lines and
    Maximilien Robespierre. It reported that no founder could be established.
  * Claim verification scoped every query to "02 uber".
  * The comparable-company search embedded "02 uber" as the description.
  * The report, the sidebar and the PDF export all titled it "02 uber".

None of that is a search problem. The queries were well-formed; they were about
a company that does not exist.

WHAT THIS IS CAREFUL ABOUT

A cleaner that is too eager is worse than no cleaner, because it silently
renames real companies. Two rules keep it honest:

  * A leading number is removed only when it looks like a file ordinal --
    zero-padded ("02 uber", "007_deck") or separated by punctuation rather than
    a plain space ("1. uber", "3-uber"). A plain space with no leading zero is
    left alone, so **500 Startups**, **1Password** and **23andMe** survive.
  * Only whole words are stripped from the deck vocabulary, and only from the
    ends. A company genuinely called "Deck" keeps its name; "uber pitch deck
    2008 final" loses the packaging and keeps "uber".

If cleaning would empty the string, the original is returned unchanged. A
recognisable wrong name beats an empty one.
"""

from __future__ import annotations

import re

# Words that describe the FILE rather than the company. Stripped only when they
# appear as whole words at the start or end, never from the middle -- "Deck
# Technologies" must not become "Technologies".
_PACKAGING_WORDS = {
    "pitch", "deck", "pitchdeck", "presentation", "slides", "slide",
    "final", "draft", "copy", "compressed", "updated", "latest", "new",
    "confidential", "teaser", "memo", "overview", "profile", "report",
    "seed", "series", "round", "raise", "fundraise", "investor", "investors",
    "vc", "deck1", "v", "version", "rev", "public", "shared", "sample",
}

# A version or year token: v2, V1.3, 2008, 2021.
_VERSION_OR_YEAR = re.compile(r"^(?:v\.?\d+(?:\.\d+)*|(?:19|20)\d{2})$", re.IGNORECASE)

# A leading file ordinal. Zero-padded, or followed by punctuation rather than a
# plain space -- see the docstring for why a bare "500 Startups" is left alone.
_LEADING_ORDINAL = re.compile(r"^\s*(?:0\d{0,2}|\d{1,3})\s*[.\-_)\]]+\s*|^\s*0\d{0,2}\s+")

# A leading dataset index on a file that is otherwise lower-case:
# "11 tinder.pdf", "07 airbnb.pdf". Only applied once the value is already
# known to be a filename, and only when what follows starts lower-case --
# which is what separates "11 tinder" from "500 Startups" and "3 Arrows
# Capital", names a person would capitalise.
_LEADING_INDEX_LOWER = re.compile(r"^\s*\d{1,3}\s+(?=[a-z])")

_SEPARATORS = re.compile(r"[_\-–—]+")
_WHITESPACE = re.compile(r"\s+")
_TRAILING_JUNK = re.compile(r"[\s\-_.,;:()\[\]]+$")


def strip_extension(filename: str) -> str:
    """`uber.pitch.pdf` -> `uber.pitch`. Only a known-length extension goes."""
    return re.sub(r"\.[A-Za-z0-9]{1,5}$", "", (filename or "").strip())


# "Series A", "Series B" -- a funding round in a filename, not part of a name.
_SERIES_ROUND = re.compile(r"\bseries\s+[a-h]\b", re.IGNORECASE)


def _looks_like_a_file(raw: str) -> bool:
    """Whether this string came from a file rather than from a person.

    This is the gate that keeps the cleaner honest, and it was added after the
    first version mangled five real companies in test: "Final Frontier" lost
    its "Final", "Deck Technologies" lost its "Deck", "Version One" became
    "One", and 7-Eleven's hyphen turned into a space.

    Packaging words are reliable signals at the end of a FILENAME and
    meaningless in a NAME SOMEONE TYPED, so the two are treated differently:
    a filename gets cleaned, a typed name is returned as it was written. The
    three things that mark a filename are a file extension, an underscore, and
    a ZERO-PADDED leading ordinal.

    The zero-padding qualifier is doing real work. "7-Eleven" is
    indistinguishable from the ordinal in "3-intercom.pdf" by shape alone, and
    the first version turned it into "Eleven". What separates them is that the
    filename carries an extension; a bare "7-Eleven" does not. A zero-padded
    number ("02", "007") is treated as a file marker on its own, because no
    company name begins that way.
    """
    value = (raw or "").strip()
    return bool(
        re.search(r"\.[A-Za-z0-9]{1,5}$", value)
        or "_" in value
        or re.match(r"^\s*0\d{0,2}\s*[.\-_)\]\s]", value)
    )


def clean(raw: str) -> str:
    """A searchable company name, from a filename or a typed value.

    Never raises. Returns the input unchanged if it does not look like a
    filename, or if cleaning would leave nothing -- a recognisable wrong name is
    more useful than an empty one, and far more correctable by the user, who
    sees this in an editable field.
    """
    original = (raw or "").strip()
    if not original:
        return ""

    # A name someone typed is theirs. Only whitespace is tidied.
    if not _looks_like_a_file(original):
        return _WHITESPACE.sub(" ", original).strip()

    name = strip_extension(original)
    name = _LEADING_ORDINAL.sub("", name)
    name = _LEADING_INDEX_LOWER.sub("", name)
    name = _SEPARATORS.sub(" ", name)
    name = _SERIES_ROUND.sub(" ", name)
    name = _WHITESPACE.sub(" ", name).strip()
    if not name:
        return original

    # Strip packaging words from both ends, repeatedly: "uber pitch deck 2008
    # final" -> "uber". Only from the ends, so an interior word is safe.
    words = name.split(" ")

    def is_packaging(word: str) -> bool:
        bare = word.strip(".,()[]").lower()
        return bool(bare) and (bare in _PACKAGING_WORDS or bool(_VERSION_OR_YEAR.match(bare)))

    while len(words) > 1 and is_packaging(words[-1]):
        words.pop()
    while len(words) > 1 and is_packaging(words[0]):
        words.pop(0)

    name = _TRAILING_JUNK.sub("", " ".join(words)).strip()
    if not name:
        return original

    return _capitalise(name)


def _capitalise(name: str) -> str:
    """Title-case only what looks like it was never capitalised.

    A name the user typed, or one already carrying internal capitals, is left
    exactly as it is: "iRobot", "eBay", "OpenAI" and "3M" must survive, and any
    scheme clever enough to re-case them is clever enough to ruin them.
    """
    if any(character.isupper() for character in name):
        return name
    return " ".join(
        word[:1].upper() + word[1:] if word else word
        for word in name.split(" ")
    )


def looks_like_a_filename(raw: str) -> bool:
    """Whether `raw` still looks like a file rather than a company.

    Used to decide whether to say so in the UI. Deliberately narrow: it reports
    only the two shapes actually seen in uploads -- a surviving extension, and a
    leading ordinal.
    """
    value = (raw or "").strip()
    if not value:
        return False
    return bool(
        re.search(r"\.(pdf|pptx?|docx?|txt|md|key|pages)$", value, re.IGNORECASE)
        or _LEADING_ORDINAL.match(value)
    )
