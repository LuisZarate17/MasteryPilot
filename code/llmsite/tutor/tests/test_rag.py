"""RAG: chunking, staleness, retrieval and curriculum loading.

None of this needs sentence-transformers, faiss, numpy or PyPDF2. That is the
point of the lazy-import refactor — rag.py used to build a real embedder and
FAISS index at import time, so `import rag` failed outright on the core
install and none of this logic could be reached at all.

The two functions that genuinely embed or search (add_documents, retrieve's
scoring path) are exercised with a fake index rather than a real one; the
arithmetic under test is the threshold and sentinel handling, not FAISS.
"""

import os
import tempfile

from django.test import SimpleTestCase

import rag


class RagTestCase(SimpleTestCase):
    """rag keeps process-global state; every test starts from a clean slate."""

    STATE = ("documents", "_curriculum_loaded", "index", "embedder", "INDEX_PATH", "DOCS_PATH")

    def setUp(self):
        self._saved = {name: getattr(rag, name) for name in self.STATE}
        rag.documents = []
        rag._curriculum_loaded = False
        rag.index = None
        rag.embedder = None

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(rag, name, value)


class ChunkTextTests(RagTestCase):
    def test_short_text_is_one_chunk(self):
        chunks = rag.chunk_text("A short sentence.", "s.txt")

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["text"], "A short sentence.")
        self.assertEqual(chunks[0]["source"], "s.txt")
        self.assertEqual(chunks[0]["chunk_idx"], 0)

    def test_empty_and_whitespace_input_yields_nothing(self):
        for text in ("", "   ", "\n\n\t"):
            with self.subTest(text=repr(text)):
                self.assertEqual(rag.chunk_text(text, "s.txt"), [])

    def test_chunk_indices_are_contiguous_from_zero(self):
        text = " ".join(f"Sentence number {i} with some padding to add length." for i in range(60))

        chunks = rag.chunk_text(text, "s.txt")

        self.assertGreater(len(chunks), 1)
        self.assertEqual([c["chunk_idx"] for c in chunks], list(range(len(chunks))))

    def test_no_chunk_exceeds_the_configured_size(self):
        text = " ".join(f"Sentence {i} padded out a little further." for i in range(120))

        for chunk in rag.chunk_text(text, "s.txt"):
            self.assertLessEqual(len(chunk["text"]), rag.CHUNK_SIZE)

    def test_an_over_long_sentence_is_hard_split(self):
        """A single sentence longer than CHUNK_SIZE still has to fit."""
        text = "x" * (rag.CHUNK_SIZE * 3) + "."

        chunks = rag.chunk_text(text, "s.txt")

        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk["text"]), rag.CHUNK_SIZE)
        self.assertEqual([c["chunk_idx"] for c in chunks], list(range(len(chunks))))

    def test_flushing_before_a_hard_split_keeps_indices_contiguous(self):
        """Exercises the branch that used to carry a dead store.

        A normal sentence buffered, then an over-long one forcing a flush. The
        removed assignment was overwritten before it was ever read, so this
        pins that removing it changed nothing observable.
        """
        text = "Short lead sentence. " + "y" * (rag.CHUNK_SIZE * 2) + "."

        chunks = rag.chunk_text(text, "s.txt")

        self.assertEqual(chunks[0]["text"], "Short lead sentence.")
        self.assertEqual([c["chunk_idx"] for c in chunks], list(range(len(chunks))))

    def test_source_is_carried_onto_every_chunk(self):
        text = " ".join(f"Sentence {i} with padding." for i in range(80))

        for chunk in rag.chunk_text(text, "algebra/ch1.txt"):
            self.assertEqual(chunk["source"], "algebra/ch1.txt")


