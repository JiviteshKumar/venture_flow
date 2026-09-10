import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import io
import re

import pdfplumber

# --- Multi-column layout handling -------------------------------------------
#
# `page.extract_text()` reads a page in raster order: everything at the same
# vertical position, left to right, regardless of which column it belongs to.
# On a single-column document that is correct. On a pitch deck it is not, and
# pitch decks are what this product receives. Measured on RouteIQ.pdf, one of
# the twenty real decks in the test set, the three-column problem slide came
# out as:
#
#     Fuel waste Missed windows Manual dispatch
#     Dispatchers manually re-route drivers,
#     Static routing plans waste 12-18% of fuel Traffic and weather ...
#     reacting to disruptions instead of
#     costs on inefficient last-mile paths. deliveries to miss ...
#     predicting them.
#
# Three separate problem statements shredded into six lines, none of which is
# a sentence any of the three authors wrote. The pricing slide was worse: it
# interleaved the tier names, prices and vehicle limits so that "$28/vehicle/mo"
# lands next to "Up to 500 vehicles" when the deck says 50 -- a wrong number
# presented as a quoted fact, which is the failure mode this whole product
# exists to prevent. FIELD_NOTES.md has carried this as a known unfixed defect
# since the first pass.
#
# The fix reconstructs columns from word geometry before reading. It is
# deliberately conservative: anything it is not confident about falls through
# to `page.extract_text()`, because a wrong reordering is worse than the
# known-imperfect default.

GUTTER_MIN_RATIO = 0.035     # a gap must be >= 3.5% of page width to be a gutter
MIN_COLUMN_WORD_SHARE = 0.10  # a column holding <10% of the page's words isn't one
LINE_TOLERANCE_PT = 3.0       # words within this vertical distance are one line
MIN_WORDS_FOR_COLUMN_DETECTION = 12


def _detect_column_bounds(words: list, page_width: float) -> list:
    """Find vertical gutters and return [(x_start, x_end), ...] column ranges.

    Returns a single full-width range when the page is not multi-column. The
    gutter has to be *completely* empty across the full page height, which is
    why full-width headings are handled separately by the caller rather than
    being allowed to veto column detection here.
    """
    if page_width <= 0:
        return [(0.0, page_width)]

    bin_count = 200
    bin_width = page_width / bin_count
    occupied = [False] * bin_count
    for word in words:
        start = max(0, min(bin_count - 1, int(word["x0"] / bin_width)))
        end = max(0, min(bin_count - 1, int(word["x1"] / bin_width)))
        for index in range(start, end + 1):
            occupied[index] = True

    # Maximal runs of empty bins that do not touch either page edge; a wide
    # left or right margin is not a gutter.
    gaps = []
    run_start = None
    for index, is_occupied in enumerate(occupied):
        if not is_occupied and run_start is None:
            run_start = index
        elif is_occupied and run_start is not None:
            gaps.append((run_start, index - 1))
            run_start = None
    if run_start is not None:
        gaps.append((run_start, bin_count - 1))

    min_gap_bins = max(1, int(GUTTER_MIN_RATIO * bin_count))
    splits = [
        ((start + end + 1) / 2) * bin_width
        for start, end in gaps
        if start > 0 and end < bin_count - 1 and (end - start + 1) >= min_gap_bins
    ]
    if not splits:
        return [(0.0, page_width)]

    edges = [0.0, *splits, page_width]
    columns = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]

    # Drop slivers: a "column" holding almost nothing is decoration (a rule, a
    # page number, a bullet glyph) and merging it back avoids splitting real
    # text away from its own heading.
    threshold = MIN_COLUMN_WORD_SHARE * len(words)
    kept = []
    for low, high in columns:
        count = sum(1 for w in words if low <= (w["x0"] + w["x1"]) / 2 < high)
        if count >= threshold:
            kept.append((low, high))
    if len(kept) < 2:
        return [(0.0, page_width)]
    # Re-expand the kept columns so they tile the page and no word is lost.
    kept[0] = (0.0, kept[0][1])
    kept[-1] = (kept[-1][0], page_width)
    return kept


def _group_lines(words: list) -> list:
    """Cluster words into visual lines, each sorted left to right."""
    lines: list[list] = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(word["top"] - lines[-1][0]["top"]) <= LINE_TOLERANCE_PT:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _column_index(word: dict, columns: list) -> int:
    midpoint = (word["x0"] + word["x1"]) / 2
    for index, (low, high) in enumerate(columns):
        if low <= midpoint < high:
            return index
    return len(columns) - 1


