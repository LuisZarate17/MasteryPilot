"""The evaluation harness's arithmetic, and the integrity of the labelled set.

rag_eval itself needs an embedding model and cannot run here. Its metrics do
not: recall, MRR, rejection accuracy and score separation are arithmetic over a
list of retrieved sources. That arithmetic is what these tests cover, so the
numbers the dispatch job reports are trustworthy before anyone reads them.

The fixture-integrity tests matter more than they look. A typo in a filename
inside queries.json would make a query permanently unhittable and quietly drag
the measured hit rate down forever, which is exactly the kind of silent
miscalibration this phase exists to prevent.
"""

import json
import os

from django.test import SimpleTestCase

from tutor.management.commands._rag_harness import (
    EVAL_CORPUS,
    EVAL_QUERIES,
    MissingStackError,
    _sources_of,
    evaluate,
    format_metric,
    load_query_set,
    require_stack,
)


class FakeRag:
    """Returns canned hits per query, standing in for a real index."""

    def __init__(self, responses):
        self._responses = responses

    def retrieve(self, query, top_k=5):
        return self._responses.get(query, [])


def hit(source, score=None, chunk_idx=0):
    doc = {"text": "body", "source": source, "chunk_idx": chunk_idx}
    if score is not None:
        doc["score"] = score
    return doc


class SourcesOfTests(SimpleTestCase):
    def test_rank_order_is_preserved(self):
        self.assertEqual(
            _sources_of([hit("b.txt"), hit("a.txt"), hit("c.txt")]), ["b.txt", "a.txt", "c.txt"]
        )

    def test_repeated_sources_collapse_to_first_appearance(self):
        """Two chunks from one document is one document, at its best rank."""
        ranked = _sources_of([hit("a.txt", chunk_idx=0), hit("b.txt"), hit("a.txt", chunk_idx=1)])

        self.assertEqual(ranked, ["a.txt", "b.txt"])

    def test_a_json_title_suffix_resolves_to_its_document(self):
        self.assertEqual(_sources_of([hit("lessons.json/Ratios")]), ["lessons.json"])