class IndexStalenessTests(RagTestCase):
    """Timestamps are set explicitly throughout.

    Writing the index and then the document and trusting wall-clock ordering is
    flaky: these tests run in single-digit milliseconds and the filesystem
    timestamp resolution is coarser than that, so both files land on the same
    mtime and the strict `>` comparison goes the wrong way.
    """

    OLD = 1_000_000  # 1970
    NEW = 2_000_000_000  # 2033

    def stamp(self, path, when):
        os.utime(path, (when, when))

    def write_index(self, tmp, when):
        rag.INDEX_PATH = os.path.join(tmp, "i.faiss")
        rag.DOCS_PATH = os.path.join(tmp, "i_docs.pkl")
        for path in (rag.INDEX_PATH, rag.DOCS_PATH):
            with open(path, "w") as f:
                f.write("x")
            self.stamp(path, when)

    def write_doc(self, folder, name, when):
        path = os.path.join(folder, name)
        with open(path, "w") as f:
            f.write("content")
        self.stamp(path, when)
        return path

    def test_missing_index_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            rag.INDEX_PATH = os.path.join(tmp, "absent.faiss")
            rag.DOCS_PATH = os.path.join(tmp, "absent_docs.pkl")

            self.assertTrue(rag.is_index_stale(tmp))

    def test_docs_sidecar_missing_is_stale(self):
        """Both halves must exist — an index without its metadata is useless."""
        with tempfile.TemporaryDirectory() as tmp:
            rag.INDEX_PATH = os.path.join(tmp, "i.faiss")
            rag.DOCS_PATH = os.path.join(tmp, "i_docs.pkl")
            with open(rag.INDEX_PATH, "w") as f:
                f.write("x")

            self.assertTrue(rag.is_index_stale(tmp))

    def test_index_newer_than_every_file_is_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            curriculum = os.path.join(tmp, "curriculum")
            os.makedirs(curriculum)
            self.write_doc(curriculum, "a.txt", self.OLD)
            self.write_index(tmp, self.NEW)

            self.assertFalse(rag.is_index_stale(curriculum))

    def test_a_file_newer_than_the_index_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            curriculum = os.path.join(tmp, "curriculum")
            os.makedirs(curriculum)
            self.write_index(tmp, self.OLD)
            self.write_doc(curriculum, "a.txt", self.NEW)

            self.assertTrue(rag.is_index_stale(curriculum))

    def test_staleness_looks_all_the_way_down_the_tree(self):
        """Nested files count — this is what load_curriculum_folder must match."""
        with tempfile.TemporaryDirectory() as tmp:
            curriculum = os.path.join(tmp, "curriculum")
            deep = os.path.join(curriculum, "unit1", "week2")
            os.makedirs(deep)
            self.write_index(tmp, self.OLD)
            self.write_doc(deep, "deep.txt", self.NEW)

            self.assertTrue(rag.is_index_stale(curriculum))


class BuildSystemMessageTests(RagTestCase):
    def test_no_chunks_yields_empty_string(self):
        """send_message branches on this being falsy."""
        self.assertEqual(rag.build_rag_system_message([]), "")

    def test_chunks_are_attributed_to_their_source(self):
        message = rag.build_rag_system_message(
            [{"text": "Fractions divide a whole.", "source": "ch1.txt", "chunk_idx": 0}]
        )

        self.assertIn("[Curriculum Context]", message)
        self.assertIn("[Source: ch1.txt, chunk 0]", message)
        self.assertIn("Fractions divide a whole.", message)

    def test_repeated_source_and_index_is_emitted_once(self):
        chunk = {"text": "Body", "source": "ch1.txt", "chunk_idx": 2}

        message = rag.build_rag_system_message([chunk, dict(chunk), dict(chunk)])

        self.assertEqual(message.count("[Source: ch1.txt, chunk 2]"), 1)

    def test_same_source_different_chunks_are_both_kept(self):
        message = rag.build_rag_system_message(
            [
                {"text": "One", "source": "ch1.txt", "chunk_idx": 0},
                {"text": "Two", "source": "ch1.txt", "chunk_idx": 1},
            ]
        )

        self.assertIn("chunk 0", message)
        self.assertIn("chunk 1", message)


