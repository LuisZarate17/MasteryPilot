"""Curriculum retrieval: chunking, embedding, FAISS index, search.

sentence-transformers, faiss, numpy and PyPDF2 are imported *inside* the
methods that need them, mirroring languagemodel.py. They live in
requirements-llm.txt, which is optional and is not installed for the test
suite, so importing this module must not drag them in — the embedder alone
would download and load a model at import time.

Everything that does not embed or search — chunking, staleness checks, source
labelling, message formatting, the loader dispatch — is therefore importable
and testable on the core install.

Structure
---------
``RagIndex`` owns everything stateful: the loaded documents, the FAISS index,
the embedder, and where those are persisted. ``default_index`` is the single
instance the application uses, and the module-level functions are thin wrappers
around it so existing callers (languagemodel.py) need no changes.

The reason for the class is that one corpus per process is a ceiling. Serving a
second curriculum — a different district, a different teacher — is now an
instantiation rather than a rewrite. Nothing in the codebase asks for that
today, so nothing here builds it; this only removes the obstacle.

Pure functions stay at module level, because they hold no state and belong to
no particular index: ``chunk_text``, ``_rel_source``, ``build_rag_system_message``.
"""

import os
import re
import json

# Bumped when the sidecar's shape changes. An unrecognised version is treated
# as unusable, which means "rebuild", not "crash".
SIDECAR_VERSION = 2

# ── Tuneable constants ────────────────────────────────────────────────────────
CHUNK_SIZE    = 400   # target characters per chunk
CHUNK_OVERLAP = 80    # characters carried forward into the next chunk
TOP_K         = 5     # candidates retrieved before threshold filtering
MIN_SCORE     = 0.25  # cosine similarity floor (0.0–1.0); chunks below are dropped
# Above this many chunks, swap exact search for approximate IVF. Raised from
# 1000: at that size nlist = min(100, n // 10) gave 100 centroids over 1000
# vectors, about 10 training points each, far below what FAISS wants — it warns
# and clusters badly. 20k vectors flat is ~30 MB and searches in milliseconds,
# so staying exact for longer costs little and can only improve recall.
IVF_THRESHOLD = 20_000

# ── Embedding model ───────────────────────────────────────────────────────────
# Swappable, but a swap invalidates every persisted index — see is_index_stale.
EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "all-MiniLM-L6-v2")

# all-MiniLM-L6-v2's width. Only a fallback for reporting before a model has
# been loaded: the real dimension is asked of the model, never assumed.
DEFAULT_DIMENSION = 384

# One model per name, shared by every index in the process. Embedders are
# stateless and large, so thirty corpora should not mean thirty copies in RAM.
_EMBEDDERS = {}


def get_shared_embedder(model_name=None):
    name = model_name or EMBED_MODEL
    if name not in _EMBEDDERS:
        from sentence_transformers import SentenceTransformer

        _EMBEDDERS[name] = SentenceTransformer(name)
    return _EMBEDDERS[name]

# ── Default persistence paths ─────────────────────────────────────────────────
# These configure the default instance. A non-default RagIndex derives its own
# paths from its curriculum directory.
_BASE      = os.path.dirname(os.path.abspath(__file__))


def sidecar_path_for(index_path):
    """Metadata path for *index_path*.

    splitext, not str.replace: replace substitutes every occurrence, so
    RAG_INDEX_PATH=/srv/.faiss-data/c.faiss used to resolve into a directory
    named _docs.json-data that does not exist, and any path without a .faiss
    extension produced a sidecar path equal to the index path, so the two
    writes silently destroyed each other.
    """
    return os.path.splitext(index_path)[0] + "_docs.json"


INDEX_PATH = os.getenv("RAG_INDEX_PATH", os.path.join(_BASE, "curriculum.faiss"))
DOCS_PATH  = sidecar_path_for(INDEX_PATH)


class IndexUnusable(RuntimeError):
    """A persisted index cannot be trusted and must be rebuilt.

    Never fatal. Every raise site is paired with a rebuild — the cache is an
    optimisation, and a corrupt one costs time, not correctness.
    """


# ─────────────────────────────────────────────────────────────────────────────
# Chunking — pure, stateless, shared by every index
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
                # No overlap carried here on purpose: the hard-split below
                # iterates `sentence`, not `current`, and sets `current` itself
                # afterwards. An assignment here would be a dead store.
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


