from dotenv import load_dotenv
load_dotenv()

import json
from datasets import load_dataset
from base import supabase, batch_upsert, chunked


def ingest_scifact():
    print("Loading SciFact from HuggingFace...")

    claims_ds = load_dataset("allenai/scifact", "claims")
    corpus_ds = load_dataset("allenai/scifact", "corpus")

    # ─────────────────────────────────────────────
    # 1. Load corpus → documents table
    # ─────────────────────────────────────────────
    doc_rows = []
    seen_docs = set()

    for item in corpus_ds["train"]:
        doc_id = str(item["doc_id"])

        # Deduplicate documents
        if doc_id in seen_docs:
            continue
        seen_docs.add(doc_id)

        doc_rows.append({
            "source": "scifact",
            "modality": "text",
            "split": "train",
            "doc_id": doc_id,
            "title": item.get("title", ""),
            "raw_text": " ".join(item.get("abstract", [])),
            "metadata": json.dumps({}),
        })

    print(f"Inserting {len(doc_rows)} corpus documents...")
    for chunk in chunked(doc_rows, 500):
        batch_upsert("documents", chunk, "source,doc_id")
    print("Documents done.")

    # ─────────────────────────────────────────────
    # 2. Load claims → claims table
    # ─────────────────────────────────────────────
    claim_rows = []
    seen_claims = set()

    for split_name in ["train", "validation"]:
        for item in claims_ds[split_name]:

            claim_id = str(item["id"])

            # 🔥 Deduplication fix (IMPORTANT)
            if claim_id in seen_claims:
                continue
            seen_claims.add(claim_id)

            label_raw = item.get("label", "")
            if label_raw == "SUPPORT":
                label = "SUPPORTS"
            elif label_raw == "CONTRADICT":
                label = "REFUTES"
            else:
                label = "NOT_ENOUGH_INFO"

            claim_rows.append({
                "source": "scifact",
                "split": "dev" if split_name == "validation" else "train",
                "claim_id": claim_id,
                "claim_text": item["claim"],
                "label": label,
                "evidence_texts": json.dumps(item.get("evidence", {})),
                "metadata": json.dumps({
                    "cited_doc_ids": item.get("cited_doc_ids", [])
                }),
            })

    print(f"Inserting {len(claim_rows)} claims...")
    for chunk in chunked(claim_rows, 500):
        batch_upsert("claims", chunk, "source,claim_id")

    print("Claims done.")
    print(f"\nSciFact ingestion complete: {len(doc_rows)} docs, {len(claim_rows)} claims.")


if __name__ == "__main__":
    ingest_scifact() 