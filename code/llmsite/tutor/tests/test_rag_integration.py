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
import unittest

from django.test import SimpleTestCase

from tutor.management.commands._rag_harness import EVAL_CORPUS, isolated_index

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
