"""Shared plumbing for the rag_eval and rag_check commands.

Underscore-prefixed so Django's command discovery skips it (find_commands
filters names beginning with an underscore).

Both commands need a real embedding model, so both only run where
requirements-llm.txt is installed. Neither is importable-heavy: the import of
rag stays inside the functions, matching the rest of the codebase.
"""

import contextlib
import json
import os
import shutil
import statistics
import tempfile

# Where the checked-in evaluation set lives.
EVAL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tests",
    "fixtures",
    "eval",
)
EVAL_CORPUS = os.path.join(EVAL_DIR, "corpus")
EVAL_QUERIES = os.path.join(EVAL_DIR, "queries.json")


class MissingStackError(RuntimeError):
    """The RAG stack is not installed in this environment."""


def require_stack():
    """Fail with an actionable message rather than a bare ImportError."""
    try:
        import faiss  # noqa: F401
        import sentence_transformers  # noqa: F401
    except ImportError as exc:
        raise MissingStackError(
            f"{exc}\n\n"
            "This command embeds text, so it needs the RAG stack:\n"
            "    pip install -r requirements-llm.txt\n\n"
            "The test suite deliberately runs without it. To exercise this path in "
            "CI, dispatch the 'rag-verify' workflow."
        ) from exc


@contextlib.contextmanager
def isolated_index(corpus_dir, chunk_size=None, chunk_overlap=None):
    """Build a throwaway index over *corpus_dir*, leaving the real one untouched.

    Every piece of module state rag owns is saved and restored, so running this
    inside a live process cannot corrupt the served index. The embedder is
    deliberately *not* reset: it is expensive to construct and is stateless
    across corpora, so repeated calls in one process reuse it.

    This function is the single seam that knows how rag stores its state. When
    that state moves onto a class, only this needs rewriting.
    """
    import rag

    owned = ("documents", "index", "_curriculum_loaded", "INDEX_PATH", "DOCS_PATH",
             "CHUNK_SIZE", "CHUNK_OVERLAP")
    saved = {name: getattr(rag, name) for name in owned}
    tmp = tempfile.mkdtemp(prefix="rag-eval-")
    try:
        rag.documents = []
        rag.index = None
        rag._curriculum_loaded = False
        # Set explicitly rather than derived, so this does not depend on how
        # the sidecar path is computed.
        rag.INDEX_PATH = os.path.join(tmp, "eval.faiss")
        rag.DOCS_PATH = os.path.join(tmp, "eval_docs.json")
        if chunk_size:
            rag.CHUNK_SIZE = chunk_size
        if chunk_overlap is not None:
            rag.CHUNK_OVERLAP = chunk_overlap

        rag.load_curriculum_folder(corpus_dir)
        yield rag
    finally:
        for name, value in saved.items():
            setattr(rag, name, value)
        shutil.rmtree(tmp, ignore_errors=True)


def load_query_set(path=EVAL_QUERIES):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)["queries"]


def _sources_of(hits):
    """Retrieved source labels, deduplicated, in rank order.

    The JSON loader appends '/<title>' to a source, so the document is the part
    before it. Everything else returns the relative path unchanged.
    """
    seen, ordered = set(), []
    for hit in hits:
        doc = hit.get("source", "").split("/")[0]
        if doc not in seen:
            seen.add(doc)
            ordered.append(doc)
    return ordered


def evaluate(rag_module, queries, top_k):
    """Run every query and return per-query rows plus aggregate metrics."""
    rows = []
    for spec in queries:
        hits = rag_module.retrieve(spec["query"], top_k=top_k)
        ranked = _sources_of(hits)
        relevant = set(spec.get("relevant") or [])

        rank = next((i for i, doc in enumerate(ranked) if doc in relevant), None)
        rows.append({
            "query": spec["query"],
            "kind": spec.get("kind", "unspecified"),
            "relevant": sorted(relevant),
            "retrieved": ranked,
            "hit": rank is not None,
            "reciprocal_rank": 1.0 / (rank + 1) if rank is not None else 0.0,
            # Off-topic queries succeed by returning nothing at all.
            "rejected": not hits,
            "scores": [h["score"] for h in hits if "score" in h],
            "relevant_scores": [
                h["score"] for h in hits
                if "score" in h and h.get("source", "").split("/")[0] in relevant
            ],
            "irrelevant_scores": [
                h["score"] for h in hits
                if "score" in h and h.get("source", "").split("/")[0] not in relevant
            ],
        })

    return rows, _aggregate(rows, top_k)


def _mean(values):
    return statistics.fmean(values) if values else None


def _aggregate(rows, top_k):
    answerable = [r for r in rows if r["relevant"]]
    unanswerable = [r for r in rows if not r["relevant"]]

    summary = {
        "top_k": top_k,
        "queries": len(rows),
        "answerable": len(answerable),
        f"hit_rate@{top_k}": _mean([float(r["hit"]) for r in answerable]),
        "mrr": _mean([r["reciprocal_rank"] for r in answerable]),
        "rejection_accuracy": _mean([float(r["rejected"]) for r in unanswerable]),
        "by_kind": {},
    }

    for kind in sorted({r["kind"] for r in rows}):
        group = [r for r in rows if r["kind"] == kind]
        scored = [r for r in group if r["relevant"]]
        summary["by_kind"][kind] = {
            "queries": len(group),
            "hit_rate": _mean([float(r["hit"]) for r in scored]),
            "mrr": _mean([r["reciprocal_rank"] for r in scored]),
            "rejection_accuracy": _mean(
                [float(r["rejected"]) for r in group if not r["relevant"]]
            ),
        }

    # Separation is only meaningful once retrieve() returns scores. Until then
    # every list is empty and this stays None rather than reporting a fake 0.0.
    relevant_scores = [s for r in answerable for s in r["relevant_scores"]]
    irrelevant_scores = [s for r in answerable for s in r["irrelevant_scores"]]
    if relevant_scores and irrelevant_scores:
        summary["score_separation"] = _mean(relevant_scores) - _mean(irrelevant_scores)
        summary["mean_relevant_score"] = _mean(relevant_scores)
        summary["mean_irrelevant_score"] = _mean(irrelevant_scores)
    else:
        summary["score_separation"] = None

    return summary


def format_metric(value):
    return "n/a" if value is None else f"{value:.3f}"
