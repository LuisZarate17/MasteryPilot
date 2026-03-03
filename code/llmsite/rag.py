# rag.py
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import os
from PyPDF2 import PdfReader

# Embedding model
embedder = SentenceTransformer("all-MiniLM-L6-v2")

# all-MiniLM-L6-v2 embedding size
DIMENSION = 384

# Use cosine similarity:
# Formula name: Cosine similarity via normalized inner product
# Formula: cos(u, v) = (u · v) / (||u|| * ||v||)
# Implementation: normalize u and v to unit length, then use inner product.
index = faiss.IndexFlatIP(DIMENSION)

# Store docs and metadata
documents = []   # chunk text
metas = []       # dicts: {"source": filename, "chunk_id": int}

def _normalize(vectors: np.ndarray) -> np.ndarray:
    """
    Formula name: L2 normalization
    Formula: v_normalized = v / max(||v||_2, eps)
    Inputs:
      - v (vector)
      - eps (small constant)
    """
    eps = 1e-12
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, eps)

def add_documents(text_list, meta_list=None):
    """
    Embed and store text documents in FAISS.

    Function: embedder.encode
    Inputs:
      - text_list (list[str])
    Output:
      - embeddings (np.ndarray shape [n, 384])
    """
    global documents, metas

    if not text_list:
        return

    embeddings = embedder.encode(text_list, convert_to_numpy=True, show_progress_bar=False)
    embeddings = embeddings.astype(np.float32)
    embeddings = _normalize(embeddings)

    index.add(embeddings)
    documents.extend(text_list)

    if meta_list is None:
        meta_list = [{"source": "unknown", "chunk_id": i} for i in range(len(text_list))]
    metas.extend(meta_list)

def retrieve(query, top_k=3, min_score=0.15):
    """
    Retrieve top-k most relevant text chunks for a query.

    With cosine similarity (inner product on normalized vectors),
    scores are in [-1, 1], and higher is better.

    Inputs:
      - query (str)
      - top_k (int)
      - min_score (float)
    Output:
      - list of dicts: {"text": ..., "source": ..., "chunk_id": ..., "score": ...}
    """
    if len(documents) == 0:
        return []

    query_vec = embedder.encode([query], convert_to_numpy=True, show_progress_bar=False).astype(np.float32)
    query_vec = _normalize(query_vec)

    scores, indices = index.search(query_vec, top_k)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0 or idx >= len(documents):
            continue
        if float(score) < float(min_score):
            continue
        m = metas[idx]
        results.append({
            "text": documents[idx],
            "source": m.get("source", "unknown"),
            "chunk_id": m.get("chunk_id", -1),
            "score": float(score),
        })
    return results

def _chunk_text_by_chars(text: str, chunk_size=900, overlap=150):
    """
    Character-based chunking with overlap, but less destructive than fixed 500.
    This preserves more sentence continuity.

    Formula name: Sliding window chunking
    Formula:
      start_0 = 0
      start_{k+1} = start_k + (chunk_size - overlap)
      chunk_k = text[start_k : start_k + chunk_size]
    Inputs:
      - chunk_size
      - overlap
    """
    text = (text or "").strip()
    if not text:
        return []

    step = max(1, chunk_size - overlap)
    chunks = []
    for start in range(0, len(text), step):
        chunk = text[start:start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
    return chunks

def load_txt_files(folder_path):
    """Loads all .txt files from a folder and indexes them."""
    all_chunks = []
    all_meta = []

    for filename in os.listdir(folder_path):
        if not filename.endswith(".txt"):
            continue

        fullpath = os.path.join(folder_path, filename)
        with open(fullpath, "r", encoding="utf-8") as f:
            content = f.read()

        chunks = _chunk_text_by_chars(content, chunk_size=900, overlap=150)
        for i, ch in enumerate(chunks):
            all_chunks.append(ch)
            all_meta.append({"source": filename, "chunk_id": i})

    add_documents(all_chunks, all_meta)

def load_pdf_files(folder_path):
    """Loads all .pdf files from a folder and indexes them."""
    all_chunks = []
    all_meta = []

    for filename in os.listdir(folder_path):
        if not filename.endswith(".pdf"):
            continue

        fullpath = os.path.join(folder_path, filename)
        reader = PdfReader(fullpath)

        # Extract per page so you can keep page boundaries if you want later
        for page_idx, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            chunks = _chunk_text_by_chars(page_text, chunk_size=900, overlap=150)

            for i, ch in enumerate(chunks):
                all_chunks.append(ch)
                all_meta.append({"source": f"{filename}:page{page_idx+1}", "chunk_id": i})

    add_documents(all_chunks, all_meta)