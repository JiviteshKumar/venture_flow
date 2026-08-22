from base import supabase

result = supabase.table("ingestion_log").select("*").limit(1).execute()
print("Connection works! Result:", result)
