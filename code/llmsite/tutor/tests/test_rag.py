"""RAG: chunking, staleness, retrieval and curriculum loading.

None of this needs sentence-transformers, faiss, numpy or PyPDF2. That is the
point of the lazy-import refactor — rag.py used to build a real embedder and
FAISS index at import time, so `import rag` failed outright on the core
install and none of this logic could be reached at all.

The two functions that genuinely embed or search (add_documents, retrieve's
scoring path) are exercised with a fake index rather than a real one; the
arithmetic under test is the threshold and sentinel handling, not FAISS.
"""

import json
import os
import tempfile

from django.test import SimpleTestCase

import rag


class RagTestCase(SimpleTestCase):
    """rag state lives on a default RagIndex; every test gets a fresh one.

    Swapping the whole instance is why this is four lines rather than the
    six-name save/restore it replaced: paths, documents, embedder and index all
    travel together, so there is nothing left to forget.

    The module-level functions look ``default_index`` up at call time, so
    rebinding it here redirects them without touching any caller.
    """

    def setUp(self):
        self._saved_default = rag.default_index
        rag.default_index = rag.RagIndex()

    def tearDown(self):
        rag.default_index = self._saved_default


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
    """Staleness is a manifest comparison, not an mtime race.

    These tests changed with the mechanism, because they encoded the mechanism
    — and the mechanism was the defect. The old check asked "is any curriculum
    file newer than the index", which cannot express a file that no longer
    exists, so a deleted document went on being retrieved forever.

    Every original test's *intent* survives below: a missing index is stale, a
    missing sidecar is stale, an unchanged corpus is fresh, a modified file is
    stale, nested files count. What is gone is the timestamp stamping those
    tests needed — the suite runs in single-digit milliseconds and filesystem
    timestamp resolution is coarser, so index and document landed on the same
    mtime and a strict `>` went the wrong way. A manifest has no such race.

    What is new is the case that could not be written before: deletion.
    """

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.curriculum = os.path.join(self.tmp.name, "curriculum")
        os.makedirs(self.curriculum)

        index = rag.default_index
        index.index_path = os.path.join(self.tmp.name, "i.faiss")
        index.docs_path = rag.sidecar_path_for(index.index_path)
        index.curriculum_path = self.curriculum

    def write_doc(self, name, content="content", folder=None):
        folder = folder or self.curriculum
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def record_index(self):
        """Persist an index describing the corpus exactly as it stands now."""
        index = rag.default_index
        with open(index.index_path, "w") as handle:
            handle.write("vectors")
        index._write_sidecar({
            "version": rag.SIDECAR_VERSION,
            "ntotal": 0,
            "embed_model": index.embed_model,
            "dimension": None,
            "corpus": index._corpus_key(self.curriculum),
            "manifest": rag.scan_manifest(self.curriculum),
            "documents": [],
        })

    # ── Intent carried over from the mtime era ───────────────────────────────

    def test_missing_index_is_stale(self):
        self.assertTrue(rag.is_index_stale(self.curriculum))

    def test_docs_sidecar_missing_is_stale(self):
        """Both halves must exist — an index without its metadata is useless."""
        with open(rag.default_index.index_path, "w") as handle:
            handle.write("vectors")

        self.assertTrue(rag.is_index_stale(self.curriculum))

    def test_an_unchanged_corpus_is_fresh(self):
        self.write_doc("a.txt")
        self.record_index()

        self.assertFalse(rag.is_index_stale(self.curriculum))

    def test_a_modified_file_is_stale(self):
        self.write_doc("a.txt")
        self.record_index()
        self.write_doc("a.txt", content="content, revised and longer")

        self.assertTrue(rag.is_index_stale(self.curriculum))

    def test_a_file_edited_without_changing_its_size_is_stale(self):
        """Size alone is not enough; the manifest records mtime too."""
        path = self.write_doc("a.txt", content="aaaa")
        self.record_index()
        self.write_doc("a.txt", content="bbbb")
        os.utime(path, (2_000_000_000, 2_000_000_000))

        self.assertTrue(rag.is_index_stale(self.curriculum))

    def test_staleness_looks_all_the_way_down_the_tree(self):
        """Nested files count — this is what load_curriculum_folder must match."""
        deep = os.path.join(self.curriculum, "unit1", "week2")
        self.write_doc("deep.txt", folder=deep)
        self.record_index()
        self.write_doc("another.txt", folder=deep)

        self.assertTrue(rag.is_index_stale(self.curriculum))

    # ── The case the old mechanism could not express ─────────────────────────

    def test_a_deleted_file_makes_the_index_stale(self):
        """The defect. A district pulling a document could not make it stop.

        mtime comparison only ever looks forward: nothing on disk is newer than
        the index once a file is gone, so the index looked fresh and its chunks
        kept being retrieved and quoted to students — across restarts, with no
        way to stop it short of deleting the index by hand.
        """
        self.write_doc("keep.txt")
        removed = self.write_doc("remove_me.txt")
        self.record_index()

        os.remove(removed)

        self.assertTrue(rag.is_index_stale(self.curriculum))

    def test_a_deleted_nested_file_makes_the_index_stale(self):
        deep = os.path.join(self.curriculum, "unit1", "week2")
        removed = self.write_doc("deep.txt", folder=deep)
        self.record_index()

        os.remove(removed)

        self.assertTrue(rag.is_index_stale(self.curriculum))

    def test_emptying_the_corpus_entirely_is_stale(self):
        removed = self.write_doc("only.txt")
        self.record_index()

        os.remove(removed)

        self.assertTrue(rag.is_index_stale(self.curriculum))

    def test_an_added_file_is_stale(self):
        self.write_doc("a.txt")
        self.record_index()
        self.write_doc("b.txt")

        self.assertTrue(rag.is_index_stale(self.curriculum))

    def test_an_index_built_from_a_different_directory_is_stale(self):
        """Relative manifest keys could otherwise collide across corpora."""
        self.write_doc("a.txt")
        self.record_index()

        other = os.path.join(self.tmp.name, "other")
        os.makedirs(other)
        with open(os.path.join(other, "a.txt"), "w", encoding="utf-8") as handle:
            handle.write("content")

        self.assertTrue(rag.is_index_stale(other))


