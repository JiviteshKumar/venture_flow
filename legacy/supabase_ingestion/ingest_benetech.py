print("Script started")

from dotenv import load_dotenv
load_dotenv()

import os, json
from PIL import Image
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from base import batch_upsert, chunked, upload_to_storage

CHECKPOINT_FILE = ".checkpoints/benetech.txt"

# ---------------- CHECKPOINT ----------------
def load_checkpoint():
    try:
        with open(CHECKPOINT_FILE) as f:
            return int(f.read().strip())
    except:
        return 0

def save_checkpoint(idx):
    os.makedirs(".checkpoints", exist_ok=True)
    with open(CHECKPOINT_FILE, "w") as f:
        f.write(str(idx))

# ---------------- PROCESS ONE FILE ----------------
def process_file(i, ann_file, annotations_dir, images_dir):
    if not ann_file.endswith(".json"):
        return None

    ann_path = os.path.join(annotations_dir, ann_file)
    img_id = ann_file.replace(".json", "")

    img_path = os.path.join(images_dir, f"{img_id}.jpg")
    if not os.path.exists(img_path):
        img_path = os.path.join(images_dir, f"{img_id}.png")

    try:
        with open(ann_path) as f:
            ann = json.load(f)
    except:
        return None

    chart_type = ann.get("chart-type", "unknown")
    data_series = ann.get("data-series", [])
    axes = ann.get("axes", {})

    bboxes = []
    for key, val in ann.get("visual-elements", {}).items():
        if isinstance(val, list):
            for elem in val:
                if isinstance(elem, dict):
                    bboxes.append({"label": key, **elem})

    storage_path = f"benetech/train/{img_id}.jpg"
    width_px, height_px = None, None

    # -------- Upload image --------
    if os.path.exists(img_path):
        try:
            with open(img_path, "rb") as img_f:
                img_bytes = img_f.read()

            with Image.open(img_path) as img:
                width_px, height_px = img.size

            upload_to_storage("charts-raw", storage_path, img_bytes, "image/jpeg")

        except Exception as e:
            return None

    return {
        "source": "benetech",
        "split": "train",
        "asset_id": img_id,
        "storage_path": storage_path,
        "storage_bucket": "charts-raw",
        "asset_type": "chart",
        "chart_type": chart_type,
        "width_px": width_px,
        "height_px": height_px,
        "bounding_boxes": json.dumps(bboxes),
        "data_series": json.dumps(data_series),
        "metadata": json.dumps({"axes": axes}),
    }

# ---------------- MAIN INGEST ----------------
def ingest_benetech(data_path: str):
    print("Starting Benetech ingestion...")

    annotations_dir = os.path.join(data_path, "train", "annotations")
    images_dir = os.path.join(data_path, "train", "images")

    annotation_files = sorted(os.listdir(annotations_dir))
    start_idx = load_checkpoint()

    print(f"Resuming from index {start_idx} of {len(annotation_files)}")

    annotation_files = annotation_files[start_idx:]

    asset_rows = []
    processed_count = start_idx

    # 🔥 PARALLEL EXECUTION
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [
            executor.submit(process_file, i + start_idx, file, annotations_dir, images_dir)
            for i, file in enumerate(annotation_files)
        ]

        for i, future in enumerate(tqdm(as_completed(futures), total=len(futures))):
            result = future.result()

            if result:
                asset_rows.append(result)

            processed_count += 1

            # Flush every 100
            if len(asset_rows) >= 100:
                for chunk in chunked(asset_rows, 100):
                    batch_upsert("visual_assets", chunk, "source,asset_id")
                asset_rows = []

                save_checkpoint(processed_count)
                print(f"Checkpoint saved at {processed_count}")

    # Final flush
    if asset_rows:
        for chunk in chunked(asset_rows, 100):
            batch_upsert("visual_assets", chunk, "source,asset_id")

    save_checkpoint(start_idx + len(annotation_files))
    print("Benetech ingestion complete.")

# ---------------- ENTRY ----------------
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python ingest_benetech.py data/benetech")
    else:
        ingest_benetech(sys.argv[1])