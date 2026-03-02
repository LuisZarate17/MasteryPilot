# rag.py
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import os
from PyPDF2 import PdfReader

# Initialize embedding model and FAISS index
embedder = SentenceTransformer("all-MiniLM-L6-v2")
dimension = 384  # embedding size for all-MiniLM-L6-v2
index = faiss.IndexFlatL2(dimension)
documents = []  # Store document text for lookup

def add_documents(text_list):
    """Embed and store text documents in the FAISS index."""
    global documents
    embeddings = embedder.encode(text_list)
    index.add(np.array(embeddings))
    documents.extend(text_list)

def retrieve(query, top_k=3):
    """Retrieve top-k most relevant text chunks for a query."""
    if len(documents) == 0:
        return ["No context documents loaded."]
    query_vec = embedder.encode([query])
    distances, indices = index.search(np.array(query_vec), top_k)
    return [documents[i] for i in indices[0]]

def load_txt_files(folder_path):
    """Loads all .txt files from a folder and indexes them."""
    text_chunks = []
    for filename in os.listdir(folder_path):
        if filename.endswith(".txt"):
            with open(os.path.join(folder_path, filename), "r", encoding="utf-8") as f:
                content = f.read()
                # split long text into smaller chunks for better search
                chunks = [content[i:i+500] for i in range(0, len(content), 500)]
                text_chunks.extend(chunks)
    if text_chunks:
        add_documents(text_chunks)

def load_pdf_files(folder_path):
    """Loads all .pdf files from a folder and indexes them."""
    text_chunks = []
    for filename in os.listdir(folder_path):
        if filename.endswith(".pdf"):
            reader = PdfReader(os.path.join(folder_path, filename))
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            chunks = [text[i:i+500] for i in range(0, len(text), 500)]
            text_chunks.extend(chunks)
    if text_chunks:
        add_documents(text_chunks)