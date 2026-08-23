"""Assemble the hand-labeled risk-detection benchmark.

Takes the raw excerpts retrieved by `collect_risk_excerpts.py`, keeps the ones
selected by hand, attaches the hand-assigned labels below, adds six
pitch-deck-register paragraphs (the product's actual input format, which SEC
filings do not cover), and writes `ml/eval/risk_benchmark.jsonl`.

**Every label in LABELS was assigned by reading the excerpt.** The retrieval
bucket in the raw file is not used as a label and does not always agree with
one: `bam_restatement` was retrieved by a red-flag query and is labeled a
genuine (MEDIUM) risk only because the paragraph discloses a real prior
restatement, while several excerpts retrieved by boilerplate queries are
saturated with risk vocabulary and are labeled risk-free precisely because
saying "could have a material adverse effect" about the weather is not a red
flag. Those disagreements are the point of the benchmark.

Label schema per example:
    id            stable identifier
    text          the excerpt as retrieved (SEC) or written (pitch deck)
    source        provenance -- filer + form + date, or "pitch_deck_register"
    url           EDGAR URL for SEC excerpts, empty for written ones
    subset        "red_flag" | "boilerplate"
    gold_risk     true if a competent analyst should flag this excerpt
    gold_categories  subset of the five categories agents/risk_detector.py uses
    gold_severity "NONE" | "LOW" | "MEDIUM" | "HIGH"
    rationale     one line on why this label, so a reviewer can disagree with
                  a specific judgement rather than the whole file

    python ml/scripts/build_risk_benchmark.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import console_safety  # noqa: E402,F401  (imported for side effect)

RAW_PATH = ROOT / "ml" / "eval" / "risk_excerpts_raw.jsonl"
OUT_PATH = ROOT / "ml" / "eval" / "risk_benchmark.jsonl"

# Trailing XBRL/inline-viewer debris that survives text extraction on older
# filings. Stripped so the label describes the prose, not the tag soup.
XBRL_TAIL = re.compile(
    r"(?:\s(?:false|true|na|UnKnown|nonnum:\S+|xbrli:\S+|us-gaap_\S+|duration|Sheet\s+http\S+)\b)+\s*$",
    re.IGNORECASE,
)

# (raw-file index, id, subset, gold_risk, categories, severity, rationale)
LABELS: list[tuple[int, str, str, bool, list[str], str, str]] = [
    # ---------------- genuine red flags, real SEC filings ----------------
    (0, "sec_going_concern_usprecious", "red_flag", True,
     ["financial_risk", "legal_risk"], "HIGH",
     "Explicit going-concern doubt plus an unpaid arbitration award and convertible notes the company states it cannot fund."),
    (2, "sec_going_concern_salamon", "red_flag", True,
     ["financial_risk"], "HIGH",
     "Auditor-reported recurring losses, working capital deficit and explicit going-concern doubt, with no revenue."),
    (3, "sec_material_weakness_meridian", "red_flag", True,
     ["financial_risk", "management_risk"], "HIGH",
     "Company discloses an identified material weakness in internal control over financial reporting."),
    (4, "sec_material_weakness_vividseats", "red_flag", True,
     ["financial_risk", "management_risk"], "HIGH",
     "Disclosure controls concluded not effective; material weakness in segregation of duties and finance staffing."),
    (6, "sec_sec_subpoena_lvs", "red_flag", True,
     ["legal_risk"], "HIGH",
     "SEC subpoena over FCPA compliance plus a parallel DOJ investigation and a wrongful-termination suit by a former executive."),
    (7, "sec_subpoena_restatement_cpiaero", "red_flag", True,
     ["legal_risk", "financial_risk"], "HIGH",
     "SEC enforcement subpoena tied to a restatement, non-reliance periods and CFO separations; investigation later closed but the underlying restatement is disclosed."),
    (8, "sec_wells_notice_competitivetech", "red_flag", True,
     ["legal_risk"], "HIGH",
     "SEC investigation into trading in the company's own securities, escalated to Wells Notices against the company and named officers."),
    (9, "sec_restatement_maxwell", "red_flag", True,
     ["financial_risk"], "HIGH",
     "Restatement of previously issued financials that cost the company the effectiveness of its S-3 shelf registration."),
    (10, "sec_restatement_bam", "red_flag", True,
     ["financial_risk"], "MEDIUM",
     "Hard case: discloses a real prior restatement but concludes controls were effective and the adjustments were non-cash. A prior restatement is still material to diligence, so genuine but MEDIUM, not HIGH."),
    (11, "sec_covenant_breach_ameri", "red_flag", True,
     ["financial_risk"], "HIGH",
     "Currently out of compliance with loan covenants, surviving on paid quarterly waivers the company says it does not expect to continue."),
    (13, "sec_covenant_default_zynex", "red_flag", True,
     ["financial_risk"], "HIGH",
     "Covenant non-compliance where the lender has already accelerated repayment and exercised default remedies."),
    (14, "sec_cfo_resignation_littlefield", "red_flag", True,
     ["management_risk"], "MEDIUM",
     "CFO resigned effective immediately. Abrupt CFO exit is a standard diligence flag; MEDIUM because the filing gives no cause and a transition period is offered."),

    # ---------------- risk-free boilerplate, real SEC filings ----------------
    # Chosen because they are saturated with the exact vocabulary a keyword
    # detector keys on. If a detector cannot stay quiet here it cannot be used.
    (16, "sec_safe_harbor_meridian", "boilerplate", False, [], "NONE",
     "Private Securities Litigation Reform Act safe-harbour paragraph. Present verbatim in essentially every 10-K; carries no company-specific information."),
    (18, "sec_riskfactor_summary_budajuice", "boilerplate", False, [], "NONE",
     "Generic risk-factor summary bullets (growth management, key employees, additional capital, climate, public-company costs). Hypothetical and universal, not a disclosed event."),
    (19, "sec_additional_capital_lotterydotcom", "boilerplate", False, [], "NONE",
     "Standard 'we may require additional capital' growth risk factor. The filer later had genuine problems, but nothing in this paragraph discloses one."),
    (21, "sec_critical_audit_matter_endeavor", "boilerplate", False, [], "NONE",
     "Hard negative: a critical audit matter on multi-element revenue recognition. Sounds alarming and is routine -- CAMs are required commentary, not findings of wrongdoing."),
    (22, "sec_asc606_policy_solarcapital", "boilerplate", False, [], "NONE",
     "ASC 606 revenue-recognition accounting policy note. Pure accounting description."),
    (23, "sec_asc606_policy_chicagorivet", "boilerplate", False, [], "NONE",
     "ASC 606 adoption note stating the adoption had no cumulative retained-earnings effect."),
    (28, "sec_8k_item202_chubb", "boilerplate", False, [], "NONE",
     "Form 8-K furnishing a quarterly earnings press release under Item 2.02. A scheduled administrative filing."),
    (30, "sec_8k_board_appointment_skyway", "boilerplate", False, [], "NONE",
     "Routine Item 5.02 board appointments. Governance activity, not a governance failure."),
    (33, "sec_econ_conditions_ranger", "boilerplate", False, [], "NONE",
     "Hard negative: macro/commodity risk factor listing recession, weather, and geopolitics. Every energy-services filer carries it."),
    (34, "sec_competition_rentrak", "boilerplate", False, [], "NONE",
     "Hard negative: 'we face intense competition' risk factor. Contains competitive-pressure language a keyword detector fires on, with no adverse event disclosed."),
]

# Six paragraphs in the register VentureFlow actually receives. SEC filings
# cover none of this: pitch decks assert rather than disclose, and the risky
# ones are risky by what they quietly admit, not by legal vocabulary. Written
# for this benchmark, not retrieved -- flagged as such in `source` so nobody
# reads them as filings.
DECK_EXAMPLES: list[dict] = [
    {
        "id": "deck_customer_concentration",
        "subset": "red_flag", "gold_risk": True,
        "gold_categories": ["operational_risk", "financial_risk"],
        "gold_severity": "HIGH",
        "rationale": "One customer is 78% of revenue on a contract renewing in four months with no signed renewal -- textbook customer concentration.",
        "text": (
            "Traction. We closed $2.4M in ARR this year, up from $310K. Our anchor customer, a national "
            "logistics operator, represents $1.9M of that figure and their master services agreement comes "
            "up for renewal in four months. We have not yet started renewal discussions because the account "
            "team is focused on the current deployment. The remaining $500K is spread across nine mid-market "
            "accounts, four of which are still in a discounted pilot tier."
        ),
    },
    {
        "id": "deck_runway_crunch",
        "subset": "red_flag", "gold_risk": True,
        "gold_categories": ["financial_risk"],
        "gold_severity": "HIGH",
        "rationale": "Under three months of runway with a raise not yet started; the deck states burn exceeds revenue by an order of magnitude.",
        "text": (
            "Financials. Monthly burn is currently $410K against $38K in monthly recognised revenue. Cash on "
            "hand at the end of last month was $1.1M. We are raising a $6M Series A to extend runway and "
            "have not yet opened a data room or begun partner meetings. Our plan assumes the round closes "
            "within the quarter; if it slips we would reduce headcount in engineering and customer success."
        ),
    },
    {
        "id": "deck_founder_departure_ip",
        "subset": "red_flag", "gold_risk": True,
        "gold_categories": ["management_risk", "legal_risk"],
        "gold_severity": "HIGH",
        "rationale": "Technical co-founder left, holds unvested-but-disputed equity, and assignment of the core algorithm's IP is unresolved.",
        "text": (
            "Team. Our founding CTO left the company in March to return to academia. He wrote the original "
            "matching algorithm during his postdoc and the assignment agreement covering that work is still "
            "being negotiated with his former university's technology transfer office. He retains 14% of the "
            "company on an accelerated schedule that the remaining founders are disputing. We are actively "
            "recruiting a replacement and one of our senior engineers is acting as interim technical lead."
        ),
    },
    {
        "id": "deck_product_description",
        "subset": "boilerplate", "gold_risk": False,
        "gold_categories": [], "gold_severity": "NONE",
        "rationale": "A plain product description. No adverse fact disclosed and nothing for a risk detector to flag.",
        "text": (
            "Product. Our platform ingests warehouse management system events and produces a live picking "
            "plan for floor staff. Customers connect through a read-only API key; no changes to the "
            "underlying WMS are required. The plan updates every thirty seconds and is delivered to handheld "
            "scanners the operator already owns. Deployment takes two weeks and is handled by our solutions "
            "team with one part-time contact on the customer side."
        ),
    },
    {
        "id": "deck_market_sizing",
        "subset": "boilerplate", "gold_risk": False,
        "gold_categories": [], "gold_severity": "NONE",
        "rationale": "A standard market-sizing slide. The numbers are unverified founder claims -- a job for claim verification, not risk detection -- and unverified is not the same as risky.",
        "text": (
            "Market. Third-party analysts size the warehouse execution software market at $4.1B today, "
            "growing to $9.8B by 2030. We define our serviceable market as mid-market third-party logistics "
            "operators in North America and Western Europe running between two and twenty facilities, which "
            "we estimate at 11,400 companies. At our current average contract value of $46K that is a $525M "
            "serviceable addressable market."
        ),
    },
    {
        "id": "deck_team_slide",
        "subset": "boilerplate", "gold_risk": False,
        "gold_categories": [], "gold_severity": "NONE",
        "rationale": "An ordinary team slide with intact founders and relevant backgrounds. Hard negative only in that it mentions a previous company shutting down, which is not itself a risk signal about this company.",
        "text": (
            "Team. Our CEO spent six years in operations at a national grocery distributor and led the "
            "rollout of its first automated fulfilment centre. Our CTO previously built routing "
            "infrastructure at a delivery startup that wound down in 2021 after its parent company was "
            "acquired. We are eleven people: six engineers, two on customer success, two on sales and one "
            "operations lead. All four early employees are still with the company."
        ),
    },
]


def main() -> None:
    raw = [json.loads(line) for line in RAW_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]

    rows: list[dict] = []
    for index, example_id, subset, gold_risk, categories, severity, rationale in LABELS:
        source_row = raw[index]
        text = XBRL_TAIL.sub("", source_row["text"]).strip()
        rows.append({
            "id": example_id,
            "text": text,
            "source": f"{source_row['company'].strip()} | {source_row['form']} | {source_row['file_date']}",
            "url": source_row["url"],
            "subset": subset,
            "gold_risk": gold_risk,
            "gold_categories": categories,
            "gold_severity": severity,
            "rationale": rationale,
        })

    for deck in DECK_EXAMPLES:
        rows.append({
            "id": deck["id"],
            "text": deck["text"],
            "source": "pitch_deck_register (written for this benchmark, not a filing)",
            "url": "",
            "subset": deck["subset"],
            "gold_risk": deck["gold_risk"],
            "gold_categories": deck["gold_categories"],
            "gold_severity": deck["gold_severity"],
            "rationale": deck["rationale"],
        })

    OUT_PATH.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    positives = sum(1 for r in rows if r["gold_risk"])
    print(f"Wrote {len(rows)} labeled examples to {OUT_PATH}")
    print(f"  {positives} genuine red flags / {len(rows) - positives} risk-free boilerplate")


if __name__ == "__main__":
    main()
