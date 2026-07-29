from dotenv import load_dotenv
load_dotenv()

import json, uuid
from datasets import load_dataset
from base import batch_upsert, chunked

def ingest_tatqa():
    print("🚀 Loading TAT-QA...")

    # ✅ WORKING DATASET (no weird issues)
    ds = load_dataset("next-tat/tat-qa")

    for split in ds.keys():
        db_split = "dev" if split == "validation" else split
        data = ds[split]

        print(f"\nProcessing {split}: {len(data)} items")

        doc_rows = []
        table_rows = []
        qa_rows = []

        for item in data:
            doc_id = str(uuid.uuid4())

            # ---------- TEXT ----------
            paragraphs = item.get("paragraphs", [])
            combined_text = " ".join(
                p["text"] if isinstance(p, dict) else str(p)
                for p in paragraphs
            )

            doc_rows.append({
                "id": doc_id,
                "source": "tat_qa",
                "modality": "multimodal",
                "split": db_split,
                "doc_id": item.get("uid", doc_id),
                "raw_text": combined_text[:50000],
                "metadata": json.dumps({})
            })

            # ---------- TABLE ----------
            table = item.get("table", {})
            if table:
                table_rows.append({
                    "source": "tat_qa",
                    "split": db_split,
                    "table_id": item.get("uid", doc_id),
                    "document_id": doc_id,
                    "cells": json.dumps(table.get("table", [])),
                    "metadata": json.dumps({})
                })

            # ---------- QA ----------
            for qa in item.get("questions", []):
                qa_rows.append({
                    "source": "tat_qa",
                    "split": db_split,
                    "qa_id": str(qa.get("uid", uuid.uuid4())),
                    "question": qa.get("question", "")[:1000],
                    "answer": json.dumps(qa.get("answer", "")),
                    "answer_type": qa.get("answer_type", ""),
                    "answer_scale": qa.get("scale", ""),
                    "supporting_facts": json.dumps(qa.get("rel_paragraphs", [])),
                    "document_id": doc_id,
                    "metadata": json.dumps({
                        "derivation": qa.get("derivation", "")
                    })
                })

        # ---------- INSERT ----------
        print(f"Inserting: {len(doc_rows)} docs, {len(table_rows)} tables, {len(qa_rows)} QA")

        for chunk in chunked(doc_rows, 200):
            batch_upsert("documents", chunk, "source,doc_id")

        for chunk in chunked(table_rows, 200):
            batch_upsert("tables_structured", chunk, None)

        for chunk in chunked(qa_rows, 500):
            batch_upsert("qa_pairs", chunk, None)

        print(f"{split} DONE")

if __name__ == "__main__":
    ingest_tatqa()