class MetricTests(SimpleTestCase):
    def evaluate(self, queries, responses, top_k=5):
        return evaluate(FakeRag(responses), queries, top_k)

    def test_a_hit_at_rank_one_scores_full_marks(self):
        _, summary = self.evaluate(
            [{"query": "q", "relevant": ["a.txt"], "kind": "paraphrase"}],
            {"q": [hit("a.txt")]},
        )

        self.assertEqual(summary["hit_rate@5"], 1.0)
        self.assertEqual(summary["mrr"], 1.0)

    def test_reciprocal_rank_falls_off_with_position(self):
        _, summary = self.evaluate(
            [{"query": "q", "relevant": ["c.txt"], "kind": "paraphrase"}],
            {"q": [hit("a.txt"), hit("b.txt"), hit("c.txt")]},
        )

        self.assertEqual(summary["mrr"], 1 / 3)
        self.assertEqual(summary["hit_rate@5"], 1.0, "a hit anywhere in top-k is still a hit")

    def test_a_miss_scores_zero_on_both_measures(self):
        _, summary = self.evaluate(
            [{"query": "q", "relevant": ["a.txt"], "kind": "paraphrase"}],
            {"q": [hit("z.txt")]},
        )

        self.assertEqual(summary["hit_rate@5"], 0.0)
        self.assertEqual(summary["mrr"], 0.0)

    def test_off_topic_queries_are_excluded_from_hit_rate(self):
        """Otherwise a query that *should* return nothing counts as a failure."""
        _, summary = self.evaluate(
            [
                {"query": "answerable", "relevant": ["a.txt"], "kind": "paraphrase"},
                {"query": "nonsense", "relevant": [], "kind": "off_topic"},
            ],
            {"answerable": [hit("a.txt")], "nonsense": []},
        )

        self.assertEqual(summary["answerable"], 1)
        self.assertEqual(summary["hit_rate@5"], 1.0)
        self.assertEqual(summary["rejection_accuracy"], 1.0)

    def test_returning_anything_for_an_off_topic_query_is_a_rejection_failure(self):
        """A system that always returns its top-k fails here rather than passing free."""
        _, summary = self.evaluate(
            [{"query": "nonsense", "relevant": [], "kind": "off_topic"}],
            {"nonsense": [hit("a.txt")]},
        )

        self.assertEqual(summary["rejection_accuracy"], 0.0)

    def test_metrics_are_broken_down_by_kind(self):
        _, summary = self.evaluate(
            [
                {"query": "p", "relevant": ["a.txt"], "kind": "paraphrase"},
                {"query": "l", "relevant": ["b.txt"], "kind": "lexical"},
            ],
            {"p": [hit("a.txt")], "l": [hit("zzz.txt")]},
        )

        self.assertEqual(summary["by_kind"]["paraphrase"]["hit_rate"], 1.0)
        self.assertEqual(summary["by_kind"]["lexical"]["hit_rate"], 0.0)

    def test_score_separation_is_none_while_retrieve_returns_no_scores(self):
        """Reporting 0.0 here would read as 'no separation' rather than 'not measured'."""
        _, summary = self.evaluate(
            [{"query": "q", "relevant": ["a.txt"], "kind": "paraphrase"}],
            {"q": [hit("a.txt"), hit("z.txt")]},
        )

        self.assertIsNone(summary["score_separation"])
        self.assertEqual(format_metric(summary["score_separation"]), "n/a")

    def test_score_separation_is_computed_once_scores_are_present(self):
        _, summary = self.evaluate(
            [{"query": "q", "relevant": ["a.txt"], "kind": "paraphrase"}],
            {"q": [hit("a.txt", score=0.8), hit("z.txt", score=0.3)]},
        )

        self.assertAlmostEqual(summary["score_separation"], 0.5)

    def test_empty_results_do_not_divide_by_zero(self):
        _, summary = self.evaluate([{"query": "q", "relevant": [], "kind": "off_topic"}], {})

        self.assertIsNone(summary["hit_rate@5"])
        self.assertEqual(summary["rejection_accuracy"], 1.0)


class EvaluationSetIntegrityTests(SimpleTestCase):
    """The labelled set is data, and wrong data silently miscalibrates everything."""

    def setUp(self):
        self.queries = load_query_set()
        self.corpus = set(os.listdir(EVAL_CORPUS))

    def test_every_labelled_document_exists_in_the_corpus(self):
        for spec in self.queries:
            for document in spec.get("relevant") or []:
                with self.subTest(query=spec["query"]):
                    self.assertIn(document, self.corpus)

    def test_every_corpus_document_is_reachable_by_some_query(self):
        """An unreferenced document is dead weight that inflates the index."""
        referenced = {doc for spec in self.queries for doc in spec.get("relevant") or []}

        self.assertEqual(referenced, self.corpus)

    def test_the_set_contains_unanswerable_queries(self):
        """Without these, rejection accuracy is undefined and a top-k-always system looks perfect."""
        self.assertTrue([s for s in self.queries if not s.get("relevant")])

    def test_queries_are_unique(self):
        asked = [spec["query"] for spec in self.queries]

        self.assertEqual(len(asked), len(set(asked)))

    def test_every_query_declares_a_documented_kind(self):
        with open(EVAL_QUERIES, "r", encoding="utf-8") as handle:
            documented = set(json.load(handle)["kinds"])

        for spec in self.queries:
            with self.subTest(query=spec["query"]):
                self.assertIn(spec["kind"], documented)


class MissingStackTests(SimpleTestCase):
    def test_the_absent_rag_stack_is_reported_actionably(self):
        """This suite runs without requirements-llm.txt, so this is the real path."""
        with self.assertRaises(MissingStackError) as caught:
            require_stack()

        self.assertIn("requirements-llm.txt", str(caught.exception))
