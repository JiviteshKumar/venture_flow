from dotenv import load_dotenv
load_dotenv()
from base import supabase

# Try uploading a tiny test file
test_bytes = b"hello world"
try:
    result = supabase.storage.from_("charts-raw").upload(
        "test/hello.txt",
        test_bytes,
        file_options={"content-type": "text/plain", "upsert": "true"}
    )
    print("Upload SUCCESS:", result)
except Exception as e:
    print("Upload FAILED:", e)