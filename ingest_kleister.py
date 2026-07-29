from dotenv import load_dotenv
load_dotenv()

import os, json, lzma
from base import batch_upsert, chunked, upload_to_storage

def ingest_kleister(data_path: str):
    print("Starting Kleister NDA ingestion...")

    split_map = {
        "train": "train",
        "dev-0": "dev",
        "test-A": "test",
    }

    documents_dir = os.path.join(data_path, "documents")
    doc_rows = []
    contract_rows = []
    seen_ids = set()

    for folder_name, db_split in split_map.items():
        split_dir = os.path.join(data_path, folder_name)
        if not os.path.exists(split_dir):
            print(f"Skipping {folder_name} — folder not found")
            continue

        print(f"\nProcessing {folder_name}...")

        # ── Read expected.tsv for annotations ───────────────────────────────
        expected_path = os.path.join(split_dir, "expected.tsv")
        annotations = {}  # doc_name → list of "key=value" strings

        if os.path.exists(expected_path):
            print(f"  Reading {expected_path}")
            with open(expected_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(" ", 1)
                    doc_name = parts[0]
                    ann_str = parts[1] if len(parts) > 1 else ""
                    if doc_name not in annotations:
                        annotations[doc_name] = []
                    if ann_str:
                        annotations[doc_name].append(ann_str)
            print(f"  Found {len(annotations)} annotated documents")
        else:
            print(f"  No expected.tsv found in {folder_name}")

        # ── Read in.tsv.xz for document names (even if no annotations) ──────
        in_tsv_xz = os.path.join(split_dir, "in.tsv.xz")
        in_doc_names = set()

        if os.path.exists(in_tsv_xz):
            print(f"  Reading {in_tsv_xz}")
            try:
                with lzma.open(in_tsv_xz, "rt", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        # first column is the document filename
                        doc_name = line.split("\t")[0].strip()
                        if doc_name:
                            in_doc_names.add(doc_name)
                print(f"  Found {len(in_doc_names)} document names in in.tsv.xz")
            except Exception as e:
                print(f"  Could not read in.tsv.xz: {e}")

        # Merge both sources of doc names
        all_doc_names = set(annotations.keys()) | in_doc_names
        print(f"  Total unique documents: {len(all_doc_names)}")

        for doc_name in all_doc_names:
            doc_id = f"kleister_{db_split}_{doc_name}"

            # Skip if already processed
            if doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)

            storage_path = None

            # Try to upload the actual document file if it exists
            if os.path.exists(documents_dir):
                for ext in [".pdf", ".txt", ".png"]:
                    candidate = os.path.join(documents_dir, f"{doc_name}{ext}")
                    if os.path.exists(candidate):
                        try:
                            with open(candidate, "rb") as df:
                                file_bytes = df.read()
                            content_type = "application/pdf" if ext == ".pdf" else "text/plain"
                            storage_path = f"kleister/{db_split}/{doc_name}{ext}"
                            upload_to_storage(
                                "documents-raw",
                                storage_path,
                                file_bytes,
                                content_type
                            )
                        except Exception as e:
                            print(f"  Upload failed for {doc_name}: {e}")
                            storage_path = None
                        break

            doc_rows.append({
                "source": "kleister_nda",
                "modality": "document",
                "split": db_split,
                "doc_id": doc_id,
                "title": doc_name,
                "storage_path": storage_path,
                "storage_bucket": "documents-raw" if storage_path else None,
                "metadata": json.dumps({"original_name": doc_name}),
            })

            # Parse key=value annotation pairs
            extracted_fields = {}
            field_spans = []
            for ann_str in annotations.get(doc_name, []):
                for token in ann_str.split():
                    if "=" in token:
                        key, val = token.split("=", 1)
                        if key not in extracted_fields:
                            extracted_fields[key] = []
                        extracted_fields[key].append(val)
                        field_spans.append({"field": key, "value": val})

            if not extracted_fields:
                extracted_fields = {"status": ["unannotated"]}

            contract_rows.append({
                "source": "kleister_nda",
                "split": db_split,
                "contract_id": doc_id,
                "extracted_fields": json.dumps(extracted_fields),
                "field_spans": json.dumps(field_spans),
                "metadata": json.dumps({"doc_name": doc_name}),
            })

    print(f"\nInserting {len(doc_rows)} Kleister documents...")
    inserted = 0
    for chunk in chunked(doc_rows, 100):
        try:
            batch_upsert("documents", chunk, "source,doc_id")
            inserted += len(chunk)
            print(f"  {inserted}/{len(doc_rows)} documents inserted...")
        except Exception as e:
            print(f"  Chunk error: {e}")

    print(f"Inserting {len(contract_rows)} contracts...")
    inserted = 0
    for chunk in chunked(contract_rows, 200):
        try:
            batch_upsert("contracts", chunk, None)
            inserted += len(chunk)
            print(f"  {inserted}/{len(contract_rows)} contracts inserted...")
        except Exception as e:
            print(f"  Chunk error: {e}")

    print(f"\nKleister NDA done: {len(doc_rows)} docs, {len(contract_rows)} contracts")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python ingest_kleister.py data/kleister_nda")
    else:
        ingest_kleister(sys.argv[1])
