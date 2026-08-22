"""
Make stdout/stderr survive non-ASCII output on Windows.

This exists because of a production outage, and the failure mode is worth
spelling out because it is invisible until it isn't.

On Windows, `sys.stdout` defaults to the ANSI codepage (cp1252 on this
machine), not UTF-8. The analysis pipeline prints progress diagnostics as it
runs -- claim reasoning, risk headers, agent status -- and that text routinely
contains characters cp1252 cannot represent: the LLM emits typographic
punctuation (U+2011 non-breaking hyphen, U+202F narrow no-break space, curly
quotes), and several source files print emoji directly (U+1F50D in
`risk_detector.score_risk`).

A bare `print()` of any such string raises `UnicodeEncodeError`. Because those
prints sit *inside* the pipeline's working code rather than at the end of it,
the exception propagated out of the function doing real work:

    File "agents/risk_detector.py", line 164, in score_risk
        print(f"\n\U0001f50d Running risk analysis for: {company}")
    UnicodeEncodeError: 'charmap' codec can't encode character '\U0001f50d'

    File "agents/claim_verifier.py", line 221, in verify_claim
        print(f"  REASONING:    {result['reasoning']}")
    UnicodeEncodeError: 'charmap' codec can't encode character '‑'

So risk analysis failed 100% of the time on Windows -- the emoji is a hardcoded
literal, so it never had a chance -- and individual claim verifications failed
whenever the model happened to use a typographic character in its reasoning.
Both are caught by the pipeline's try/except blocks and degrade to
`available: false`, which is why the app kept "working" while producing
reports with no risk assessment and missing claim results. A debug print was
silently deleting the product's actual output.

Reconfiguring the streams once, at import, fixes all 58 print sites at once and
every one added later, which is the property that matters -- fixing the three
known call sites individually would leave the next one to be found in
production. `errors="replace"` means an unrepresentable character degrades to
a replacement glyph in the console instead of taking down an analysis.
"""

from __future__ import annotations

import sys


def configure_streams() -> None:
    """Force UTF-8 with replacement on stdout/stderr, best-effort.

    Wrapped in try/except per stream because this must never be the thing that
    breaks startup: under pytest capture, or when the process is launched with
    stdout replaced by something that is not a reconfigurable TextIOWrapper,
    `reconfigure` is either absent or raises. In those environments the
    original stream is already handling encoding, so skipping is correct.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - never break startup over console setup
            pass


configure_streams()