class ManifestTests(RagTestCase):
    """The manifest itself: what it records and how it compares."""

    def test_it_records_every_file_in_the_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "unit1"))
            for rel in ("a.txt", os.path.join("unit1", "b.txt")):
                with open(os.path.join(tmp, rel), "w", encoding="utf-8") as handle:
                    handle.write("x")

            manifest = rag.scan_manifest(tmp)

            self.assertEqual(set(manifest), {"a.txt", "unit1/b.txt"})

    def test_separators_are_normalised_so_platforms_agree(self):
        """A manifest written on Windows must compare equal on Linux."""
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "unit1"))
            with open(os.path.join(tmp, "unit1", "b.txt"), "w", encoding="utf-8") as handle:
                handle.write("x")

            self.assertIn("unit1/b.txt", rag.scan_manifest(tmp))
            self.assertNotIn("\\", "".join(rag.scan_manifest(tmp)))

    def test_an_empty_directory_yields_an_empty_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(rag.scan_manifest(tmp), {})

    def test_it_survives_a_json_round_trip_unchanged(self):
        """It is compared after being read back out of the sidecar."""
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8") as handle:
                handle.write("content")
            manifest = rag.scan_manifest(tmp)

            self.assertEqual(json.loads(json.dumps(manifest)), manifest)


class SidecarPathTests(RagTestCase):
    """str.replace substitutes every occurrence; splitext does not."""

    def test_a_dot_faiss_directory_does_not_get_rewritten(self):
        """RAG_INDEX_PATH pointing into a .faiss-named directory used to break.

        The old derivation rewrote the directory too, aiming the sidecar at
        /srv/_docs.json-data/, which does not exist.
        """
        derived = rag.sidecar_path_for(os.path.join(os.sep, "srv", ".faiss-data", "c.faiss"))

        self.assertEqual(
            derived, os.path.join(os.sep, "srv", ".faiss-data", "c_docs.json")
        )

    def test_an_extensionless_path_still_gets_a_distinct_sidecar(self):
        """Equal paths meant the two writes destroyed each other."""
        index_path = os.path.join(os.sep, "data", "index")

        self.assertNotEqual(rag.sidecar_path_for(index_path), index_path)

    def test_the_sidecar_is_json_not_pickle(self):
        self.assertTrue(rag.sidecar_path_for("a.faiss").endswith("_docs.json"))

    def test_an_instance_derives_its_sidecar_from_its_index_path(self):
        index = rag.RagIndex(index_path=os.path.join("tmp", "corpus.faiss"))

        self.assertEqual(index.docs_path, os.path.join("tmp", "corpus_docs.json"))