class RelSourceTests(RagTestCase):
    def test_path_is_made_relative_to_the_curriculum_root(self):
        root = os.path.join("C:", os.sep, "curriculum")
        path = os.path.join(root, "unit1", "a.txt")

        self.assertEqual(rag._rel_source(path, root), os.path.join("unit1", "a.txt"))

    def test_same_directory_is_just_the_filename(self):
        root = os.path.join("C:", os.sep, "curriculum")

        self.assertEqual(rag._rel_source(os.path.join(root, "a.txt"), root), "a.txt")


class FakeIndex:
    """Minimal stand-in for a FAISS index — plain lists, no numpy."""

    def __init__(self, scores, indices):
        self._scores = scores
        self._indices = indices
        self.ntotal = len(indices[0])

    def search(self, _vec, _k):
        return self._scores, self._indices


class FakeEmbedder:
    def encode(self, _texts, convert_to_numpy=True):
        class _Vec:
            def astype(self, _dtype):
                return self

        return _Vec()


class RetrieveTests(RagTestCase):
    def install_fakes(self, scores, indices):
        rag.embedder = FakeEmbedder()
        rag.index = FakeIndex([scores], [indices])
        import sys
        import types

        fake_faiss = types.ModuleType("faiss")
        fake_faiss.normalize_L2 = lambda _v: None
        sys.modules["faiss"] = fake_faiss
        self.addCleanup(sys.modules.pop, "faiss", None)

    def test_empty_corpus_returns_nothing_without_touching_the_model(self):
        """The early return runs before any heavy call — no fakes needed."""
        self.assertEqual(rag.retrieve("anything"), [])

    def test_chunks_below_the_score_floor_are_dropped(self):
        rag.documents = [{"text": "keep"}, {"text": "drop"}]
        self.install_fakes([rag.MIN_SCORE + 0.1, rag.MIN_SCORE - 0.1], [0, 1])

        results = rag.retrieve("q")

        self.assertEqual(results, [{"text": "keep"}])

    def test_a_score_exactly_at_the_floor_is_kept(self):
        rag.documents = [{"text": "edge"}]
        self.install_fakes([rag.MIN_SCORE], [0])

        self.assertEqual(rag.retrieve("q"), [{"text": "edge"}])

    def test_the_negative_one_sentinel_is_skipped(self):
        """FAISS pads short result sets with -1."""
        rag.documents = [{"text": "real"}]
        self.install_fakes([0.9, 0.9], [0, -1])

        self.assertEqual(rag.retrieve("q"), [{"text": "real"}])


class EnsureCurriculumLoadedTests(RagTestCase):
    """Pure branching over five monkeypatchable callees."""

    def setUp(self):
        super().setUp()
        self.calls = []
        for name in ("load_curriculum_folder", "_maybe_upgrade_to_ivf", "save_index", "load_index"):
            self._patch(name)

    def _patch(self, name):
        original = getattr(rag, name)
        setattr(rag, name, lambda *a, _n=name, **k: self.calls.append(_n))
        self.addCleanup(setattr, rag, name, original)

    def test_a_second_call_is_a_no_op(self):
        rag._curriculum_loaded = True

        rag.ensure_curriculum_loaded("anywhere")

        self.assertEqual(self.calls, [])

    def test_a_missing_folder_is_skipped_but_still_marks_loaded(self):
        rag.ensure_curriculum_loaded(os.path.join("does", "not", "exist"))

        self.assertEqual(self.calls, [])
        self.assertTrue(rag._curriculum_loaded)

    def force_staleness(self, stale):
        original = rag.is_index_stale
        self.addCleanup(setattr, rag, "is_index_stale", original)
        rag.is_index_stale = lambda _p: stale

    def test_a_stale_index_is_rebuilt_and_saved(self):
        self.force_staleness(True)
        with tempfile.TemporaryDirectory() as tmp:
            rag.index = FakeIndex([[0.0]], [[0]])

            rag.ensure_curriculum_loaded(tmp)

        self.assertEqual(
            self.calls, ["load_curriculum_folder", "_maybe_upgrade_to_ivf", "save_index"]
        )

    def test_a_fresh_index_is_loaded_from_disk(self):
        self.force_staleness(False)
        with tempfile.TemporaryDirectory() as tmp:
            rag.ensure_curriculum_loaded(tmp)

        self.assertEqual(self.calls, ["load_index"])


