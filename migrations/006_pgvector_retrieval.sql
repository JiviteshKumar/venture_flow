-- Enables real vector retrieval to replace the SQL LIKE "RAG" in
-- rag_engine.py (e1 on the Ship List). Embeddings are produced by
-- embeddings.py (TF-IDF+SVD -- see ml/scripts/train_text_embedder.py for
-- why not a pretrained sentence-transformer). No ANN index (ivfflat/hnsw)
-- is created here -- at single-user report volumes a sequential scan over
-- the <=> operator is both correct and fast; add one once report volume
-- actually justifies the build/maintenance cost.
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE dd_reports ADD COLUMN IF NOT EXISTS embedding vector(64);
