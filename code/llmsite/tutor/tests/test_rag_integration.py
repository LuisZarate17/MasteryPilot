"""Integration tests that need a real embedding model and a real FAISS index.

Skipped everywhere the RAG stack is absent, which includes this developer
machine, the default test run and the push-triggered CI job. They execute in
the `rag-verify` workflow, which is dispatched by hand.

That makes these the only tests in the suite that touch the vector path. Every
other RAG test runs against fakes, deliberately — but fakes cannot tell you
that FAISS round-trips an index, that cosine similarity actually ranks a
relevant passage above an irrelevant one, or that a deleted file stops being
retrievable. Those are the claims worth checking with the real thing.

Assertions here are deliberately about *ordering and membership*, never about
specific similarity values. Exact scores are a property of the model and would
turn a model upgrade into a test failure for no reason.
"""

import os
import shutil
import tempfile
import unittest

from django.test import SimpleTestCase

import rag
from tutor.management.commands._rag_harness import (
    EVAL_CORPUS,
    _shared_embedder,
    isolated_index,
)

try:
    import faiss  # noqa: F401
    import sentence_transformers  # noqa: F401

    HAS_RAG_STACK = True
except ImportError:
    HAS_RAG_STACK = False

SKIP_REASON = "requirements-llm.txt is not installed (run the rag-verify workflow)"


@unittest.skipUnless(HAS_RAG_STACK, SKIP_REASON)
class RealIndexTests(SimpleTestCase):
    """The evaluation corpus, embedded and searched for real."""

    def test_the_corpus_indexes_to_a_nonempty_index(self):
        with isolated_index(EVAL_CORPUS) as index:
            self.assertGreater(len(index.documents), 0)
            self.assertEqual(index.get_index().ntotal, len(index.documents))

    def test_a_direct_question_retrieves_its_own_document(self):
        with isolated_index(EVAL_CORPUS) as index:
            hits = index.retrieve("how do plants convert sunlight into food")

            self.assertTrue(hits, "a clearly answerable question returned nothing")
            self.assertIn("photosynthesis.txt", {h["source"] for h in hits})

    def test_subject_separation_holds_across_the_corpus(self):
        """Algebra questions must not surface biology, and vice versa."""
        cases = [
            ("what is the quadratic formula", "quadratic_equations.txt"),
            ("what is the bottom number of a fraction called", "fractions.txt"),
            ("what do mitochondria do", "cell_structure.txt"),
        ]
        with isolated_index(EVAL_CORPUS) as index:
            for query, expected in cases:
                with self.subTest(query=query):
                    hits = index.retrieve(query)

                    self.assertTrue(hits, f"{query!r} returned nothing")
                    self.assertEqual(
                        hits[0]["source"].split("/")[0],
                        expected,
                        f"top hit for {query!r} was {hits[0]['source']}",
                    )

    def test_every_indexed_chunk_carries_its_source_and_position(self):
        with isolated_index(EVAL_CORPUS) as index:
            corpus_files = set(os.listdir(EVAL_CORPUS))
            for doc in index.documents:
                self.assertIn(doc["source"].split("/")[0], corpus_files)
                self.assertIsInstance(doc["chunk_idx"], int)


@unittest.skipUnless(HAS_RAG_STACK, SKIP_REASON)
class PersistenceRoundTripTests(SimpleTestCase):
    """save_index then load_index must reproduce the same answers.

    The index and its metadata are written as two files. If they can ever drift
    apart, documents[i] indexes a different corpus than the vector at i, and
    chunks get attributed to the wrong source — silently, because nothing
    raises.
    """

    QUERY = "what is the discriminant"

    def test_a_saved_index_reloads_with_identical_results(self):
        with isolated_index(EVAL_CORPUS) as index:
            before = index.retrieve(self.QUERY)
            self.assertTrue(before, "nothing to compare — the query returned no hits")

            index.save_index()
            index.documents = []
            index.index = None
            index.load_index()

            after = index.retrieve(self.QUERY)

        self.assertEqual(
            [(h["source"], h["chunk_idx"]) for h in before],
            [(h["source"], h["chunk_idx"]) for h in after],
        )

    def test_the_reloaded_index_and_metadata_stay_the_same_length(self):
        with isolated_index(EVAL_CORPUS) as index:
            expected = len(index.documents)

            index.save_index()
            index.documents = []
            index.index = None
            index.load_index()

            self.assertEqual(len(index.documents), expected)
            self.assertEqual(index.get_index().ntotal, expected)