class CurriculumWalkTests(RagTestCase):
    """load_curriculum_folder must cover the same tree is_index_stale checks."""

    def setUp(self):
        super().setUp()
        self.loaded = []
        original = rag.load_all_files
        rag.load_all_files = lambda folder, root=None: self.loaded.append(folder)
        self.addCleanup(setattr, rag, "load_all_files", original)

    def test_nested_directories_are_indexed(self):
        """Regression: the walk used to stop after immediate subdirectories.

        A file two levels down made is_index_stale (which uses os.walk) return
        True forever while never being indexed, so every startup rebuilt the
        entire corpus.
        """
        with tempfile.TemporaryDirectory() as tmp:
            deep = os.path.join(tmp, "unit1", "week2")
            os.makedirs(deep)
            with open(os.path.join(deep, "deep.txt"), "w") as f:
                f.write("content")

            rag.load_curriculum_folder(tmp)

            self.assertIn(deep, self.loaded)

    def test_the_root_itself_is_indexed(self):
        with tempfile.TemporaryDirectory() as tmp:
            rag.load_curriculum_folder(tmp)

            self.assertIn(tmp, self.loaded)


class FileLoaderTests(RagTestCase):
    def setUp(self):
        super().setUp()
        self.added = []
        original = rag.add_documents
        rag.add_documents = self.added.extend
        self.addCleanup(setattr, rag, "add_documents", original)

    def test_txt_files_are_chunked_with_a_relative_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = os.path.join(tmp, "unit1")
            os.makedirs(sub)
            with open(os.path.join(sub, "a.txt"), "w", encoding="utf-8") as f:
                f.write("Fractions divide a whole.")

            rag.load_txt_files(sub, tmp)

        self.assertEqual(len(self.added), 1)
        self.assertEqual(self.added[0]["source"], os.path.join("unit1", "a.txt"))

    def test_non_matching_extensions_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "notes.rtf"), "w") as f:
                f.write("ignored")

            rag.load_txt_files(tmp, tmp)

        self.assertEqual(self.added, [])

    def test_markdown_syntax_is_stripped_before_chunking(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "a.md"), "w", encoding="utf-8") as f:
                f.write("# Heading\n\nSee [the docs](http://x) and **bold** text.")

            rag.load_md_files(tmp, tmp)

        text = " ".join(c["text"] for c in self.added)
        self.assertNotIn("#", text)
        self.assertNotIn("http://x", text)
        self.assertIn("the docs", text)
        self.assertIn("bold", text)

    def test_json_records_become_chunks_titled_by_their_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "a.json"), "w", encoding="utf-8") as f:
                f.write('[{"title": "Ratios", "content": "A ratio compares two values."}]')

            rag.load_json_files(tmp, tmp)

        self.assertEqual(len(self.added), 1)
        self.assertTrue(self.added[0]["source"].endswith("Ratios"))

    def test_unparseable_json_is_skipped_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "bad.json"), "w", encoding="utf-8") as f:
                f.write("{not json")

            rag.load_json_files(tmp, tmp)

        self.assertEqual(self.added, [])

    def test_docx_loading_is_a_no_op_without_python_docx(self):
        """python-docx is in no requirements file; this path must stay safe."""
        with tempfile.TemporaryDirectory() as tmp:
            rag.load_docx_files(tmp, tmp)

        self.assertEqual(self.added, [])
