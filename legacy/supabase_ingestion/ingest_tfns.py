from dotenv import load_dotenv
load_dotenv()

import json
from datasets import load_dataset
from base import batch_upsert, chunked

def ingest_tfns():
    print("Loading TFNS from HuggingFace...")
    ds = load_dataset("zeroshot/twitter-financial-news-sentiment")
    label_map = {0: "bearish", 1: "bullish", 2: "neutral"}
    norm_map = {"bearish": "negative", "bullish": "positive", "neutral": "neutral"}
    rows = []
    for split in ["train", "validation"]:
        for item in ds[split]:
            raw = label_map[item["label"]]
            rows.append({
                "source": "tfns",
                "split": "dev" if split == "validation" else split,
                "text": item["text"],
                "label": norm_map[raw],
                "raw_label": raw,
                "metadata": json.dumps({}),
            })
    for chunk in chunked(rows, 500):
        batch_upsert("sentiment_records", chunk, None)
    print(f"TFNS: {len(rows)} records loaded")

if __name__ == "__main__":
    ingest_tfns()