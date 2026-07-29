from dotenv import load_dotenv
load_dotenv()

import os, uuid, json, asyncio
from supabase import create_client, Client
from datasets import load_dataset
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]  # use service key for ETL

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Batch upserter with retry ──────────────────────────────────────────────
@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=30))
def batch_upsert(table: str, rows: list[dict], conflict_cols: str = None):
    """Insert rows; on conflict (source, original_id) do nothing."""
    if not rows:
        return
    query = supabase.table(table).upsert(rows, on_conflict=conflict_cols)
    query.execute()

def chunked(lst, n=500):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

# ── Storage uploader ────────────────────────────────────────────────────────
@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=1, max=20))
def upload_to_storage(bucket: str, path: str, file_bytes: bytes, content_type: str):
    supabase.storage.from_(bucket).upload(
        path, file_bytes,
        file_options={"content-type": content_type, "upsert": "true"}
    )
    return path