@unittest.skipUnless(HAS_RAG_STACK, SKIP_REASON)
class EvictionTests(SimpleTestCase):
    """Deleted curriculum must stop reaching students.

    The defect this phase exists for, checked against a real index rather than
    a manifest comparison. The unit tests prove staleness is *detected*; these
    prove the detection actually results in the content being gone.
    """

    QUERY = "how do plants convert sunlight into food"
    DOOMED = "photosynthesis.txt"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rag-eviction-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.corpus = os.path.join(self.tmp, "curriculum")
        shutil.copytree(EVAL_CORPUS, self.corpus)

    def build(self):
        """A fresh RagIndex over the corpus, sharing the process-wide embedder.

        Constructing a new one each time is what makes the second call in
        test_a_deletion_survives_a_restart a genuine cold start.
        """
        index = rag.RagIndex(
            curriculum_path=self.corpus,
            index_path=os.path.join(self.tmp, "i.faiss"),
        )
        index.embedder = _shared_embedder(rag)
        index.ensure_curriculum_loaded(self.corpus)
        return index

    def sources(self, index):
        return {doc["source"].split("/")[0] for doc in index.documents}

    def test_a_deleted_document_stops_being_retrieved(self):
        index = self.build()
        self.assertIn(
            self.DOOMED,
            {h["source"] for h in index.retrieve(self.QUERY)},
            "the document was not retrievable to begin with — the test proves nothing",
        )

        os.remove(os.path.join(self.corpus, self.DOOMED))
        index.ensure_curriculum_loaded(self.corpus)

        self.assertNotIn(self.DOOMED, {h["source"] for h in index.retrieve(self.QUERY)})
        self.assertNotIn(self.DOOMED, self.sources(index))

    def test_a_deletion_survives_a_restart(self):
        """mtime staleness could not see a deletion, so a restart did not help."""
        self.build()

        os.remove(os.path.join(self.corpus, self.DOOMED))

        self.assertNotIn(self.DOOMED, self.sources(self.build()))

    def test_the_surviving_documents_are_still_retrievable(self):
        """Eviction rebuilds the corpus, so it has to put everything else back."""
        index = self.build()
        os.remove(os.path.join(self.corpus, self.DOOMED))

        index.ensure_curriculum_loaded(self.corpus)

        self.assertEqual(
            self.sources(index), set(os.listdir(self.corpus)) - {self.DOOMED}
        )
        self.assertTrue(index.retrieve("what is the discriminant"))

    def test_an_added_document_becomes_retrievable(self):
        index = self.build()
        with open(os.path.join(self.corpus, "tides.txt"), "w", encoding="utf-8") as handle:
            handle.write(
                "Tides are the rise and fall of sea level caused by the gravitational "
                "pull of the moon and the sun on the oceans of the earth."
            )

        index.ensure_curriculum_loaded(self.corpus)

        self.assertIn("tides.txt", self.sources(index))
        self.assertIn(
            "tides.txt", {h["source"] for h in index.retrieve("what causes the tides")}
        )

    def test_an_unchanged_corpus_is_not_rebuilt(self):
        """Re-checking on every call must stay cheap, or this becomes a regression."""
        index = self.build()
        rebuilt = []
        index._rebuild = lambda *a, **k: rebuilt.append(1)

        index.ensure_curriculum_loaded(self.corpus)

        self.assertEqual(rebuilt, [])


@unittest.skipUnless(HAS_RAG_STACK, SKIP_REASON)
class HybridRetrievalTests(SimpleTestCase):
    """Both legs, against real vectors.

    The unit tests prove BM25 and rank fusion are arithmetically correct. What
    they cannot show is that the combination beats either leg alone on real
    embeddings, which is the claim the README makes.
    """

    LEXICAL = [
        ("what is the discriminant", "quadratic_equations.txt"),
        ("chlorophyll", "photosynthesis.txt"),
        ("what is the Calvin cycle", "photosynthesis.txt"),
        ("least common denominator", "fractions.txt"),
        ("what is an accumulator variable", "python_loops.md"),
    ]

    def test_rare_term_queries_find_their_document(self):
        """Exactly where a compressed embedding is least confident."""
        with isolated_index(EVAL_CORPUS) as index:
            for query, expected in self.LEXICAL:
                with self.subTest(query=query):
                    hits = index.retrieve(query)

                    self.assertTrue(hits, f"{query!r} returned nothing")
                    self.assertIn(expected, {h["source"].split("/")[0] for h in hits})

    def test_paraphrases_still_work(self):
        """Adding a lexical leg must not cost the semantic one."""
        cases = [
            ("how do plants make food from sunlight", "photosynthesis.txt"),
            ("what is the bottom number of a fraction called", "fractions.txt"),
            ("how do I repeat something when I do not know how many times", "python_loops.md"),
        ]
        with isolated_index(EVAL_CORPUS) as index:
            for query, expected in cases:
                with self.subTest(query=query):
                    hits = index.retrieve(query)

                    self.assertTrue(hits, f"{query!r} returned nothing")
                    self.assertIn(expected, {h["source"].split("/")[0] for h in hits})

    def test_off_topic_questions_still_come_back_empty(self):
        """The dense gate has to survive the sparse leg being added."""
        with isolated_index(EVAL_CORPUS) as index:
            for query in ("what is the capital of France", "how do I reset my password"):
                with self.subTest(query=query):
                    self.assertEqual(index.retrieve(query), [])

    def test_code_inside_fenced_blocks_is_retrievable(self):
        """It was deleted during ingestion, so these could never have matched."""
        with isolated_index(EVAL_CORPUS) as index:
            hits = index.retrieve("how do I use range to loop from 1 to 10")

            self.assertIn("python_loops.md", {h["source"].split("/")[0] for h in hits})

    def test_every_hit_carries_a_fused_score(self):
        with isolated_index(EVAL_CORPUS) as index:
            hits = index.retrieve("what is the discriminant")

            self.assertTrue(all("score" in hit for hit in hits))
            self.assertEqual(
                [h["score"] for h in hits], sorted((h["score"] for h in hits), reverse=True)
            )
