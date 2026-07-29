import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import re
import pdfplumber
import io

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract all text from a PDF file."""
    text_parts = []
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text.strip())
    except Exception as e:
        print(f"PDF extraction error: {e}")
    return "\n".join(text_parts)

def clean_sentence(s: str) -> str:
    """Clean up extracted PDF sentences."""
    # Remove newlines within sentence
    s = re.sub(r'\n+', ' ', s)
    # Remove multiple spaces
    s = re.sub(r' {2,}', ' ', s)
    # Remove leading bullets, dashes, dots
    s = re.sub(r'^[\s\-\•\*\·]+', '', s)
    return s.strip()

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
    if not has_fact:
        return False

    # Must have a verb (real sentence, not just a label)
    verbs = r'\b(is|are|was|were|has|have|had|will|does|do|can|provides|offers|delivers|achieves|uses|reduces|increases|generates|processes|serves|operates|raised|cleared|approved)\b'
    if not re.search(verbs, s, re.IGNORECASE):
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

    # Also split on newlines that look like sentence boundaries
    expanded = []
    for sent in sentences:
        # Split on newlines if the result looks like multiple sentences
        parts = re.split(r'\n(?=[A-Z])', sent)
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

    return unique_claims[:5]

def extract_company_info(text: str) -> dict:
    info = {
        "description":   "",
        "revenue":       None,
        "burn_rate":     None,
        "runway_months": None,
    }

    clean_text          = re.sub(r'\n{3,}', '\n\n', text)
    info["description"] = clean_text[:1200].strip()

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
            except:
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
            except:
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
            except:
                pass

    return info