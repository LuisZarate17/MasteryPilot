# rag.py
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import os
import re
import pickle
import json
from PyPDF2 import PdfReader

try:
    import docx as _docx
    _DOCX_AVAILABLE = True
except ImportError:
    _DOCX_AVAILABLE = False

# ── Tuneable constants ────────────────────────────────────────────────────────
CHUNK_SIZE    = 400   # target characters per chunk
CHUNK_OVERLAP = 80    # characters carried forward into the next chunk
TOP_K         = 5     # candidates retrieved before threshold filtering
MIN_SCORE     = 0.25  # cosine similarity floor (0.0–1.0); chunks below are dropped
IVF_THRESHOLD = 1000  # switch to approximate IVF index above this many chunks

# ── Persistence paths ─────────────────────────────────────────────────────────
_BASE      = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.getenv("RAG_INDEX_PATH", os.path.join(_BASE, "curriculum.faiss"))
DOCS_PATH  = INDEX_PATH.replace(".faiss", "_docs.pkl")

# ── Embedding model + FAISS index ─────────────────────────────────────────────
embedder  = SentenceTransformer("all-MiniLM-L6-v2")
dimension = 384
index     = faiss.IndexFlatIP(dimension)   # inner product == cosine after L2-norm
documents = []   # list of {"text": str, "source": str, "chunk_idx": int}

# Guard against loading the curriculum more than once per process
_curriculum_loaded = False


# ─────────────────────────────────────────────────────────────────────────────
# Chunking
# ─────────────────────────────────────────────────────────────────────────────