FULL_WIDTH_SPAN_RATIO = 0.50   # a line covering half the page may be full-width
FULL_WIDTH_GAP_RATIO = 0.02    # ...but only if it has no internal gap this wide


def _is_full_width_line(line: list, page_width: float) -> bool:
    """True for a line of continuous prose that runs across the whole page.

    This distinguishes a slide subtitle from a row of column headings, and it
    has to exist because otherwise a single subtitle destroys column detection
    for the entire page: the gutter histogram looks for x-ranges no word
    touches, and one sentence spanning the page touches all of them. On the
    PetVoice team slide, the line "Builders who've shipped hardware, ML, and
    pet products before" was hiding two real gutters, so the three founder
    biographies below it stayed interleaved.

    Continuity is the discriminator. A sentence has ordinary word spaces
    throughout; a row of three column headings has two large holes where the
    gutters are.
    """
    if len(line) < 2 or page_width <= 0:
        return False
    span = max(w["x1"] for w in line) - min(w["x0"] for w in line)
    if span < FULL_WIDTH_SPAN_RATIO * page_width:
        return False
    ordered = sorted(line, key=lambda w: w["x0"])
    widest_gap = max(
        (nxt["x0"] - cur["x1"] for cur, nxt in zip(ordered, ordered[1:])),
        default=0.0,
    )
    return widest_gap <= FULL_WIDTH_GAP_RATIO * page_width


def _straddles_gutter(word: dict, columns: list) -> bool:
    """True if a single word physically crosses a column boundary.

    One word cannot belong to two columns, so this is unambiguous evidence
    that the line it sits on runs the full width of the page.
    """
    return any(word["x0"] < low < word["x1"] for low, _ in columns[1:])


def _is_standalone(line: list, line_column: int, words: list, columns: list) -> bool:
    """True if nothing in any other column shares this line's vertical band.

    This is what separates a slide title from a column body line, and it has
    to be measured on real top/bottom extents rather than on the line-grouping
    tolerance. Adjacent columns rarely share a baseline -- on the RouteIQ
    problem slide the third column sits 9pt above the other two -- so a rule
    based on "did these words group into the same line" calls every column
    line a standalone title and reorders nothing.
    """
    top = min(w["top"] for w in line)
    bottom = max(w["bottom"] for w in line)
    return not any(
        _column_index(word, columns) != line_column
        and word["top"] < bottom
        and word["bottom"] > top
        for word in words
    )


