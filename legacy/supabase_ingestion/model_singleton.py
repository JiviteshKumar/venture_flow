from sentence_transformers import SentenceTransformer
import warnings
warnings.filterwarnings("ignore")

print("Loading embedding model (once)...")
_embedder = None

def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(
            "sentence-transformers/all-mpnet-base-v2"
        )
    return _embedder