def _rel_source(file_path, curriculum_root):
    """Return file_path relative to curriculum_root as the source label."""
    try:
        return os.path.relpath(file_path, curriculum_root)
    except ValueError:
        return os.path.basename(file_path)


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
# The index
# ─────────────────────────────────────────────────────────────────────────────

class RagIndex:
    """One curriculum corpus: its chunks, its vectors, and where they persist."""

    def __init__(self, curriculum_path=None, index_path=None, docs_path=None,
                 embed_model=None):
        self.curriculum_path = curriculum_path
        self.embed_model = embed_model or EMBED_MODEL

        # Asked of the model on first use, or read back from the sidecar.
        # Never assumed: a wrong width is the one mistake FAISS cannot detect
        # for you if the numbers happen to agree.
        self.dimension = None

        if index_path is None:
            # A derived path must sit *beside* the corpus, never inside it:
            # is_index_stale walks the corpus tree, so an index stored within
            # it would be newer than itself and stale on every single check.
            index_path = (
                INDEX_PATH if curriculum_path is None
                else os.path.normpath(curriculum_path) + ".faiss"
            )
        self.index_path = index_path
        self.docs_path = docs_path or sidecar_path_for(index_path)

        self.documents = []   # list of {"text": str, "source": str, "chunk_idx": int}

        # Built on first use rather than at construction — see the module docstring.
        self.embedder = None
        self.index = None

        # Manifest of the corpus this index currently holds, or None when
        # nothing is loaded. Comparing it against a fresh scan is what makes a
        # repeat load cheap and a changed corpus visible.
        self._loaded_manifest = None

    # ── Lazily built singletons ──────────────────────────────────────────────

    def get_embedder(self):
        """The sentence-transformers model, shared across indexes by name."""
        if self.embedder is None:
            self.embedder = get_shared_embedder(self.embed_model)
        return self.embedder

    def get_dimension(self):
        """Vector width, asked of the model rather than hardcoded.

        384 was written into the module as a constant beside a model name.
        Changing the model then produced an index of the wrong width — and if
        the replacement happened to be 384-wide too, nothing raised at all: the
        cache loaded, queries embedded, and every answer was drawn from vectors
        that meant something else.
        """
        if self.dimension is None:
            self.dimension = self.get_embedder().get_sentence_embedding_dimension()
        return self.dimension

    def get_index(self):
        """The FAISS index, created once per index."""
        if self.index is None:
            import faiss

            # Inner product == cosine once vectors are L2-normalised.
            self.index = faiss.IndexFlatIP(self.get_dimension())
        return self.index

    # ── Index management ─────────────────────────────────────────────────────

    def add_documents(self, chunk_dicts):
        """Embed chunks, L2-normalise, and add to FAISS index."""
        import faiss

        if not chunk_dicts:
            return
        texts = [c["text"] for c in chunk_dicts]
        vecs = self.get_embedder().encode(texts, convert_to_numpy=True).astype("float32")
        faiss.normalize_L2(vecs)
        self.get_index().add(vecs)
        self.documents.extend(chunk_dicts)

    @property
    def ntotal(self):
        """Vectors held, without forcing an index (hence a model) into being."""
        return 0 if self.index is None else self.index.ntotal

    def _sidecar_payload(self, manifest):
        """The metadata written beside the vectors."""
        return {
            "version": SIDECAR_VERSION,
            "ntotal": self.ntotal,
            "embed_model": self.embed_model,
            "dimension": self.dimension,
            "corpus": self._corpus_key(self.curriculum_path),
            "manifest": manifest,
            "documents": self.documents,
        }

    def _write_sidecar(self, payload):
        """Write the sidecar atomically.

        Written to a temporary file and renamed, because os.replace is atomic
        on both POSIX and Windows. Without it, two workers rebuilding at once —
        or a crash mid-write — leave a half-written file that parses to
        nothing useful.
        """
        tmp = self.docs_path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, self.docs_path)

    def _read_sidecar(self):
        try:
            with open(self.docs_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except FileNotFoundError as exc:
            raise IndexUnusable("metadata sidecar is missing") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            # Also the path a pre-JSON pickle sidecar takes, if one is still
            # sitting on disk under the old name.
            raise IndexUnusable(f"metadata sidecar is unreadable: {exc}") from exc

        if not isinstance(payload, dict) or payload.get("version") != SIDECAR_VERSION:
            raise IndexUnusable(
                f"metadata sidecar version {payload.get('version') if isinstance(payload, dict) else '?'} "
                f"is not {SIDECAR_VERSION}"
            )
        return payload

    def save_index(self, manifest=None):
        """Persist FAISS index and document metadata to disk.

        Vectors first, metadata last. The sidecar is the commit record: if it
        is absent or disagrees with the vectors, load_index refuses and the
        corpus is rebuilt. That is what makes a crash between the two writes
        cost a rebuild rather than silently misattributing chunks.
        """
        import faiss

        payload = self._sidecar_payload(manifest if manifest is not None else {})
        # An empty corpus has no vectors to write, and building an index for it
        # would mean downloading a model to describe nothing.
        if self.index is not None:
            faiss.write_index(self.index, self.index_path)
        self._write_sidecar(payload)
        print(f"[RAG] Index saved: {payload['ntotal']} vectors → {self.index_path}")

    def load_index(self):
        """Load FAISS index and document metadata from disk.

        Raises IndexUnusable rather than loading a mismatched pair. retrieve()
        looks documents up by the position FAISS returns, so an index and a
        sidecar describing different corpora do not error — they answer with
        the wrong text under the wrong source, which is worse.
        """
        import faiss

        payload = self._read_sidecar()

        recorded_model = payload.get("embed_model")
        if recorded_model != self.embed_model:
            raise IndexUnusable(
                f"index was built with {recorded_model!r}, this process uses "
                f"{self.embed_model!r}"
            )

        documents = payload["documents"]
        if payload["ntotal"] == 0:
            # Nothing was indexed, so there is no vector file to read.
            self.index = None
            self.documents = []
            print("[RAG] Index loaded from disk: empty corpus")
            return

        try:
            index = faiss.read_index(self.index_path)
        except Exception as exc:
            raise IndexUnusable(f"vector index is unreadable: {exc}") from exc

        if index.ntotal != payload["ntotal"]:
            raise IndexUnusable(
                f"vector count {index.ntotal} does not match the recorded {payload['ntotal']}"
            )
        if len(documents) != index.ntotal:
            raise IndexUnusable(
                f"{len(documents)} documents against {index.ntotal} vectors"
            )

        self.index = index
        self.documents = documents
        # Taken from the file, so reopening an index never has to load a model
        # just to learn how wide its vectors are.
        self.dimension = payload.get("dimension") or index.d
        print(f"[RAG] Index loaded from disk: {index.ntotal} vectors")

    # ── Corpus fingerprinting ────────────────────────────────────────────────

    @staticmethod
    def _corpus_key(curriculum_path):
        """Stable identity for a corpus directory."""
        if not curriculum_path:
            return None
        return os.path.normcase(os.path.abspath(curriculum_path))

    @staticmethod
    def scan_manifest(curriculum_path):
        """Describe every file under *curriculum_path* as {relpath: [mtime, size]}.

        Separators are normalised to "/" so a manifest written on Windows
        compares equal to the same corpus read on Linux.
        """
        manifest = {}
        for root, _dirs, files in os.walk(curriculum_path):
            for fname in files:
                full = os.path.join(root, fname)
                try:
                    stat = os.stat(full)
                except OSError:
                    # Vanished between listing and stat; the next scan settles it.
                    continue
                rel = os.path.relpath(full, curriculum_path).replace(os.sep, "/")
                manifest[rel] = [stat.st_mtime, stat.st_size]
        return manifest

    def _saved_fingerprint(self):
        """(corpus key, manifest) recorded in the sidecar, or (None, None).

        The sidecar alone is consulted: it is the commit record, and an empty
        corpus legitimately has no vector file beside it.
        """
        try:
            payload = self._read_sidecar()
        except IndexUnusable:
            return None, None
        if payload.get("embed_model") != self.embed_model:
            return None, None
        return payload.get("corpus"), payload.get("manifest")

    def is_index_stale(self, curriculum_path, manifest=None):
        """Return True unless the saved index describes exactly this corpus.

        Compares a manifest of every file, not mtimes against the index. The
        old check asked "is any file newer than the index", which cannot express
        a file that no longer exists — so deleting curriculum through the
        dashboard left its chunks being retrieved and quoted to students
        forever, across restarts, with no way to stop it short of deleting the
        index by hand.

        A set comparison catches all three cases: added, modified, and removed.
        """
        saved_corpus, saved_manifest = self._saved_fingerprint()
        if saved_manifest is None:
            return True
        if saved_corpus != self._corpus_key(curriculum_path):
            return True
        if manifest is None:
            manifest = self.scan_manifest(curriculum_path)
        return saved_manifest != manifest

    def _maybe_upgrade_to_ivf(self):
        """If corpus exceeds IVF_THRESHOLD, replace flat index with approximate IVF."""
        # Nothing indexed: no index to upgrade, and no reason to load a model —
        # or, since the guard precedes the import, to require faiss at all.
        if self.index is None:
            return

        import faiss

        index = self.index
        n = index.ntotal
        if n < IVF_THRESHOLD or isinstance(index, faiss.IndexIVFFlat):
            return
        print(f"[RAG] {n} vectors — upgrading to approximate IVF index...")
        all_vecs = index.reconstruct_n(0, n)
        nlist = min(100, n // 10)
        width = self.get_dimension()
        quantiser = faiss.IndexFlatIP(width)
        ivf = faiss.IndexIVFFlat(quantiser, width, nlist, faiss.METRIC_INNER_PRODUCT)
        ivf.train(all_vecs)
        ivf.add(all_vecs)
        ivf.nprobe = 10
        self.index = ivf
        print(f"[RAG] IVF index ready (nlist={nlist}, nprobe=10).")

    def ensure_curriculum_loaded(self, curriculum_path=None):
        """Make this index reflect the corpus on disk, right now.

        Re-checks on every call rather than latching after the first. The latch
        it replaces had two problems. It was set *before* indexing ran, on the
        reasoning that this prevented re-entry on error — so a single
        unreadable PDF left the process serving a half-built index for its
        entire lifetime, silently and with no log line. And because it never
        cleared, a curriculum change could not take effect without a restart,
        which is the other half of why deleted content kept being served.

        The cost of re-checking is one os.walk plus a stat per file. This runs
        when a chat session opens, not per message, so that is not a hot path.
        """
        curriculum_path = curriculum_path or self.curriculum_path
        self.curriculum_path = curriculum_path

        if not curriculum_path or not os.path.exists(curriculum_path):
            print("[RAG] No curriculum folder found. Skipping.")
            return

        current = self.scan_manifest(curriculum_path)

        # Already serving exactly this corpus — nothing to do.
        if self._loaded_manifest == current and self.documents:
            return

        if not self.is_index_stale(curriculum_path, current):
            try:
                self.load_index()
                self._loaded_manifest = current
                return
            except IndexUnusable as exc:
                print(f"[RAG] Cached index rejected ({exc}) — rebuilding.")

        print(f"[RAG] Curriculum changed or unindexed — rebuilding from {curriculum_path} ...")
        self._rebuild(curriculum_path, current)

    def invalidate(self):
        """Forget what is loaded, so the next load re-reads the corpus.

        Called when curriculum is uploaded or deleted. Strictly this is belt
        and braces — ensure_curriculum_loaded re-scans anyway — but it makes
        the coupling between the dashboard and the index explicit rather than
        incidental.

        Note the scope: this clears *this process*. Under multiple gunicorn
        workers, the others pick the change up at their next session start.
        """
        self._loaded_manifest = None

    def _rebuild(self, curriculum_path, manifest=None):
        """Index the corpus from scratch and persist the result.

        Resetting documents and index first is what evicts deleted content:
        chunks are not removed one by one, the corpus is simply re-read, and
        anything no longer on disk is no longer in it. That is deliberately
        the dumb approach. Incremental removal means FAISS remove_ids, which
        compacts and renumbers a flat index while `documents` is a parallel
        Python list — and a desync there does not raise, it answers with the
        wrong text under the wrong source. Rebuilding a pilot corpus takes
        seconds and cannot get that wrong.
        """
        if manifest is None:
            manifest = self.scan_manifest(curriculum_path)

        self.documents = []
        self.index = None

        self.load_curriculum_folder(curriculum_path)
        self._maybe_upgrade_to_ivf()
        self.save_index(manifest)
        self._loaded_manifest = manifest
        print(f"[RAG] Curriculum indexed: {len(self.documents)} chunks.")

    # ── Retrieval ────────────────────────────────────────────────────────────

    def retrieve(self, query, top_k=TOP_K, min_score=MIN_SCORE):
        """
        Return chunk dicts relevant to *query*.
        Chunks with cosine similarity < min_score are dropped silently.
        Returns an empty list when nothing relevant exists.
        """
        if not self.documents:
            return []
        import faiss

        query_vec = self.get_embedder().encode([query], convert_to_numpy=True).astype("float32")
        faiss.normalize_L2(query_vec)
        k = min(top_k, len(self.documents))
        scores, indices = self.get_index().search(query_vec, k)
        results = []
        for score, i in zip(scores[0], indices[0]):
            if i < 0:
                continue
            if float(score) >= min_score:
                results.append(self.documents[i])
        return results

    # ── File loaders ─────────────────────────────────────────────────────────

    def load_txt_files(self, folder_path, curriculum_root=None):
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
            self.add_documents(chunk_text(content, _rel_source(filepath, root)))

    def load_pdf_files(self, folder_path, curriculum_root=None):
        from PyPDF2 import PdfReader

        root = curriculum_root or folder_path
        for filename in os.listdir(folder_path):
            if not filename.endswith(".pdf"):
                continue
            filepath = os.path.join(folder_path, filename)
            reader = PdfReader(filepath)
            text = "".join(page.extract_text() or "" for page in reader.pages)
            self.add_documents(chunk_text(text, _rel_source(filepath, root)))

    def load_md_files(self, folder_path, curriculum_root=None):
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
            self.add_documents(chunk_text(content, _rel_source(filepath, root)))

    def load_docx_files(self, folder_path, curriculum_root=None):
        try:
            import docx as _docx
        except ImportError:
            return
        root = curriculum_root or folder_path
        for filename in os.listdir(folder_path):
            if not filename.endswith(".docx"):
                continue
            filepath = os.path.join(folder_path, filename)
            doc = _docx.Document(filepath)
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            self.add_documents(chunk_text(text, _rel_source(filepath, root)))

    def load_json_files(self, folder_path, curriculum_root=None):
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
                        self.add_documents(chunk_text(content, source))

    def load_all_files(self, folder_path, curriculum_root=None):
        """Load all supported file types from a single folder."""
        self.load_txt_files(folder_path, curriculum_root)
        self.load_pdf_files(folder_path, curriculum_root)
        self.load_md_files(folder_path, curriculum_root)
        self.load_docx_files(folder_path, curriculum_root)
        self.load_json_files(folder_path, curriculum_root)

    def load_curriculum_folder(self, curriculum_path):
        """Load files from the curriculum root and every subdirectory below it.

        This walks the full tree to match is_index_stale, which uses os.walk. It
        used to descend only one level, so a file nested two deep made the index
        permanently stale — it was newer than the index, but indexing never picked
        it up — and every startup rebuilt the whole corpus.
        """
        for root, _dirs, _files in os.walk(curriculum_path):
            self.load_all_files(root, curriculum_path)


# ─────────────────────────────────────────────────────────────────────────────
# The default instance, and the module-level API that delegates to it
# ─────────────────────────────────────────────────────────────────────────────

default_index = RagIndex()


def get_embedder():
    return default_index.get_embedder()


def get_index():
    return default_index.get_index()


def add_documents(chunk_dicts):
    return default_index.add_documents(chunk_dicts)


def save_index(manifest=None):
    return default_index.save_index(manifest)


def scan_manifest(curriculum_path):
    return RagIndex.scan_manifest(curriculum_path)


def invalidate():
    return default_index.invalidate()


def load_index():
    return default_index.load_index()


def is_index_stale(curriculum_path):
    return default_index.is_index_stale(curriculum_path)


def _maybe_upgrade_to_ivf():
    return default_index._maybe_upgrade_to_ivf()


def ensure_curriculum_loaded(curriculum_path=None):
    return default_index.ensure_curriculum_loaded(curriculum_path)


def retrieve(query, top_k=TOP_K, min_score=MIN_SCORE):
    return default_index.retrieve(query, top_k=top_k, min_score=min_score)


def load_txt_files(folder_path, curriculum_root=None):
    return default_index.load_txt_files(folder_path, curriculum_root)


def load_pdf_files(folder_path, curriculum_root=None):
    return default_index.load_pdf_files(folder_path, curriculum_root)


def load_md_files(folder_path, curriculum_root=None):
    return default_index.load_md_files(folder_path, curriculum_root)


def load_docx_files(folder_path, curriculum_root=None):
    return default_index.load_docx_files(folder_path, curriculum_root)


def load_json_files(folder_path, curriculum_root=None):
    return default_index.load_json_files(folder_path, curriculum_root)


def load_all_files(folder_path, curriculum_root=None):
    return default_index.load_all_files(folder_path, curriculum_root)


def load_curriculum_folder(curriculum_path):
    return default_index.load_curriculum_folder(curriculum_path)