def extract_page_text(page) -> str:
    """Read one page in human reading order, columns included.

    Full-width lines (slide titles, footers, anything spanning more than one
    column) are emitted in place, and the runs of single-column lines between
    them are read column by column. That ordering is what makes a three-column
    problem slide come back as three intact statements instead of six
    interleaved fragments.
    """
    try:
        words = page.extract_words()
    except Exception:
        return page.extract_text() or ""

    if len(words) < MIN_WORDS_FOR_COLUMN_DETECTION:
        return page.extract_text() or ""

    page_width = float(page.width or 0)
    lines = _group_lines(words)

    # Gutters are looked for in the body text only. Full-width prose lines are
    # excluded from the histogram because they bridge every gutter on the page
    # and would otherwise veto column detection outright -- see
    # _is_full_width_line.
    full_width = {id(line) for line in lines if _is_full_width_line(line, page_width)}
    body_words = [w for line in lines if id(line) not in full_width for w in line]
    columns = _detect_column_bounds(body_words or words, page_width)
    if len(columns) < 2:
        return page.extract_text() or ""

    output: list[str] = []
    block: list[tuple[int, list]] = []   # (column index, line)

    def flush_block() -> None:
        if not block:
            return
        for column in range(len(columns)):
            for _, line in [item for item in block if item[0] == column]:
                output.append(" ".join(w["text"] for w in line))
        block.clear()

    # A page can hold more than one independent multi-column group -- a metrics
    # row, then a paragraph, then a footer. Merging them into a single block
    # would read all of group one's columns before any of group two's. A large
    # vertical gap is the signal that one group has ended; it is also what
    # keeps a page footer at the foot of the page instead of in the middle of
    # the body.
    heights = sorted(w["bottom"] - w["top"] for w in words)
    median_height = heights[len(heights) // 2] or 1.0
    block_break_gap = 2.5 * median_height
    previous_bottom: float | None = None

    multi_column_block_seen = False
    for line in lines:
        line_top = min(w["top"] for w in line)
        if previous_bottom is not None and (line_top - previous_bottom) > block_break_gap:
            flush_block()
        previous_bottom = max(w["bottom"] for w in line)

        if id(line) in full_width or any(_straddles_gutter(word, columns) for word in line):
            # Continuous prose across the page, or a single word physically
            # crossing a gutter. Either way the line belongs to no column.
            flush_block()
            output.append(" ".join(w["text"] for w in line))
            continue

        indices = {_column_index(word, columns) for word in line}
        if len(indices) == 1:
            column = next(iter(indices))
            if _is_standalone(line, column, words, columns):
                # A title or footer sitting alone on its row. Keep it in place;
                # folding it into a column would move a slide heading below the
                # body text it introduces.
                flush_block()
                output.append(" ".join(w["text"] for w in line))
                continue
            block.append((column, line))
        else:
            # Words from several columns sharing a baseline -- three parallel
            # sub-headings, a row of metrics, a pricing table row. Split the
            # line at the gutters and file each fragment with its own column,
            # which is what puts "Missed windows" back above the sentence that
            # explains it.
            for column in sorted(indices):
                segment = [w for w in line if _column_index(w, columns) == column]
                block.append((column, segment))
        if len({item[0] for item in block}) > 1:
            multi_column_block_seen = True
    flush_block()

    if not multi_column_block_seen:
        # Every line sat in the same column, so the "gutter" was just a wide
        # margin. Nothing was gained and the default reader is better tested.
        return page.extract_text() or ""

    return "\n".join(part for part in output if part.strip())


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract all text from a PDF file, in reading order on multi-column pages."""
    text_parts = []
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                text = extract_page_text(page)
                if text:
                    text_parts.append(text.strip())
    except Exception as e:
        print(f"PDF extraction error: {e}")
    return "\n".join(text_parts)

def extract_pages_from_pdf(file_bytes: bytes) -> list:
    """Same extraction as `extract_text_from_pdf`, kept per page.

    Exists for `extraction_coverage`, which reports how much of the deck
    reached a structured field. Slide boundaries are what make that number
    mean something: the failure this measures is whole slides being dropped
    in silence, and a metric computed over one joined blob cannot say which
    slide went missing. Everything here delegates to the same
    `extract_page_text` the joined version uses, so the two can never drift.
    """
    pages = []
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                pages.append((extract_page_text(page) or "").strip())
    except Exception as e:
        print(f"PDF page extraction error: {e}")
    return pages


def clean_sentence(s: str) -> str:
    """Clean up extracted PDF sentences."""
    # Remove newlines within sentence
    s = re.sub(r'\n+', ' ', s)
    # Remove multiple spaces
    s = re.sub(r' {2,}', ' ', s)
    # Remove leading bullets, dashes, dots
    s = re.sub(r'^[\s\-\•\*\·]+', '', s)
    return s.strip()

def _looks_like_a_heading(s: str) -> bool:
    """A slide heading rather than a claim, decided by shape, not wording.

    This replaces the closed verb list that used to serve the same purpose and
    did it by rejecting most real deck content. Headings are short and have few
    words; the test never consults a vocabulary of expected slide names, which
    is the property that makes it survive a deck calling its solution slide
    "1-Click Car Service" or "Key Differentiators".
    """
    words = s.split()
    if len(words) <= 4 and len(s) < 42:
        return True
    # "Business Model" / "Progress To Date": title-cased and short.
    if len(words) <= 5 and s == s.title():
        return True
    return False


def is_good_claim(sentence: str) -> bool:
    """
    A good claim must:
    - Be a complete sentence (not just a title or label)
    - Contain a verifiable fact (number, percentage, superlative)
    - Be between 20 and 250 characters
    - Not be a section header or navigation item
    - Have a subject and predicate structure
    """
    s = sentence.strip()

    # Length check
    if len(s) < 25 or len(s) > 280:
        return False

    # Must contain a letter
    if not re.search(r'[a-zA-Z]', s):
        return False

    # Skip things that look like headers (no verb, title case, short)
    if len(s) < 50 and s == s.title():
        return False

    # Must contain a verifiable fact indicator
    fact_patterns = [
        r'\$[\d,]+',                         # dollar amounts
        r'\d+\s*%',                          # percentages
        r'\d+[KMBx]\b',                      # K/M/B/x multipliers
        r'\b\d{1,3}(,\d{3})+\b',            # large numbers with commas
        r'\b(million|billion|trillion)\b',   # magnitude words
        r'\b(first|only|largest|fastest|cheapest|best|leading)\b',  # superlatives
        r'\b(customers|users|clients|hospitals|agencies)\b',         # customer counts
        r'\b(ARR|MRR|revenue|valuation|funded|raised)\b',           # financial terms
        r'\b(patent|FDA|approved|cleared|certified|authorized)\b',  # validation
        r'\b(grew|growth|increased|doubled|tripled|reduced)\b',     # growth claims
        r'\b(deployed|operating|processing|serving)\b',             # operational claims
    ]
    has_fact = any(re.search(p, s, re.IGNORECASE) for p in fact_patterns)

    # A deck bullet that names no dollar figure is still a claim: "Not hailed
    # from street, so no medallion licenses are required" is checkable and
    # material. Substance is measured as length plus word count rather than by
    # matching a keyword list, for the same reason the verb list had to go --
    # any fixed vocabulary silently drops whatever it did not anticipate.
    is_substantive = len(s.split()) >= 6 and len(s) >= 35
    if not (has_fact or is_substantive):
        return False

    # NO closed verb list here, deliberately.
    #
    # There used to be one: a claim had to contain a finite verb drawn from a
    # 24-word list. It is the single filter that did the most damage, because
    # pitch decks are written in noun phrases. Measured on the real 2008 UberCab
    # deck, it is what dropped every one of these:
    #
    #   "U.S. taxi & limousine industry sized at roughly $4.2B annually"
    #   "Revenue model: percentage cut of every fare (roughly 80/20 split)"
    #   "Membership-only clientele - vetted, professional users"
    #
    # -- all of which carry a fact indicator and all of which a partner would
    # call a claim. What survived was two restatements of the same $200K raise,
    # because "Raised $200K" happens to contain "raised". The report then said
    # "insufficient data" about a deck that was full of it.
    #
    # A label is now excluded by shape rather than by vocabulary: headings are
    # short and have few words, which `_looks_like_a_heading` tests directly
    # without needing to know what any particular deck calls its slides.
    if _looks_like_a_heading(s):
        return False

    # Skip obvious navigation/formatting artifacts
    skip_patterns = [
        r'^(page|slide|section|figure|table)\s+\d',
        r'^\d+\s*$',
        r'^(confidential|proprietary)',
        r'@',           # email addresses
        r'www\.',       # URLs
        r'\|.*\|',      # table separators
    ]
    if any(re.search(p, s, re.IGNORECASE) for p in skip_patterns):
        return False

    return True

def extract_claims_from_text(text: str) -> list:
    """
    Extract only high-quality verifiable claims from pitch deck text.
    Each claim must be a complete, specific, verifiable statement.
    """
    # Split into sentences more carefully
    # Handle cases where PDF extraction runs sentences together
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)

    # Split on line breaks and on bullet glyphs.
    #
    # This used to split only on `\n(?=[A-Z])` -- a newline followed by a
    # capital letter. Deck bullets begin with "•" or "–", not with a capital,
    # so an entire slide arrived as one run-on string: heading, every bullet
    # and the slide number concatenated. Those blobs are useless as claims
    # (nobody can verify "UberCab Fleet • Premium – S550 for SF Beta clients •
    # 30mpg with S400 BlueHybrid...") and they also defeat deduplication,
    # because two slides sharing a heading fingerprint collapse into one.
    #
    # Splitting on the glyphs themselves yields one candidate per bullet, which
    # is the unit a deck actually asserts in.
    expanded = []
    for sent in sentences:
        parts = re.split(r'\n+|\s*[•▪◦‣]\s*|\s+[–—]\s+', sent)
        expanded.extend(parts)

    cleaned = [clean_sentence(s) for s in expanded]

    # Filter to good claims
    good_claims = [s for s in cleaned if is_good_claim(s)]

    # Deduplicate — keep the most specific version of similar claims
    seen_keys = set()
    unique_claims = []
    for claim in good_claims:
        # Create a fingerprint from first 40 chars
        key = re.sub(r'\W+', '', claim[:40].lower())
        if key not in seen_keys:
            seen_keys.add(key)
            unique_claims.append(claim)

    # Score claims by specificity (more numbers = more verifiable)
    def specificity_score(claim):
        numbers = len(re.findall(r'\d+', claim))
        dollars = len(re.findall(r'\$', claim))
        pct     = len(re.findall(r'%', claim))
        return numbers + (dollars * 2) + (pct * 2)

    unique_claims.sort(key=specificity_score, reverse=True)

    # 12, not 5. The cap used to be set by what claim verification could afford
    # to check; it therefore also silently truncated the report's record of the
    # deck to a third of a nine-slide deck's content. Verification still checks
    # only the top few (see run_due_diligence), but what the deck SAID is no
    # longer discarded to suit what the verifier can afford to read.
    return unique_claims[:12]

# Role words that mark the line *after* a person's name on a team slide. Kept
# deliberately narrow: "Head of Hardware" and "Co-founder & CTO" are roles,
# "Field agronomy team" (from a use-of-funds slide) is not, and the whole point
# of this list is to not turn the second one into a founder.
_ROLE_PATTERN = re.compile(
    r"^\s*(?:co[-\s]?founder|founder|ceo|cto|coo|cfo|cpo|cmo|chief\s+\w+"
    r"|head\s+of\s+\w+|vp\s+of\s+\w+|president|managing\s+director)\b",
    re.IGNORECASE,
)
# A person's name as it appears on a deck: two or three capitalised words.
# Allows internal apostrophes and hyphens (O'Brien, Sanchez-Rivera).
_NAME_PATTERN = re.compile(
    r"^[A-Z][a-z'’-]+(?:\s+[A-Z][a-z'’.-]+){1,2}$"
)
_TEAM_HEADING = re.compile(r"^\s*(?:the\s+)?(?:team|founders?|leadership|who\s+we\s+are)\s*$",
                           re.IGNORECASE)
# "Melanie Perkins, Founder" / "Ada Lovelace - Co-Founder & CTO". The role half
# is still validated against _ROLE_PATTERN by the caller, so "San Francisco,
# California" and "Trips to/from restaurants, bars" do not become founders.
_INLINE_NAME_ROLE = re.compile(
    r"^([A-Z][\w'’-]+(?:\s+[A-Z][\w'’.-]+){1,2})\s*[,–—-]\s*(.{2,60})$"
)


def extract_founders(text: str, max_founders: int = 5) -> list:
    """Pull founder name / role / background triples out of a deck's team slide.

    The regex counterpart to the LLM founder extraction in
    `structured_extractor.py`, and the reason `agents/founder_verifier.py` can
    now receive input at all: the verifier has existed since the third pass and
    had never once run in production, because `DiligenceRequest.founders` was
    never populated by anything -- not the upload form, and not extraction.

    Structure, not keywords, is what makes this reliable on a deck: a founder
    entry is a capitalised name line immediately followed by a role line. That
    pairing is what a team slide looks like and what a use-of-funds bullet
    ("20% -- Field agronomy team") does not, so this returns nothing on the
    twenty decks in the test set that have no team slide, which is the correct
    answer for them.

    Returns [] on anything it is not confident about. Never raises.
    """
    try:
        lines = [line.strip() for line in text.splitlines()]
        founders: list[dict] = []
        seen: set[str] = set()
        for index, line in enumerate(lines):
            # "Melanie Perkins, Founder" -- name and role on ONE line.
            #
            # The two-line form below (name, then role beneath) is what a team
            # slide looks like, and it was the only form recognised. A title
            # slide does it differently: it sets the founder's name and title
            # together on a single line under the logo, and that is precisely
            # the deck that has no team slide for the two-line rule to find.
            # So the one case where this function was the only thing standing
            # between the report and "no founder names were submitted" was the
            # case it could not read.
            inline = _INLINE_NAME_ROLE.match(line)
            if inline:
                name, role = inline.group(1).strip(), inline.group(2).strip()
                if name.lower() not in seen and _ROLE_PATTERN.match(role):
                    seen.add(name.lower())
                    founders.append({"name": name, "role": role, "background": ""})
                    if len(founders) >= max_founders:
                        break
                continue

            if not _NAME_PATTERN.match(line):
                continue
            role_line = next(
                (lines[j] for j in range(index + 1, min(index + 3, len(lines))) if lines[j]),
                "",
            )
            if not _ROLE_PATTERN.match(role_line):
                continue
            if line.lower() in seen:
                continue
            seen.add(line.lower())
            # Background is the prose that follows the role line, up to the
            # next name or a blank run -- it is what the verifier cross-checks
            # against public evidence, so an empty one is fine but a wrong one
            # is not.
            background: list[str] = []
            cursor = index + 1
            while cursor < len(lines) and lines[cursor] != role_line:
                cursor += 1
            for follower in lines[cursor + 1: cursor + 6]:
                if not follower or _NAME_PATTERN.match(follower) or _ROLE_PATTERN.match(follower):
                    break
                # Decks set slide headings in caps and rarely leave a blank
                # line before the next slide, so without this the last
                # founder's biography swallows "THE ASK Raising a $1.2M seed
                # round" and the verifier is asked to corroborate it.
                if len(follower) > 3 and follower.upper() == follower:
                    break
                background.append(follower)
            founders.append({
                "name": line,
                "role": role_line,
                "background": " ".join(background).strip(),
            })
            if len(founders) >= max_founders:
                break
        return founders
    except Exception as exc:
        print(f"Founder extraction error: {exc}")
        return []


def extract_company_info(text: str) -> dict:
    info = {
        "description":   "",
        "revenue":       None,
        "burn_rate":     None,
        "runway_months": None,
    }

    clean_text          = re.sub(r'\n{3,}', '\n\n', text)
    # 1,200 characters is a PROMPT budget, not a description of the deck, and
    # it was silently doing duty as both. `desc_len` is a real feature of the
    # score model, so capping here made it a near-constant 1199/1200 for every
    # deck long enough to hit the cap -- measured across seven real decks, six
    # of the seven reported 1199 or 1200, destroying the one text-shape signal a
    # deck reliably supplies.
    #
    # The cap stays on `description` because downstream prompts depend on it.
    # `description_full` carries the untruncated text for consumers that want
    # the real length.
    info["description"] = clean_text[:1200].strip()
    info["description_full"] = clean_text.strip()

    # Revenue — requires explicit label + number >= $1,000
    revenue_patterns = [
        # Pitch-deck key-metric rows put values above their labels.
        r'\$\s*([\d,]+\.?\d*)\s*(M|B|K|million|billion|thousand)[^\n]{0,80}\n\s*(?:Annual\s+)?(?:ARR|MRR|Revenue)\b',
        # Require an explicit revenue label: otherwise a raise/valuation is easily mistaken for revenue.
        r'\$\s*([\d,]+\.?\d*)\s*(M|B|K|million|billion|thousand)\s*(?:Annual\s+)?(?:ARR|MRR|revenue)\b',
        r'(?:ARR|MRR|Annual Recurring Revenue|Annual Revenue|Revenue)[^\d$]{0,20}\$\s*([\d,]+\.?\d*)\s*(M|B|K|million|billion|thousand)',
        r'(?:revenue|ARR|MRR)[^\d$]{0,20}\$?\s*(\d{1,3}(?:,\d{3}){1,})',
    ]
    for pattern in revenue_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                groups = [g for g in match.groups() if g is not None]
                num    = float(groups[0].replace(",", ""))
                mult   = groups[1].strip().upper() if len(groups) > 1 else ""
                if mult in ["M", "MILLION"]:    num *= 1_000_000
                elif mult in ["B", "BILLION"]:  num *= 1_000_000_000
                elif mult in ["K", "THOUSAND"]: num *= 1_000
                # Must be at least $1,000 to count as revenue
                if num >= 1000:
                    info["revenue"] = num
                    break
            except Exception:
                pass

    # CarbonCycle has "$0" revenue explicitly — detect zero revenue
    if re.search(r'[Cc]urrent revenue \$0|revenue.*\$0\b|\$0.*revenue', text):
        info["revenue"] = None  # pre-revenue company

    # Burn rate
    burn_patterns = [
        r'(?:monthly burn|burn rate|monthly spend|burn)[^\d$]{0,20}\$\s*([\d,]+\.?\d*)\s*(M|B|K|million|thousand)?',
        r'\$\s*([\d,]+\.?\d*)\s*(M|K)\s*(?:monthly burn|burn|per month)',
    ]
    for pattern in burn_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                num  = float(match.group(1).replace(",", ""))
                mult = (match.group(2) or "").strip().upper()
                if mult in ["M", "MILLION"]:    num *= 1_000_000
                elif mult in ["K", "THOUSAND"]: num *= 1_000
                if num >= 1000:
                    info["burn_rate"] = num
                    break
            except Exception:
                pass

    # Runway
    runway_patterns = [
        r'(\d+)\s*(?:month|mo)s?\s*(?:of\s*)?runway',
        r'runway\s*(?:of\s*)?(\d+)\s*(?:month|mo)s?',
        r'(\d+)\s*months?\s*post.raise',
        r'runway[^\d]{0,15}(\d+)\s*months?',
    ]
    for pattern in runway_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                val = float(match.group(1))
                if 1 <= val <= 120:
                    info["runway_months"] = val
                    break
            except Exception:
                pass

    return info