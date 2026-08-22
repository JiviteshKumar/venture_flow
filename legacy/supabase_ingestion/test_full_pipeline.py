import requests
import os
import glob

BASE = "http://localhost:8000"

pdf_name = "CarbonCycle_Seed.pdf"

# Search everywhere common
search_locations = [
    # Current folder
    pdf_name,
    # Downloads
    os.path.join(os.path.expanduser("~"), "Downloads", pdf_name),
    # OneDrive Downloads
    os.path.join(os.path.expanduser("~"), "OneDrive", "Downloads", pdf_name),
    # Desktop
    os.path.join(os.path.expanduser("~"), "Desktop", pdf_name),
    # OneDrive Desktop
    os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", pdf_name),
    # Documents
    os.path.join(os.path.expanduser("~"), "Documents", pdf_name),
    # Venture_Flow folder
    os.path.join(os.path.expanduser("~"), "OneDrive", "Documents",
                 "Venture_Flow", pdf_name),
]

# Also do a glob search just in case
glob_results = glob.glob(
    os.path.join(os.path.expanduser("~"), "**", pdf_name),
    recursive=True
)
search_locations.extend(glob_results)

pdf_path = None
for path in search_locations:
    if os.path.exists(path):
        pdf_path = path
        print(f"Found PDF at: {pdf_path}")
        break

if not pdf_path:
    print(f"\nCould not find {pdf_name} anywhere.")
    print("Please do ONE of these:")
    print(f"  1. Copy the file to your Venture_Flow folder:")
    print(f"     copy \"%USERPROFILE%\\Downloads\\{pdf_name}\" .")
    print(f"  2. Or drag {pdf_name} into VS Code's file panel on the left")
    exit(1)

# ── Step 1: Upload PDF ────────────────────────────────────────
print("\nStep 1: Uploading CarbonCycle pitch deck...")
with open(pdf_path, "rb") as f:
    resp = requests.post(
        f"{BASE}/upload-pdf",
        files={"file": (pdf_name, f, "application/pdf")},
        data={"company_name": "CarbonCycle"}
    )

if resp.status_code != 200:
    print(f"Upload failed: {resp.status_code}")
    print(resp.text[:500])
    exit(1)

upload = resp.json()
print(f"  Pages:    {upload['page_count']}")
print(f"  Revenue:  {upload.get('revenue')}")
print(f"  Runway:   {upload.get('runway_months')} months")
print(f"  Claims detected ({len(upload['detected_claims'])}):")
for i, c in enumerate(upload['detected_claims'], 1):
    print(f"    {i}. {c[:100]}")

# ── Step 2: Full analysis ─────────────────────────────────────
print("\nStep 2: Running full due diligence (2-4 minutes)...")
resp2 = requests.post(
    f"{BASE}/analyze",
    json={
        "company_name":        "CarbonCycle",
        "company_description": upload["company_description"][:1000],
        "claims":              upload["detected_claims"],
        "filing_text":         upload["extracted_text"],
        "revenue":             upload.get("revenue"),
        "burn_rate":           None,
        "runway_months":       upload.get("runway_months"),
    },
    timeout=300
)

if resp2.status_code != 200:
    print(f"Analysis failed: {resp2.status_code}")
    print(resp2.text[:500])
    exit(1)

analysis = resp2.json()
print(f"\n{'='*50}")
print(f"SCORE:          {analysis['final_score']}/100")
print(f"RECOMMENDATION: {analysis['recommendation']}")
print(f"RISK LEVEL:     {analysis['risk_level']}")
print(f"{'='*50}")
print(f"Claims: {analysis['claims_verified']} checked | "
      f"{analysis['claims_supported']} supported | "
      f"{analysis['claims_refuted']} refuted")
print(f"\nRed flags:")
for flag in analysis.get('red_flags', []):
    print(f"  - {flag}")
print(f"\nPositive signals:")
for signal in analysis.get('positive_factors', []):
    print(f"  + {signal}")
print(f"\nAI Analysis preview:")
print(analysis['ai_analysis'][:600])

session_id = analysis['session_id']

# ── Step 3: Chatbot test ──────────────────────────────────────
print(f"\n{'='*50}")
print("Step 3: Chatbot test")
print(f"{'='*50}")

questions = [
    "What is the cost per tonne of CO2 removal?",
    "Who are the founders?",
    "What is the runway after the raise?",
    "What is their exit strategy?",       # Not in doc → should say no data
    "What is the company churn rate?",    # Not in doc → should say no data
]

for q in questions:
    r = requests.post(
        f"{BASE}/chat",
        json={"session_id": session_id, "question": q},
        timeout=60
    ).json()

    icon = "ANSWERED" if r['has_data'] else "NO DATA"
    print(f"\n[{icon}] {q}")
    print(f"  {r['answer'][:180]}")
    print(f"  Confidence: {r['confidence']:.0%}")

print(f"\nDone. Session ID: {session_id}")