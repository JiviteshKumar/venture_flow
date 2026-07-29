from dotenv import load_dotenv
load_dotenv()

import os, json, uuid, asyncio, aiofiles
import aiohttp
from PIL import Image
from tqdm import tqdm
from base import supabase, batch_upsert, chunked, upload_to_storage

CHECKPOINT_FILE = ".checkpoints/chartqa.txt"

def load_checkpoint():
    try:
        with open(CHECKPOINT_FILE) as f:
            return set(f.read().strip().split("\n"))
    except:
        return set()

def save_checkpoint(done_ids: set):
    os.makedirs(".checkpoints", exist_ok=True)
    with open(CHECKPOINT_FILE, "w") as f:
        f.write("\n".join(done_ids))

def get_already_uploaded():
    """Fetch asset_ids already in DB so we skip re-uploading."""
    print("Checking what's already in database...")
    try:
        result = supabase.table("visual_assets")\
            .select("asset_id")\
            .eq("source", "chartqa")\
            .execute()
        existing = {r["asset_id"] for r in result.data}
        print(f"  Found {len(existing)} already uploaded")
        return existing
    except:
        return set()

def upload_image_safe(bucket, storage_path, img_local, content_type="image/png"):
    """Upload with graceful failure — returns True/False."""
    try:
        with open(img_local, "rb") as f:
            img_bytes = f.read()
        upload_to_storage(bucket, storage_path, img_bytes, content_type)
        return True
    except Exception as e:
        # If already exists, that's fine
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            return True
        print(f"  Upload failed {os.path.basename(img_local)}: {e}")
        return False

def ingest_chartqa(image_dir: str):
    print("Starting ChartQA ingestion (fast mode)...")

    already_done = get_already_uploaded()
    checkpoint_ids = load_checkpoint()
    already_done = already_done | checkpoint_ids

    for split in ["train", "val", "test"]:
        # Try both naming conventions
        qa_path = None
        for candidate in [
            f"{image_dir}/{split}/{split}_augmented.json",
            f"{image_dir}/{split}/{split}_human.json",
            f"{image_dir}/{split}.json",
        ]:
            if os.path.exists(candidate):
                qa_path = candidate
                break

        if not qa_path:
            print(f"No JSON found for split '{split}', skipping...")
            continue

        print(f"\nReading {qa_path}...")
        with open(qa_path, encoding="utf-8") as f:
            qa_data = json.load(f)

        db_split = "dev" if split == "val" else split

        # Find images folder
        img_folder = None
        for candidate in [
            f"{image_dir}/{split}/png",
            f"{image_dir}/{split}/images",
            f"{image_dir}/{split}",
        ]:
            if os.path.exists(candidate):
                img_folder = candidate
                break

        if not img_folder:
            print(f"  No images folder found for {split}, skipping images...")

        asset_rows = []
        qa_rows = []
        seen_in_batch = set()  # prevent duplicates within same run
        skipped = 0
        uploaded = 0

        print(f"Processing {len(qa_data)} items in {split}...")

        for item in tqdm(qa_data, desc=f"ChartQA {split}"):
            img_filename = item.get("imgname", item.get("image", ""))
            if not img_filename:
                continue

            # Skip if already processed
            if img_filename in already_done or img_filename in seen_in_batch:
                skipped += 1
                # Still need QA pairs even if image already uploaded
                asset_id_lookup = img_filename  # use filename as stable ID
                for qa in item.get("qa", []):
                    question = qa.get("query", qa.get("question", ""))
                    answer = str(qa.get("label", qa.get("answer", "")))
                    if question:
                        qa_rows.append({
                            "source": "chartqa",
                            "split": db_split,
                            "question": question[:1000],
                            "answer": answer[:500],
                            "answer_type": "extractive",
                            "metadata": json.dumps({
                                "imgname": img_filename,
                                "data_source": qa.get("data_source", "")
                            }),
                        })
                continue

            seen_in_batch.add(img_filename)
            asset_id = str(uuid.uuid4())
            storage_path = f"chartqa/{split}/{img_filename}"
            width_px, height_px = None, None

            # Upload image if folder exists
            if img_folder:
                img_local = os.path.join(img_folder, img_filename)
                if os.path.exists(img_local):
                    try:
                        with Image.open(img_local) as img:
                            width_px, height_px = img.size
                    except:
                        pass
                    success = upload_image_safe("charts-raw", storage_path, img_local)
                    if success:
                        uploaded += 1
                        already_done.add(img_filename)

            asset_rows.append({
                "id": asset_id,
                "source": "chartqa",
                "split": db_split,
                "asset_id": img_filename,
                "storage_path": storage_path,
                "storage_bucket": "charts-raw",
                "asset_type": "chart",
                "width_px": width_px,
                "height_px": height_px,
                "bounding_boxes": json.dumps([]),
                "data_series": json.dumps([]),
                "metadata": json.dumps({"original_filename": img_filename}),
            })

            for qa in item.get("qa", []):
                question = qa.get("query", qa.get("question", ""))
                answer = str(qa.get("label", qa.get("answer", "")))
                if not question:
                    continue
                qa_rows.append({
                    "source": "chartqa",
                    "split": db_split,
                    "question": question[:1000],
                    "answer": answer[:500],
                    "answer_type": "extractive",
                    "visual_asset_id": asset_id,
                    "metadata": json.dumps({
                        "imgname": img_filename,
                        "data_source": qa.get("data_source", "")
                    }),
                })

            # Flush every 200 assets
            if len(asset_rows) >= 200:
                for chunk in chunked(asset_rows, 100):
                    try:
                        batch_upsert("visual_assets", chunk, "source,asset_id")
                    except Exception as e:
                        print(f"  Asset chunk error: {e}")
                asset_rows = []
                save_checkpoint(already_done)

        # Final flush for this split
        if asset_rows:
            for chunk in chunked(asset_rows, 100):
                try:
                    batch_upsert("visual_assets", chunk, "source,asset_id")
                except Exception as e:
                    print(f"  Asset chunk error: {e}")

        if qa_rows:
            print(f"  Inserting {len(qa_rows)} QA pairs for {split}...")
            for chunk in chunked(qa_rows, 500):
                try:
                    batch_upsert("qa_pairs", chunk, None)
                except Exception as e:
                    print(f"  QA chunk error: {e}")

        save_checkpoint(already_done)
        print(f"  {split}: {uploaded} uploaded, {skipped} skipped, {len(qa_rows)} QA pairs")

    print("\nChartQA ingestion complete.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python ingest_chartqa.py \"data/chartqa/ChartQA Dataset\"")
    else:
        ingest_chartqa(sys.argv[1])