def chunk_text(text, source):
    """
    Split text into sentence-boundary-aware chunks with overlap.
    Returns list of {"text": str, "source": str, "chunk_idx": int}.
    """
    sentences = re.split(r'(?<=[.!?])\s+|\n{2,}', text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks = []
    current = ""
    idx = 0

    for sentence in sentences:
        # Sentence alone exceeds chunk size — flush buffer then hard-split it
        if len(sentence) > CHUNK_SIZE:
            if current:
                chunks.append({"text": current, "source": source, "chunk_idx": idx})
                idx += 1
                current = current[-CHUNK_OVERLAP:] if len(current) > CHUNK_OVERLAP else ""
            for i in range(0, len(sentence), CHUNK_SIZE - CHUNK_OVERLAP):
                piece = sentence[i:i + CHUNK_SIZE]
                if piece.strip():
                    chunks.append({"text": piece, "source": source, "chunk_idx": idx})
                    idx += 1
            current = sentence[-CHUNK_OVERLAP:]
            continue

        candidate = (current + " " + sentence).strip() if current else sentence
        if len(candidate) > CHUNK_SIZE and current:
            chunks.append({"text": current, "source": source, "chunk_idx": idx})
            idx += 1
            overlap_tail = current[-CHUNK_OVERLAP:] if len(current) > CHUNK_OVERLAP else current
            current = (overlap_tail + " " + sentence).strip()
        else:
            current = candidate

    if current:
        chunks.append({"text": current, "source": source, "chunk_idx": idx})
    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# Index management
# ─────────────────────────────────────────────────────────────────────────────

def add_documents(chunk_dicts):
    """Embed chunks, L2-normalise, and add to FAISS index."""
    global documents
    if not chunk_dicts:
        return
    texts = [c["text"] for c in chunk_dicts]
    vecs = embedder.encode(texts, convert_to_numpy=True).astype("float32")
    faiss.normalize_L2(vecs)
    index.add(vecs)
    documents.extend(chunk_dicts)


def save_index():
    """Persist FAISS index and document metadata to disk."""
    faiss.write_index(index, INDEX_PATH)
    with open(DOCS_PATH, "wb") as f:
        pickle.dump(documents, f)
    print(f"[RAG] Index saved: {index.ntotal} vectors → {INDEX_PATH}")


def load_index():
    """Load FAISS index and document metadata from disk."""
    global index, documents
    index = faiss.read_index(INDEX_PATH)
    with open(DOCS_PATH, "rb") as f:
        documents = pickle.load(f)
    print(f"[RAG] Index loaded from disk: {index.ntotal} vectors")


def is_index_stale(curriculum_path):
    """Return True if the saved index is absent or older than any curriculum file."""
    if not os.path.exists(INDEX_PATH) or not os.path.exists(DOCS_PATH):
        return True
    index_mtime = os.path.getmtime(INDEX_PATH)
    for root, _dirs, files in os.walk(curriculum_path):
        for fname in files:
            if os.path.getmtime(os.path.join(root, fname)) > index_mtime:
                return True
    return False


def _maybe_upgrade_to_ivf():
    """If corpus exceeds IVF_THRESHOLD, replace flat index with approximate IVF."""
    global index
    n = index.ntotal
    if n < IVF_THRESHOLD or isinstance(index, faiss.IndexIVFFlat):
        return
    print(f"[RAG] {n} vectors — upgrading to approximate IVF index...")
    all_vecs = np.vstack([index.reconstruct(i) for i in range(n)]).astype("float32")
    nlist = min(100, n // 10)
    quantiser = faiss.IndexFlatIP(dimension)
    ivf = faiss.IndexIVFFlat(quantiser, dimension, nlist, faiss.METRIC_INNER_PRODUCT)
    ivf.train(all_vecs)
    ivf.add(all_vecs)
    ivf.nprobe = 10
    index = ivf
    print(f"[RAG] IVF index ready (nlist={nlist}, nprobe=10).")


def ensure_curriculum_loaded(curriculum_path):
    """
    Load curriculum into the index exactly once per process.
    Uses cached index file when fresh; rebuilds and saves when stale or absent.
    """
    global _curriculum_loaded
    if _curriculum_loaded:
        return
    _curriculum_loaded = True   # set early to prevent re-entry on error
    if not os.path.exists(curriculum_path):
        print("[RAG] No curriculum folder found. Skipping.")
        return
    if is_index_stale(curriculum_path):
        print(f"[RAG] Index stale or absent — rebuilding from {curriculum_path} ...")
        load_curriculum_folder(curriculum_path)
        _maybe_upgrade_to_ivf()
        save_index()
        print(f"[RAG] Curriculum indexed: {index.ntotal} chunks.")
    else:
        load_index()


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval
# ─────────────────────────────────────────────────────────────────────────────

def retrieve(query, top_k=TOP_K, min_score=MIN_SCORE):
    """
    Return chunk dicts relevant to *query*.
    Chunks with cosine similarity < min_score are dropped silently.
    Returns an empty list when nothing relevant exists.
    """
    if not documents:
        return []
    query_vec = embedder.encode([query], convert_to_numpy=True).astype("float32")
    faiss.normalize_L2(query_vec)
    k = min(top_k, len(documents))
    scores, indices = index.search(query_vec, k)
    results = []
    for score, i in zip(scores[0], indices[0]):
        if i < 0:
            continue
        if float(score) >= min_score:
            results.append(documents[i])
    return results


def build_rag_system_message(chunks):
    """Format retrieved chunks as a system-message string with source attribution."""
    if not chunks:
        return ""
    lines = ["[Curriculum Context]"]
    seen = set()
    for c in chunks:
        key = (c["source"], c["chunk_idx"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"\n[Source: {c['source']}, chunk {c['chunk_idx']}]")
        lines.append(c["text"])
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# File loaders
# ─────────────────────────────────────────────────────────────────────────────

def _rel_source(file_path, curriculum_root):
    """Return file_path relative to curriculum_root as the source label."""
    try:
        return os.path.relpath(file_path, curriculum_root)
    except ValueError:
        return os.path.basename(file_path)


def load_txt_files(folder_path, curriculum_root=None):
    root = curriculum_root or folder_path
    for filename in os.listdir(folder_path):
        if not filename.endswith(".txt"):
            continue
        filepath = os.path.join(folder_path, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(filepath, "r", encoding="latin-1") as f:
                content = f.read()
        add_documents(chunk_text(content, _rel_source(filepath, root)))


def load_pdf_files(folder_path, curriculum_root=None):
    root = curriculum_root or folder_path
    for filename in os.listdir(folder_path):
        if not filename.endswith(".pdf"):
            continue
        filepath = os.path.join(folder_path, filename)
        reader = PdfReader(filepath)
        text = "".join(page.extract_text() or "" for page in reader.pages)
        add_documents(chunk_text(text, _rel_source(filepath, root)))


def load_md_files(folder_path, curriculum_root=None):
    root = curriculum_root or folder_path
    for filename in os.listdir(folder_path):
        if not filename.endswith(".md"):
            continue
        filepath = os.path.join(folder_path, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(filepath, "r", encoding="latin-1") as f:
                content = f.read()
        # Strip common markdown syntax before chunking
        content = re.sub(r'!\[.*?\]\(.*?\)', '', content)
        content = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', content)
        content = re.sub(r'`{1,3}[\s\S]*?`{1,3}', '', content)
        content = re.sub(r'[*_]{1,2}([^*_\n]+)[*_]{1,2}', r'\1', content)
        content = re.sub(r'^#{1,6}\s+', '', content, flags=re.MULTILINE)
        add_documents(chunk_text(content, _rel_source(filepath, root)))


def load_docx_files(folder_path, curriculum_root=None):
    if not _DOCX_AVAILABLE:
        return
    root = curriculum_root or folder_path
    for filename in os.listdir(folder_path):
        if not filename.endswith(".docx"):
            continue
        filepath = os.path.join(folder_path, filename)
        doc = _docx.Document(filepath)
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        add_documents(chunk_text(text, _rel_source(filepath, root)))


def load_json_files(folder_path, curriculum_root=None):
    root = curriculum_root or folder_path
    for filename in os.listdir(folder_path):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(folder_path, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                title   = item.get("title", filename)
                content = item.get("content", "")
                if content:
                    source = _rel_source(filepath, root) + f"/{title}"
                    add_documents(chunk_text(content, source))


def load_all_files(folder_path, curriculum_root=None):
    """Load all supported file types from a single folder."""
    load_txt_files(folder_path, curriculum_root)
    load_pdf_files(folder_path, curriculum_root)
    load_md_files(folder_path, curriculum_root)
    load_docx_files(folder_path, curriculum_root)
    load_json_files(folder_path, curriculum_root)


def load_curriculum_folder(curriculum_path):
    """Load files from the curriculum root and all immediate subdirectories."""
    load_all_files(curriculum_path, curriculum_path)
    for entry in os.scandir(curriculum_path):
        if entry.is_dir():
            load_all_files(entry.path, curriculum_path)