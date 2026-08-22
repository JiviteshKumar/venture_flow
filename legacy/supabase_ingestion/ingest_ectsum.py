from dotenv import load_dotenv
load_dotenv()

import os, json, csv, uuid
from base import batch_upsert, chunked, upload_to_storage

def find_data_files(path, extensions):
    found = []
    for root, dirs, files in os.walk(path):
        for f in files:
            if any(f.endswith(ext) for ext in extensions):
                found.append(os.path.join(root, f))
    return found

def ingest_ectsum(base_path: str):
    print("Starting ECTSum ingestion...")
    print(f"Scanning {base_path} for data files...")

    doc_rows = []
    summary_rows = []
    seen_doc_ids = set()  # prevent duplicate doc_ids within this run

    # ── Process TXT files (the 4,850 transcript files) ──────────────────────
    txt_files = find_data_files(base_path, [".txt"])
    # Filter out non-data txt files
    txt_files = [f for f in txt_files if not any(
        skip in f for skip in ["__pycache__", ".git", "LICENSE", "README"]
    )]
    print(f"Processing {len(txt_files)} TXT transcript files...")

    for filepath in txt_files:
        # Derive a unique doc_id from the full relative path
        doc_id = filepath.replace("\\", "/").replace(base_path.replace("\\", "/"), "").strip("/")
        doc_id = doc_id.replace("/", "_").replace(".txt", "")[:200]

        # Make sure it's unique
        if doc_id in seen_doc_ids:
            doc_id = doc_id + "_" + str(uuid.uuid4())[:8]
        seen_doc_ids.add(doc_id)

        # Determine split from path
        path_lower = filepath.lower()
        if "train" in path_lower:
            db_split = "train"
        elif "val" in path_lower or "dev" in path_lower:
            db_split = "dev"
        elif "test" in path_lower:
            db_split = "test"
        else:
            db_split = "train"

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().strip()
        except:
            continue

        if not content:
            continue

        doc_rows.append({
            "source": "ectsum",
            "modality": "text",
            "split": db_split,
            "doc_id": doc_id,
            "title": os.path.basename(filepath),
            "raw_text": content[:50000],
            "metadata": json.dumps({
                "original_path": filepath.replace("\\", "/"),
                "file_type": "transcript"
            }),
        })

    # ── Process JSON files ───────────────────────────────────────────────────
    json_files = find_data_files(base_path, [".json"])
    json_files = [f for f in json_files if not any(
        skip in f for skip in ["__pycache__", ".git"]
    )]
    print(f"Processing {len(json_files)} JSON files...")

    for filepath in json_files:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                item = json.load(f)
        except:
            continue

        # Build unique doc_id
        base_id = os.path.basename(filepath).replace(".json", "")
        doc_id = base_id
        if doc_id in seen_doc_ids:
            doc_id = base_id + "_" + str(uuid.uuid4())[:8]
        seen_doc_ids.add(doc_id)

        path_lower = filepath.lower()
        if "train" in path_lower:
            db_split = "train"
        elif "val" in path_lower or "dev" in path_lower:
            db_split = "dev"
        elif "test" in path_lower:
            db_split = "test"
        else:
            db_split = "train"

        transcript = str(item.get("transcript", item.get("text", item.get("body", ""))))
        gpt_summary = str(item.get("gpt_summary", item.get("summary", "")))
        human_summary = str(item.get("human_summary", ""))
        ext_summary = str(item.get("extractive_summary", ""))
        company = str(item.get("company", item.get("ticker", "")))
        ticker = str(item.get("ticker", ""))

        if not transcript and not gpt_summary:
            continue

        doc_rows.append({
            "source": "ectsum",
            "modality": "text",
            "split": db_split,
            "doc_id": doc_id,
            "title": company or doc_id,
            "raw_text": transcript[:50000],
            "metadata": json.dumps({
                "company": company,
                "ticker": ticker,
                "file_type": "json"
            }),
        })

        for stype, stext in [
            ("gpt", gpt_summary),
            ("human", human_summary),
            ("extractive", ext_summary)
        ]:
            if not stext or stext == "None":
                continue
            summary_rows.append({
                "source": "ectsum",
                "split": db_split,
                "summary_id": f"{doc_id}_{stype}_{str(uuid.uuid4())[:8]}",
                "transcript_text": transcript[:5000],
                "summary_text": stext,
                "summary_type": stype,
                "entity_tags": json.dumps([{
                    "ticker": ticker,
                    "company": company
                }]),
                "metadata": json.dumps({}),
            })

    print(f"\nTotal: {len(doc_rows)} docs, {len(summary_rows)} summaries")

    if not doc_rows:
        print("No data found — check folder structure")
        return

    print(f"Inserting documents in batches...")
    inserted = 0
    for chunk in chunked(doc_rows, 100):
        try:
            batch_upsert("documents", chunk, "source,doc_id")
            inserted += len(chunk)
            print(f"  Inserted {inserted}/{len(doc_rows)} documents...")
        except Exception as e:
            print(f"  Chunk error (skipping): {e}")

    print(f"Inserting summaries...")
    for chunk in chunked(summary_rows, 200):
        try:
            batch_upsert("summaries", chunk, None)
        except Exception as e:
            print(f"  Summary chunk error (skipping): {e}")

    print(f"ECTSum done: {len(doc_rows)} docs, {len(summary_rows)} summaries")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python ingest_ectsum.py data/ectsum")
    else:
        ingest_ectsum(sys.argv[1])
