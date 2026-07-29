from dotenv import load_dotenv
load_dotenv()
from base import supabase

print("=== Embedding coverage ===")
for table, col in [
    ("claims", "claim_text"),
    ("documents", "raw_text"),
    ("sentiment_records", "text"),
]:
    has = supabase.table(table).select("id", count="exact").not_.is_("embedding", "null").limit(1).execute()
    missing = supabase.table(table).select("id", count="exact").is_("embedding", "null").limit(1).execute()
    print(f"  {table:<25} {has.count or 0:>6,} embedded | {missing.count or 0:>6,} missing")