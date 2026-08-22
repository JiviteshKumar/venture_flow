from dotenv import load_dotenv
load_dotenv()

import os
import time
import concurrent.futures
from sentence_transformers import SentenceTransformer
from base import supabase

print("Loading embedding model...")
model = SentenceTransformer("sentence-transformers/all-mpnet-base-v2")
print("Model ready.\n")

def update_batch(batch_data: list[tuple]) -> int:
    """Update a batch of rows with their embeddings using parallel calls."""
    success = 0
    for row_id, embedding in batch_data:
        try:
            supabase.table_name_placeholder  # just to reference supabase
            supabase.rpc("update_embedding", {
                "row_id": row_id,
                "new_embedding": embedding
            }).execute()
            success += 1
        except:
            pass
    return success

def embed_table(table: str, text_col: str, encode_batch: int = 512, update_workers: int = 10):
    """
    Fast embedding:
    - Encodes 512 texts at once (GPU/CPU batched)
    - Updates DB with 10 parallel workers simultaneously
    """
    print(f"Embedding {table}.{text_col}...")
    total_embedded = 0
    round_num = 0

    while True:
        round_num += 1

        # Fetch rows missing embeddings
        result = supabase.table(table)\
            .select(f"id,{text_col}")\
            .is_("embedding", "null")\
            .limit(encode_batch)\
            .execute()

        rows = result.data
        if not rows:
            print(f"  No more rows. Done with {table}\n")
            break

        # Filter empty texts
        valid = [(r["id"], str(r.get(text_col) or "")[:512])
                 for r in rows if r.get(text_col)]
        if not valid:
            break

        ids = [v[0] for v in valid]
        texts = [v[1] for v in valid]

        t0 = time.time()
        print(f"  Round {round_num}: encoding {len(texts)} texts...", end=" ", flush=True)

        # Encode all at once — fast
        embeddings = model.encode(
            texts,
            batch_size=64,
            show_progress_bar=False,
            normalize_embeddings=True
        )

        encode_time = time.time() - t0
        print(f"done in {encode_time:.1f}s. Saving...", end=" ", flush=True)

        t1 = time.time()

        # Update using thread pool — 10 parallel API calls at once
        def update_one(args):
            row_id, emb = args
            try:
                supabase.table(table)\
                    .update({"embedding": emb.tolist()})\
                    .eq("id", row_id)\
                    .execute()
                return 1
            except Exception as e:
                return 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=update_workers) as executor:
            results = list(executor.map(update_one, zip(ids, embeddings)))

        saved = sum(results)
        save_time = time.time() - t1
        total_embedded += saved

        print(f"{saved} saved in {save_time:.1f}s | Total: {total_embedded}")

    print(f"Done: {table} — {total_embedded} total rows embedded\n")

def count_missing(table: str, text_col: str) -> int:
    result = supabase.table(table)\
        .select("id", count="exact")\
        .is_("embedding", "null")\
        .limit(1)\
        .execute()
    return result.count or 0

if __name__ == "__main__":
    # Show status first
    print("=== Current embedding status ===")
    for table, col in [
        ("claims", "claim_text"),
        ("documents", "raw_text"),
        ("sentiment_records", "text"),
    ]:
        missing = count_missing(table, col)
        print(f"  {table:<25} {missing:>6,} rows need embedding")
    print()

    # Run
    embed_table("claims", "claim_text")
    embed_table("documents", "raw_text")
    embed_table("sentiment_records", "text")

    print("All embeddings complete.")
     