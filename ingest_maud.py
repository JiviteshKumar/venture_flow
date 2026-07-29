from dotenv import load_dotenv
load_dotenv()

import os, json, uuid
import pandas as pd
from base import batch_upsert, chunked, upload_to_storage

def ingest_maud(data_path: str):
    print("Starting MAUD ingestion...")
    doc_rows = []
    sentiment_rows = []
    contract_rows = []

    # MAUD ships as a CSV with one row per merger agreement clause
    csv_path = os.path.join(data_path, "maud.csv")
    if not os.path.exists(csv_path):
        # try alternate names
        for fname in os.listdir(data_path):
            if fname.endswith(".csv"):
                csv_path = os.path.join(data_path, fname)
                break

    print(f"Reading {csv_path}...")
    df = pd.read_csv(csv_path, encoding="utf-8", errors="replace")
    print(f"Columns found: {list(df.columns)}")

    # Group by agreement (document)
    id_col = "deal_id" if "deal_id" in df.columns else df.columns[0]
    text_col = next((c for c in df.columns if "text" in c.lower()), df.columns[1])
    label_col = next((c for c in df.columns if "label" in c.lower() or "answer" in c.lower()), None)

    seen_docs = {}
    for _, row in df.iterrows():
        doc_key = str(row[id_col])
        if doc_key not in seen_docs:
            doc_id = str(uuid.uuid4())
            seen_docs[doc_key] = doc_id
            doc_rows.append({
                "source": "maud",
                "modality": "document",
                "split": "train",
                "doc_id": doc_key,
                "title": doc_key,
                "metadata": json.dumps({"deal_id": doc_key}),
            })

        clause_text = str(row.get(text_col, ""))[:1000]
        label_val = str(row.get(label_col, "")) if label_col else ""

        # Normalize label
        if any(w in label_val.lower() for w in ["yes", "present", "support"]):
            norm_label = "positive"
        elif any(w in label_val.lower() for w in ["no", "absent", "contra"]):
            norm_label = "negative"
        else:
            norm_label = "neutral"

        sentiment_rows.append({
            "source": "maud",
            "split": "train",
            "text": clause_text,
            "label": norm_label,
            "raw_label": label_val[:100],
            "document_id": None,
            "metadata": json.dumps({row.name: str(v) for row.name, v in row.items()
                                     if row.name not in [id_col, text_col]}),
        })

    print(f"Inserting {len(doc_rows)} MAUD documents...")
    for chunk in chunked(doc_rows, 200):
        batch_upsert("documents", chunk, "source,doc_id")

    print(f"Inserting {len(sentiment_rows)} MAUD clause annotations...")
    for chunk in chunked(sentiment_rows, 500):
        batch_upsert("sentiment_records", chunk, None)

    print(f"MAUD done: {len(doc_rows)} docs, {len(sentiment_rows)} clauses")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python ingest_maud.py data/maud")
    else:
        ingest_maud(sys.argv[1])
