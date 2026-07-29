from dotenv import load_dotenv
load_dotenv()

import os, json
from base import batch_upsert, chunked, upload_to_storage

def ingest_10k(data_path: str):
    print("Starting 10-K ingestion...")
    doc_rows = []
    sentiment_rows = []
    seen_sentences = set()  # deduplicate in memory too

    for root, dirs, files in os.walk(data_path):
        for filename in files:
            if not filename.endswith(".txt"):
                continue

            filepath = os.path.join(root, filename)
            parts = filepath.replace("\\", "/").split("/")
            company = parts[-3] if len(parts) >= 3 else "unknown"
            year = parts[-2] if len(parts) >= 2 else "unknown"
            doc_id = f"{company}_{year}_{filename}"

            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    raw_text = f.read()
            except Exception as e:
                print(f"Could not read {filepath}: {e}")
                continue

            if len(raw_text) > 500_000:
                storage_path = f"ten_k/{company}/{year}/{filename}"
                try:
                    upload_to_storage(
                        "filings-raw",
                        storage_path,
                        raw_text.encode("utf-8"),
                        "text/plain"
                    )
                    doc_rows.append({
                        "source": "ten_k",
                        "modality": "document",
                        "split": "train",
                        "doc_id": doc_id,
                        "title": filename,
                        "storage_path": storage_path,
                        "storage_bucket": "filings-raw",
                        "metadata": json.dumps({
                            "company": company,
                            "year": year,
                            "filename": filename
                        }),
                    })
                except Exception as e:
                    print(f"Storage upload failed: {e}")
            else:
                doc_rows.append({
                    "source": "ten_k",
                    "modality": "document",
                    "split": "train",
                    "doc_id": doc_id,
                    "title": filename,
                    "raw_text": raw_text[:50000],
                    "metadata": json.dumps({
                        "company": company,
                        "year": year,
                        "filename": filename
                    }),
                })

            sentences = [s.strip() for s in raw_text.split(".") if len(s.strip()) > 40]
            for sent in sentences[:50]:
                key = sent[:200]
                if key in seen_sentences:
                    continue
                seen_sentences.add(key)
                sentiment_rows.append({
                    "source": "ten_k",
                    "split": "train",
                    "text": sent[:500],
                    "label": "neutral",
                    "raw_label": "unlabeled",
                    "metadata": json.dumps({
                        "company": company,
                        "year": year,
                        "section": "body"
                    }),
                })

    print(f"Inserting {len(doc_rows)} 10-K documents...")
    for chunk in chunked(doc_rows, 100):
        batch_upsert("documents", chunk, "source,doc_id")

    print(f"Inserting {len(sentiment_rows)} risk sentences...")
    for chunk in chunked(sentiment_rows, 500):
        # ignore duplicates that already exist in DB
        try:
            batch_upsert("sentiment_records", chunk, None)
        except Exception as e:
            print(f"Skipping chunk due to duplicate: {e}")

    print(f"10-K done: {len(doc_rows)} docs, {len(sentiment_rows)} sentences")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python ingest_10k.py data/ten_k")
    else:
        ingest_10k(sys.argv[1])