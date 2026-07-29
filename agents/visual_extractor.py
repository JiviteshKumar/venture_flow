from dotenv import load_dotenv
load_dotenv()

import io, json, base64
import requests
from PIL import Image
from sentence_transformers import SentenceTransformer
from base import supabase

embedder = SentenceTransformer("sentence-transformers/all-mpnet-base-v2")

def get_image_from_storage(storage_path: str, bucket: str) -> bytes:
    """Download image from Supabase Storage."""
    try:
        result = supabase.storage.from_(bucket).download(storage_path)
        return result
    except Exception as e:
        print(f"Storage download failed: {e}")
        return None

def answer_chart_question(
    question: str,
    asset_id: str = None,
    image_bytes: bytes = None
) -> dict:
    """
    Answer a question about a chart using semantic search
    against our QA pairs database.
    Falls back to web search if no DB match found.
    """
    # 1. Try to find answer in our QA pairs database
    q_emb = embedder.encode(question)

    # Search similar questions in qa_pairs
    result = supabase.table("qa_pairs")\
        .select("question,answer,visual_asset_id,source")\
        .eq("source", "chartqa")\
        .limit(1000)\
        .execute()

    qa_data = result.data
    if qa_data:
        # Find most similar question
        best_match = None
        best_sim = 0.0

        from sentence_transformers import util
        import torch

        q_tensor = embedder.encode(question, convert_to_tensor=True)
        db_questions = [r["question"] for r in qa_data]
        db_embs = embedder.encode(db_questions, convert_to_tensor=True)

        sims = util.cos_sim(q_tensor, db_embs)[0]
        best_idx = int(sims.argmax())
        best_sim = float(sims[best_idx])

        if best_sim > 0.75:
            best_match = qa_data[best_idx]
            return {
                "question": question,
                "answer": best_match["answer"],
                "source": "database_match",
                "similarity": best_sim,
                "matched_question": best_match["question"],
            }

    # 2. If no good DB match, return best effort
    return {
        "question": question,
        "answer": "No similar question found in database",
        "source": "no_match",
        "similarity": 0.0,
    }

def extract_chart_data(asset_id: str) -> dict:
    """Pull chart metadata and data series from database."""
    result = supabase.table("visual_assets")\
        .select("*")\
        .eq("asset_id", asset_id)\
        .execute()

    if not result.data:
        return {"error": "Asset not found"}

    asset = result.data[0]
    data_series = asset.get("data_series", [])
    bboxes = asset.get("bounding_boxes", [])

    if isinstance(data_series, str):
        data_series = json.loads(data_series)
    if isinstance(bboxes, str):
        bboxes = json.loads(bboxes)

    return {
        "asset_id": asset_id,
        "chart_type": asset.get("chart_type"),
        "dimensions": f"{asset.get('width_px')}x{asset.get('height_px')}",
        "data_series": data_series,
        "bounding_boxes": bboxes[:5],
        "storage_path": asset.get("storage_path"),
    }

def get_chart_stats(asset_id: str) -> dict:
    """Extract numeric statistics from chart data series."""
    chart = extract_chart_data(asset_id)

    if "error" in chart:
        return chart

    series = chart.get("data_series", [])
    if not series:
        return {**chart, "stats": "No numeric data available"}

    # Try to extract numbers
    numbers = []
    for item in series:
        if isinstance(item, (int, float)):
            numbers.append(item)
        elif isinstance(item, dict):
            for v in item.values():
                if isinstance(v, (int, float)):
                    numbers.append(v)

    stats = {}
    if numbers:
        stats = {
            "count": len(numbers),
            "min": min(numbers),
            "max": max(numbers),
            "mean": sum(numbers) / len(numbers),
            "range": max(numbers) - min(numbers),
        }

    return {**chart, "stats": stats}

if __name__ == "__main__":
    # Test QA
    result = answer_chart_question(
        "What is the highest value shown in the bar chart?"
    )
    print(json.dumps(result, indent=2))