from dotenv import load_dotenv
load_dotenv()

import json
from datasets import load_dataset
from base import batch_upsert, chunked

def ingest_phrasebank():
    configs = {
        "sentences_allagree": 1.0,
        "sentences_75agree": 0.75,
        "sentences_66agree": 0.66,
        "sentences_50agree": 0.50,
    }
    label_map = {0: "negative", 1: "neutral", 2: "positive"}
    seen = set()
    rows = []
    for config, confidence in configs.items():
        print(f"Loading config: {config}...")
        ds = load_dataset("takala/financial_phrasebank", config, trust_remote_code=True)
        for item in ds["train"]:
            key = item["sentence"]
            if key not in seen:
                seen.add(key)
                rows.append({
                    "source": "financial_phrasebank",
                    "split": "train",
                    "text": item["sentence"],
                    "label": label_map[item["label"]],
                    "raw_label": str(item["label"]),
                    "confidence": confidence,
                    "metadata": json.dumps({"agreement_threshold": config}),
                })
    for chunk in chunked(rows, 500):
        batch_upsert("sentiment_records", chunk, "source,text")
    print(f"PhraseBank: {len(rows)} records loaded")

if __name__ == "__main__":
    ingest_phrasebank()