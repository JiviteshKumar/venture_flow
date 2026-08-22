"""Bundled sandbox/demo deck (p4 on the Ship List — onboarding mode).

A first-time user has no pitch deck handy and no Neon data to look at.
This module ships one fictional, clearly-labeled example company so the
"Try a demo deck" button on the upload page can run the REAL pipeline
(claim verification, risk model, RAG, Groq synthesis, comparables, etc.)
end to end without requiring a file upload first.

Everything here is invented. "Solstice Robotics" is not a real company;
any resemblance to a real company of that name is coincidental. The
claims are deliberately mixed -- some should verify, some should not --
so a new user sees what a real verdict spread looks like, not a
rigged all-green demo.
"""

DEMO_COMPANY_NAME = "Solstice Robotics (Demo)"

DEMO_SAMPLE = {
    "session_id": "demo-sandbox",
    "company_name": DEMO_COMPANY_NAME,
    "company_description": (
        "Solstice Robotics builds autonomous weeding robots for small and "
        "mid-size specialty-crop farms (strawberries, lettuce, tree nuts). "
        "The robot uses computer vision to distinguish crop from weed and "
        "kills weeds mechanically, removing the need for herbicide passes. "
        "Solstice sells the hardware on a subscription (robot-as-a-service) "
        "model with a per-acre monthly fee, targeting the labor shortage and "
        "herbicide-resistance problems facing specialty-crop growers."
    ),
    "detected_claims": [
        "Solstice has signed pilot agreements with over 40 farms across California and Arizona.",
        "The robot reduces herbicide use by 90% compared to conventional spraying.",
        "Solstice raised a $14M Series A led by Bessemer Venture Partners in 2025.",
        "The founding team previously built and sold an agtech company to John Deere.",
        "Solstice is the fastest-growing agricultural robotics company in North America.",
    ],
    "extracted_text": (
        "SOLSTICE ROBOTICS -- SERIES A PITCH DECK (DEMO SAMPLE)\n\n"
        "Problem: Specialty-crop farms spend $500-800/acre/season on manual "
        "weeding labor, and that labor is increasingly unavailable. Herbicide "
        "resistance is also rising, cutting the effectiveness of chemical "
        "weed control by an estimated 15% per year in affected regions.\n\n"
        "Solution: An autonomous, solar-assisted weeding robot that uses a "
        "vision model trained on over 200,000 labeled crop/weed images to "
        "mechanically remove weeds row-by-row, with no herbicide required.\n\n"
        "Traction: Solstice has signed pilot agreements with over 40 farms "
        "across California and Arizona, covering roughly 3,200 acres. Early "
        "pilot data shows a 90% reduction in herbicide use versus conventional "
        "spraying on the same fields.\n\n"
        "Team: Founded by two engineers with backgrounds in agricultural "
        "automation and computer vision. The founding team previously built "
        "and sold an agtech company to John Deere.\n\n"
        "Funding: Solstice raised a $14M Series A led by Bessemer Venture "
        "Partners in 2025, following a $2.5M seed round.\n\n"
        "Market: Solstice is the fastest-growing agricultural robotics "
        "company in North America, addressing a specialty-crop weeding "
        "market estimated at $3.1B annually in the US alone.\n\n"
        "Financials: Current MRR is approximately $95,000 across pilot "
        "customers on the per-acre subscription model. Monthly burn is "
        "roughly $310,000, giving an estimated 14 months of runway on the "
        "current balance sheet."
    ),
    "revenue": 1_140_000.0,
    "runway_months": 14.0,
    "founders": ["Dana Whitfield", "Marcus Reyes"],
    "page_count": 11,
    "extraction_method": "demo_fixture",
}
