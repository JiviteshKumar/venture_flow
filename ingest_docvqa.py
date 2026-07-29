# ---------- CRITICAL (FIRST) ----------
from PIL import Image
Image.MAX_IMAGE_PIXELS = None

from dotenv import load_dotenv
load_dotenv()

import json, uuid, os, io, time
from datasets import load_dataset
from base import supabase, batch_upsert, chunked, upload_to_storage

CHECKPOINT_FILE = ".checkpoints/docvqa.txt"


# ---------- CHECKPOINT ----------
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


# ---------- EXISTING ----------
def get_existing():
    try:
        res = supabase.table("visual_assets") \
            .select("asset_id") \
            .eq("source", "docvqa") \
            .execute()
        return {r["asset_id"] for r in res.data}
    except:
        return set()


# ---------- SAFE UPLOAD ----------
def safe_upload(bucket, path, bytes_data, mime):
    for _ in range(3):
        try:
            upload_to_storage(bucket, path, bytes_data, mime)
            return True
        except:
            time.sleep(2)
    return False


# ---------- IMAGE ----------
def get_image_bytes(item):
    for key in ["image", "document", "preview"]:
        img = item.get(key)

        if img is None:
            continue

        if isinstance(img, list) and len(img) > 0:
            img = img[0]

        if hasattr(img, "save"):
            try:
                # 🔥 resize + compress
                img.thumbnail((1024, 1024))

                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=70)
                return buf.getvalue(), img.size

            except Exception as e:
                print(f"Image processing error: {e}")
                return None, (None, None)

    return None, (None, None)


# ---------- QA ----------
def extract_qa(item, asset_db_id, split):
    qa_rows = []

    questions = item.get("questions", {})
    answers = item.get("answers", {})

    if isinstance(questions, dict):
        q_ids = questions.get("question_id", [])
        q_texts = questions.get("question", [])
        a_list = answers.get("answer", []) if isinstance(answers, dict) else []

        for i, (qid, qtext) in enumerate(zip(q_ids, q_texts)):
            ans = a_list[i] if i < len(a_list) else ""
            if isinstance(ans, list):
                ans = ans[0] if ans else ""

            qa_rows.append({
                "source": "docvqa",
                "split": split,
                "qa_id": str(qid),
                "question": str(qtext)[:1000],
                "answer": str(ans)[:500],
                "answer_type": "extractive",
                "visual_asset_id": asset_db_id,
                "metadata": json.dumps({})
            })

    elif isinstance(questions, list):
        for qa in questions:
            if not isinstance(qa, dict):
                continue

            ans = qa.get("answer", "")
            if isinstance(ans, list):
                ans = ans[0] if ans else ""

            qa_rows.append({
                "source": "docvqa",
                "split": split,
                "qa_id": str(qa.get("question_id", uuid.uuid4())),
                "question": str(qa.get("question", ""))[:1000],
                "answer": str(ans)[:500],
                "answer_type": "extractive",
                "visual_asset_id": asset_db_id,
                "metadata": json.dumps({})
            })

    return qa_rows


# ---------- MAIN ----------
def ingest_docvqa():
    print("Starting DocVQA ingestion...")

    existing = get_existing()
    print(f"Already uploaded: {len(existing)}")

    start_idx = load_checkpoint()

    # 🔥 streaming (prevents crashes)
    ds = load_dataset("VLR-CVC/DocVQA-2026", streaming=True)

    for split in ds.keys():

        if split in ["val", "validation"]:
            db_split = "dev"
        else:
            db_split = split

        data = ds[split]
        print(f"\nProcessing {split} (streaming mode)")

        asset_rows = []
        qa_rows = []

        for i, item in enumerate(data):

            if split == "train" and i < start_idx:
                continue

            doc_id = str(item.get("doc_id", uuid.uuid4()))
            asset_id = f"{doc_id}_{i}"

            if asset_id in existing:
                continue

            storage_path = f"docvqa/{db_split}/{asset_id}.jpg"

            # -------- IMAGE --------
            try:
                img_bytes, (w, h) = get_image_bytes(item)
            except Exception as e:
                print(f"Skipping image error: {e}")
                continue

            if img_bytes:
                success = safe_upload(
                    "documents-raw",
                    storage_path,
                    img_bytes,
                    "image/jpeg"
                )

                if not success:
                    print("Upload failed after retries → skipping")
                    continue

            # -------- ASSET --------
            asset_db_id = str(uuid.uuid4())

            asset_rows.append({
                "id": asset_db_id,
                "source": "docvqa",
                "split": db_split,
                "asset_id": asset_id,
                "storage_path": storage_path,
                "storage_bucket": "documents-raw",
                "asset_type": "page_scan",
                "width_px": w,
                "height_px": h,
                "bounding_boxes": json.dumps([]),
                "data_series": json.dumps([]),
                "metadata": json.dumps({
                    "doc_category": str(item.get("doc_category", ""))
                }),
            })

            # -------- QA --------
            qa_rows.extend(extract_qa(item, asset_db_id, db_split))

            # -------- BATCH --------
            if len(asset_rows) >= 100:
                for chunk in chunked(asset_rows, 100):
                    batch_upsert("visual_assets", chunk, "source,asset_id")
                asset_rows = []

            if len(qa_rows) >= 500:
                for chunk in chunked(qa_rows, 500):
                    batch_upsert("qa_pairs", chunk, None)
                qa_rows = []

            # -------- CHECKPOINT --------
            if i % 500 == 0 and split == "train":
                save_checkpoint(i)
                print(f"Checkpoint: {i}")

        # -------- FINAL FLUSH --------
        for chunk in chunked(asset_rows, 100):
            batch_upsert("visual_assets", chunk, "source,asset_id")

        for chunk in chunked(qa_rows, 500):
            batch_upsert("qa_pairs", chunk, None)

        print(f"{split} DONE")

    print("\n🔥 DocVQA ingestion complete.")


# ---------- RUN ----------
if __name__ == "__main__":
    ingest_docvqa()