class FakeFaiss:
    """Enough of faiss to exercise save/load without the real library."""

    def __init__(self):
        self.written = {}

    def install(self, test):
        import sys
        import types

        module = types.ModuleType("faiss")
        module.write_index = lambda index, path: self.written.__setitem__(path, index)
        module.read_index = self._read
        module.normalize_L2 = lambda _v: None
        sys.modules["faiss"] = module
        test.addCleanup(sys.modules.pop, "faiss", None)
        return self

    def _read(self, path):
        if path not in self.written:
            raise RuntimeError(f"no such index: {path}")
        return self.written[path]


class CountingIndex:
    """A FAISS index reduced to the two numbers persistence cares about."""

    def __init__(self, ntotal, d=rag.DEFAULT_DIMENSION):
        self.ntotal = ntotal
        self.d = d


class SidecarPersistenceTests(RagTestCase):
    """The index and its metadata must not be able to drift apart.

    retrieve() looks documents up by the position FAISS returns. An index and a
    sidecar describing different corpora do not raise — they answer with the
    wrong text attributed to the wrong source, which is the failure worth
    engineering against.
    """

    def setUp(self):
        super().setUp()
        self.faiss = FakeFaiss().install(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        rag.default_index.index_path = os.path.join(self.tmp.name, "i.faiss")
        rag.default_index.docs_path = rag.sidecar_path_for(rag.default_index.index_path)

    def save(self, documents):
        rag.default_index.documents = list(documents)
        rag.default_index.index = CountingIndex(len(documents))
        rag.save_index()

    def test_documents_survive_a_save_and_load_round_trip(self):
        documents = [
            {"text": "Fractions divide a whole.", "source": "ch1.txt", "chunk_idx": 0},
            {"text": "A ratio compares.", "source": "ch2.txt", "chunk_idx": 0},
        ]
        self.save(documents)
        rag.default_index.documents = []

        rag.load_index()

        self.assertEqual(rag.default_index.documents, documents)

    def test_the_sidecar_is_readable_json(self):
        """A person debugging a bad index should be able to open the file."""
        self.save([{"text": "body", "source": "a.txt", "chunk_idx": 0}])

        with open(rag.default_index.docs_path, encoding="utf-8") as handle:
            payload = json.load(handle)

        self.assertEqual(payload["version"], rag.SIDECAR_VERSION)
        self.assertEqual(payload["ntotal"], 1)
        self.assertEqual(payload["documents"][0]["source"], "a.txt")

    def test_unicode_survives_the_round_trip(self):
        documents = [{"text": "A = πr² and c = √(a² + b²)", "source": "m.txt", "chunk_idx": 0}]
        self.save(documents)
        rag.default_index.documents = []

        rag.load_index()

        self.assertEqual(rag.default_index.documents, documents)

    def test_no_temporary_file_is_left_behind(self):
        self.save([{"text": "body", "source": "a.txt", "chunk_idx": 0}])

        self.assertFalse(os.path.exists(rag.default_index.docs_path + ".tmp"))

    def test_a_vector_count_disagreeing_with_the_sidecar_is_rejected(self):
        """The shape a crash between the two writes leaves behind."""
        self.save([{"text": "body", "source": "a.txt", "chunk_idx": 0}])
        # The index moved on; the sidecar still describes one vector.
        self.faiss.written[rag.default_index.index_path] = CountingIndex(9)

        with self.assertRaises(rag.IndexUnusable):
            rag.load_index()

    def test_a_document_count_disagreeing_with_the_vectors_is_rejected(self):
        self.save([{"text": "body", "source": "a.txt", "chunk_idx": 0}])
        self._corrupt(lambda p: p.update(documents=[]))

        with self.assertRaises(rag.IndexUnusable):
            rag.load_index()

    def test_a_missing_sidecar_is_rejected(self):
        self.save([{"text": "body", "source": "a.txt", "chunk_idx": 0}])
        os.remove(rag.default_index.docs_path)

        with self.assertRaises(rag.IndexUnusable):
            rag.load_index()

    def test_an_unparseable_sidecar_is_rejected_rather_than_raising_json_errors(self):
        """Covers a leftover pickle sitting where JSON is expected."""
        self.save([{"text": "body", "source": "a.txt", "chunk_idx": 0}])
        with open(rag.default_index.docs_path, "wb") as handle:
            handle.write(b"\x80\x04\x95not json at all")

        with self.assertRaises(rag.IndexUnusable):
            rag.load_index()

    def test_an_unrecognised_sidecar_version_is_rejected(self):
        """A format change must cost a rebuild, never a misread."""
        self.save([{"text": "body", "source": "a.txt", "chunk_idx": 0}])
        self._corrupt(lambda p: p.update(version=rag.SIDECAR_VERSION + 1))

        with self.assertRaises(rag.IndexUnusable):
            rag.load_index()

    def test_an_unreadable_vector_file_is_rejected(self):
        self.save([{"text": "body", "source": "a.txt", "chunk_idx": 0}])
        self.faiss.written.clear()

        with self.assertRaises(rag.IndexUnusable):
            rag.load_index()

    def _corrupt(self, mutate):
        with open(rag.default_index.docs_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        mutate(payload)
        with open(rag.default_index.docs_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)


class EmbeddingModelIdentityTests(RagTestCase):
    """An index is only meaningful against the model that built it.

    The dangerous case is not a width mismatch — FAISS catches that. It is
    swapping one 384-wide model for another: the cached index loads, queries
    embed, dimensions agree, nothing raises, and every answer is drawn from
    vectors that meant something else.
    """

    def setUp(self):
        super().setUp()
        self.faiss = FakeFaiss().install(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # The index lives beside the corpus, never inside it: is_index_stale
        # walks the corpus, so a sidecar written within it would show up as a
        # change to the very thing it describes.
        self.corpus = os.path.join(self.tmp.name, "curriculum")
        os.makedirs(self.corpus)
        index = rag.default_index
        index.index_path = os.path.join(self.tmp.name, "i.faiss")
        index.docs_path = rag.sidecar_path_for(index.index_path)
        index.curriculum_path = self.corpus
        index.documents = [{"text": "body", "source": "a.txt", "chunk_idx": 0}]
        index.index = CountingIndex(1)
        index.dimension = rag.DEFAULT_DIMENSION
        rag.save_index()

    def test_the_model_that_built_the_index_is_recorded(self):
        with open(rag.default_index.docs_path, encoding="utf-8") as handle:
            payload = json.load(handle)

        self.assertEqual(payload["embed_model"], rag.EMBED_MODEL)
        self.assertEqual(payload["dimension"], rag.DEFAULT_DIMENSION)

    def test_a_different_model_of_the_same_width_is_refused(self):
        """Same dimension, different meaning. Nothing else would catch this."""
        rag.default_index.embed_model = "some-other-384-wide-model"

        with self.assertRaises(rag.IndexUnusable):
            rag.load_index()

    def test_a_different_model_makes_the_index_stale(self):
        """Refused at the staleness check too, so it rebuilds rather than retries."""
        rag.default_index.embed_model = "some-other-384-wide-model"

        self.assertTrue(rag.is_index_stale(self.corpus))

    def test_the_same_model_round_trips(self):
        rag.default_index.documents = []

        rag.load_index()

        self.assertEqual(len(rag.default_index.documents), 1)

    def test_the_width_is_restored_without_loading_a_model(self):
        """Reopening an index must not need the embedder just to learn its width."""
        rag.default_index.documents = []
        rag.default_index.dimension = None
        rag.default_index.embedder = None

        rag.load_index()

        self.assertEqual(rag.default_index.dimension, rag.DEFAULT_DIMENSION)


class ReconstructRecorder:
    """A flat index that records how its vectors were read back."""

    def __init__(self, ntotal, d=rag.DEFAULT_DIMENSION):
        self.ntotal = ntotal
        self.d = d
        self.calls = []

    def reconstruct_n(self, start, count):
        self.calls.append(("reconstruct_n", start, count))
        return [[0.0] * self.d for _ in range(count)]

    def reconstruct(self, i):
        self.calls.append(("reconstruct", i))
        return [0.0] * self.d


class IvfUpgradeTests(RagTestCase):
    """Contract tests, deliberately, and the docstring says so.

    These pin that FAISS is *called* correctly — reconstruct_n(0, n) in one go
    rather than n separate round trips through Python. They say nothing about
    what FAISS does with that call. Only the rag-verify workflow can speak to
    that, and it does.
    """

    def install_faiss(self):
        import sys
        import types

        class FlatIndex:
            def __init__(self, d):
                self.d = d
                self.ntotal = 0

        class IvfIndex:
            def __init__(self, quantiser, d, nlist, metric):
                self.quantiser, self.d, self.nlist, self.metric = quantiser, d, nlist, metric
                self.trained = self.added = None
                self.nprobe = None

            def train(self, vectors):
                self.trained = vectors

            def add(self, vectors):
                self.added = vectors

        module = types.ModuleType("faiss")
        module.IndexFlatIP = FlatIndex
        module.IndexIVFFlat = IvfIndex
        module.METRIC_INNER_PRODUCT = 0
        sys.modules["faiss"] = module
        self.addCleanup(sys.modules.pop, "faiss", None)
        return module

    def upgrade_with(self, ntotal):
        self.install_faiss()
        source = ReconstructRecorder(ntotal)
        rag.default_index.index = source
        rag.default_index.dimension = source.d
        rag._maybe_upgrade_to_ivf()
        return source

    def test_vectors_are_read_back_in_one_call(self):
        """The loop it replaces crossed the Python/C boundary once per vector."""
        source = self.upgrade_with(rag.IVF_THRESHOLD)

        self.assertEqual(source.calls, [("reconstruct_n", 0, rag.IVF_THRESHOLD)])

    def test_no_per_vector_reconstruct_survives(self):
        source = self.upgrade_with(rag.IVF_THRESHOLD)

        self.assertNotIn("reconstruct", [call[0] for call in source.calls])

    def test_a_corpus_below_the_threshold_stays_exact(self):
        """Approximate search is a cost, not a feature, until the corpus earns it."""
        source = self.upgrade_with(rag.IVF_THRESHOLD - 1)

        self.assertEqual(source.calls, [])
        self.assertIs(rag.default_index.index, source)

    def test_the_threshold_is_high_enough_to_train_properly(self):
        """nlist = min(100, n // 10) needs enough vectors per centroid.

        At the old threshold of 1000 this gave 100 centroids over 1000 vectors —
        about 10 training points each, far below what FAISS wants. It warns and
        clusters badly, which costs recall exactly when the corpus is still
        small enough not to need approximation at all.
        """
        nlist = min(100, rag.IVF_THRESHOLD // 10)

        self.assertGreaterEqual(rag.IVF_THRESHOLD / nlist, 39)

    def test_an_index_that_is_already_approximate_is_left_alone(self):
        module = self.install_faiss()
        already = module.IndexIVFFlat(None, rag.DEFAULT_DIMENSION, 10, 0)
        already.ntotal = rag.IVF_THRESHOLD * 2
        rag.default_index.index = already

        rag._maybe_upgrade_to_ivf()

        self.assertIs(rag.default_index.index, already)

    def test_an_unbuilt_index_needs_neither_faiss_nor_a_model(self):
        """An empty corpus must not download a model to upgrade nothing."""
        rag.default_index.index = None

        rag._maybe_upgrade_to_ivf()

        self.assertIsNone(rag.default_index.index)


class EmptyCorpusTests(RagTestCase):
    """A curriculum directory with no files must not require a model.

    get_index() asks the embedder how wide its vectors are, so an empty corpus
    that still constructed an index would download a model in order to describe
    nothing.
    """

    def setUp(self):
        super().setUp()
        self.faiss = FakeFaiss().install(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Beside the corpus, not inside it — see EmbeddingModelIdentityTests.
        self.corpus = os.path.join(self.tmp.name, "curriculum")
        os.makedirs(self.corpus)
        index = rag.default_index
        index.index_path = os.path.join(self.tmp.name, "i.faiss")
        index.docs_path = rag.sidecar_path_for(index.index_path)
        index.curriculum_path = self.corpus

    def test_ntotal_is_zero_without_building_an_index(self):
        self.assertEqual(rag.default_index.ntotal, 0)
        self.assertIsNone(rag.default_index.index)

    def test_saving_an_empty_corpus_writes_no_vector_file(self):
        rag.save_index({})

        self.assertTrue(os.path.exists(rag.default_index.docs_path))
        self.assertFalse(os.path.exists(rag.default_index.index_path))

    def test_an_empty_corpus_round_trips(self):
        rag.save_index({})

        rag.load_index()

        self.assertEqual(rag.default_index.documents, [])
        self.assertIsNone(rag.default_index.index)

    def test_an_empty_corpus_is_fresh_once_recorded(self):
        """Otherwise every session start rebuilds a corpus with nothing in it."""
        rag.save_index(rag.scan_manifest(self.corpus))

        self.assertFalse(rag.is_index_stale(self.corpus))


class RejectedIndexRebuildTests(RagTestCase):
    """A cache that cannot be trusted costs time, never correctness."""

    def setUp(self):
        super().setUp()
        self.calls = []
        rag.default_index.is_index_stale = lambda *_a, **_k: False
        rag.default_index._rebuild = lambda *_a, **_k: self.calls.append("rebuild")

    def test_a_rejected_cache_falls_back_to_a_rebuild(self):
        rag.default_index.load_index = self._raise

        with tempfile.TemporaryDirectory() as tmp:
            rag.ensure_curriculum_loaded(tmp)

        self.assertEqual(self.calls, ["rebuild"])

    def test_a_healthy_cache_is_not_rebuilt(self):
        rag.default_index.load_index = lambda: self.calls.append("load")

        with tempfile.TemporaryDirectory() as tmp:
            rag.ensure_curriculum_loaded(tmp)

        self.assertEqual(self.calls, ["load"])

    @staticmethod
    def _raise():
        raise rag.IndexUnusable("deliberately corrupt")


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
        rag.default_index.embedder = FakeEmbedder()
        rag.default_index.index = FakeIndex([scores], [indices])
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
        rag.default_index.documents = [{"text": "keep"}, {"text": "drop"}]
        self.install_fakes([rag.MIN_SCORE + 0.1, rag.MIN_SCORE - 0.1], [0, 1])

        results = rag.retrieve("q")

        self.assertEqual(results, [{"text": "keep"}])

    def test_a_score_exactly_at_the_floor_is_kept(self):
        rag.default_index.documents = [{"text": "edge"}]
        self.install_fakes([rag.MIN_SCORE], [0])

        self.assertEqual(rag.retrieve("q"), [{"text": "edge"}])

    def test_the_negative_one_sentinel_is_skipped(self):
        """FAISS pads short result sets with -1."""
        rag.default_index.documents = [{"text": "real"}]
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
        """Patch on the instance: these are methods, so ensure_curriculum_loaded
        reaches them through self, not through the module namespace."""
        setattr(
            rag.default_index, name, lambda *a, _n=name, **k: self.calls.append(_n)
        )

    def test_a_repeat_call_on_an_unchanged_corpus_does_no_work(self):
        """Replaces a test that asserted a latch which never cleared.

        The latch made a repeat call free, but it also meant no curriculum
        change could take effect without restarting the process. The cheapness
        is worth keeping; the permanence is not. The guard is now "the corpus
        still matches what I loaded" rather than "I have loaded once".
        """
        with tempfile.TemporaryDirectory() as tmp:
            rag.default_index._loaded_manifest = rag.scan_manifest(tmp)
            rag.default_index.documents = [{"text": "x", "source": "a.txt", "chunk_idx": 0}]

            rag.ensure_curriculum_loaded(tmp)

            self.assertEqual(self.calls, [])

    def test_a_corpus_that_changed_is_reloaded_without_a_restart(self):
        """The process-level half of the eviction fix."""
        with tempfile.TemporaryDirectory() as tmp:
            rag.default_index._loaded_manifest = rag.scan_manifest(tmp)
            rag.default_index.documents = [{"text": "x", "source": "a.txt", "chunk_idx": 0}]

            with open(os.path.join(tmp, "new.txt"), "w", encoding="utf-8") as handle:
                handle.write("added after loading")

            rag.ensure_curriculum_loaded(tmp)

            self.assertEqual(
                self.calls, ["load_curriculum_folder", "_maybe_upgrade_to_ivf", "save_index"]
            )

    def test_a_missing_folder_is_skipped(self):
        """No longer asserts that a latch was set — there is no latch."""
        rag.ensure_curriculum_loaded(os.path.join("does", "not", "exist"))

        self.assertEqual(self.calls, [])

    def test_a_failed_build_does_not_freeze_the_process(self):
        """The latch was set *before* indexing ran, so one bad PDF was fatal.

        A raising loader used to leave the process serving a half-built index
        for its whole lifetime, silently and with no log line. Now the failure
        propagates and the next call tries again.
        """
        def explode(*_args, **_kwargs):
            raise RuntimeError("corrupt PDF")

        rag.default_index.load_curriculum_folder = explode

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                rag.ensure_curriculum_loaded(tmp)

            self._patch("load_curriculum_folder")
            rag.ensure_curriculum_loaded(tmp)

        self.assertIn("load_curriculum_folder", self.calls)

    def force_staleness(self, stale):
        rag.default_index.is_index_stale = lambda *_a, **_k: stale

    def test_a_stale_index_is_rebuilt_and_saved(self):
        self.force_staleness(True)
        with tempfile.TemporaryDirectory() as tmp:
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
        rag.default_index.load_all_files = (
            lambda folder, root=None: self.loaded.append(folder)
        )

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
        rag.default_index.add_documents = self.added.extend

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
        """Safe when the optional dependency is absent, as it is here."""
        with tempfile.TemporaryDirectory() as tmp:
            rag.load_docx_files(tmp, tmp)

        self.assertEqual(self.added, [])


class LoaderDispatchTests(RagTestCase):
    """One walk over a table, where five near-identical functions used to be."""

    def setUp(self):
        super().setUp()
        self.added = []
        rag.default_index.add_documents = self.added.extend
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, content="A sentence of curriculum."):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def sources(self):
        return [chunk["source"] for chunk in self.added]

    def test_every_supported_format_has_an_extractor(self):
        self.assertEqual(set(rag.EXTRACTORS), {".txt", ".md", ".pdf", ".docx", ".json"})

    def test_one_call_picks_up_every_supported_format(self):
        self.write("a.txt")
        self.write("b.md", "# Heading\n\nSome prose about fractions.")
        self.write("c.json", '[{"title": "Ratios", "content": "A ratio compares two values."}]')

        rag.load_all_files(self.tmp.name, self.tmp.name)

        self.assertEqual(self.sources(), ["a.txt", "b.md", "c.json/Ratios"])

    def test_unsupported_extensions_are_ignored(self):
        self.write("notes.rtf")
        self.write("sheet.xlsx")

        rag.load_all_files(self.tmp.name, self.tmp.name)

        self.assertEqual(self.added, [])

    def test_extensions_are_matched_case_insensitively(self):
        """A teacher's file from Windows may well be README.TXT."""
        self.write("SHOUTING.TXT")

        rag.load_all_files(self.tmp.name, self.tmp.name)

        self.assertEqual(self.sources(), ["SHOUTING.TXT"])

    def test_files_are_read_in_a_deterministic_order(self):
        """os.listdir order is not guaranteed, and it decides chunk positions."""
        for name in ("c.txt", "a.txt", "b.txt"):
            self.write(name)

        rag.load_all_files(self.tmp.name, self.tmp.name)

        self.assertEqual(self.sources(), ["a.txt", "b.txt", "c.txt"])

    def test_an_unreadable_file_is_skipped_and_the_rest_still_index(self):
        """Bug E, exercised for real: PyPDF2 is absent, so every .pdf raises.

        One bad file used to abort the entire corpus build. Combined with the
        load-once latch, that left the process serving a half-built index until
        somebody restarted it.
        """
        self.write("good.txt")
        self.write("broken.pdf", "not really a pdf")
        self.write("also_good.md", "More prose.")

        rag.load_all_files(self.tmp.name, self.tmp.name)

        self.assertEqual(self.sources(), ["also_good.md", "good.txt"])

    def test_an_empty_file_produces_no_chunks(self):
        self.write("blank.txt", "   \n\n  ")

        rag.load_all_files(self.tmp.name, self.tmp.name)

        self.assertEqual(self.added, [])

    def test_one_json_file_can_yield_several_labelled_sources(self):
        self.write(
            "lessons.json",
            '[{"title": "Ratios", "content": "A ratio compares."},'
            ' {"title": "Percents", "content": "A percent is per hundred."}]',
        )

        rag.load_all_files(self.tmp.name, self.tmp.name)

        self.assertEqual(self.sources(), ["lessons.json/Ratios", "lessons.json/Percents"])

    def test_malformed_json_is_skipped_rather_than_fatal(self):
        self.write("bad.json", "{not json")
        self.write("fine.txt")

        rag.load_all_files(self.tmp.name, self.tmp.name)

        self.assertEqual(self.sources(), ["fine.txt"])

    def test_the_single_format_wrappers_still_filter(self):
        """The public load_*_files names are the tested surface; keep them honest."""
        self.write("a.txt")
        self.write("b.md", "Prose.")

        rag.load_txt_files(self.tmp.name, self.tmp.name)

        self.assertEqual(self.sources(), ["a.txt"])
