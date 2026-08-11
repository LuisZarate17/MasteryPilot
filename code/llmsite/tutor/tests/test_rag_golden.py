"""Characterisation tests: chunk boundaries pinned to a checked-in fixture.

These do not assert that the chunking is *good*. They assert that it has not
changed without someone noticing — which is the only guarantee available in an
environment that cannot run an embedding model.

The chain of custody: if the text handed to the embedder is byte-identical and
the model is unchanged, the vectors are identical and retrieval is identical.
That reasoning needs no GPU, and these fixtures are what make the first half of
it checkable.

Chunk boundaries *are* expected to change in the ingestion and chunk-sizing
work. When that happens the fixture is regenerated deliberately and the diff is
reviewed as part of the change:

    RAG_UPDATE_GOLDEN=1 python manage.py test tutor.tests.test_rag_golden

A diff appearing in any other commit means something moved that should not have.
"""

import json
import os

from django.test import SimpleTestCase

import rag

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "chunking")
CORPUS_DIR = os.path.join(FIXTURES, "corpus")
MARKDOWN_DIR = os.path.join(FIXTURES, "markdown")
GOLDEN_CHUNKS = os.path.join(FIXTURES, "golden_chunks.json")
GOLDEN_MARKDOWN = os.path.join(FIXTURES, "golden_markdown.json")

UPDATE = os.getenv("RAG_UPDATE_GOLDEN", "").strip().lower() in {"1", "true", "yes", "on"}

REGENERATE_HINT = (
    "\n\nChunk boundaries moved. If that was deliberate, regenerate and review the diff:\n"
    "    RAG_UPDATE_GOLDEN=1 python manage.py test tutor.tests.test_rag_golden\n"
    "If it was not deliberate, something changed the text reaching the embedder."
)


def _read_text(path):
    """Text mode: universal newlines, so a CRLF checkout yields the same chunks."""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _read_golden(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_golden(path, payload):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


class GoldenChunkingTests(SimpleTestCase):
    """chunk_text over a fixed corpus."""

    def current(self):
        return {
            name: rag.chunk_text(_read_text(os.path.join(CORPUS_DIR, name)), name)
            for name in sorted(os.listdir(CORPUS_DIR))
        }

    def test_chunk_boundaries_match_the_fixture(self):
        current = self.current()
        if UPDATE:
            _write_golden(GOLDEN_CHUNKS, current)

        self.assertEqual(current, _read_golden(GOLDEN_CHUNKS), REGENERATE_HINT)

    def test_the_corpus_covers_every_branch_of_chunk_text(self):
        """A fixture that stopped exercising the hard-split path would pass silently."""
        current = self.current()

        self.assertEqual(len(current["short.txt"]), 1, "short.txt must stay single-chunk")
        self.assertGreater(len(current["prose.txt"]), 1, "prose.txt must span chunks")
        self.assertGreater(
            len(current["long_sentence.txt"]), 1, "long_sentence.txt must force a hard split"
        )
        self.assertEqual(
            current["flush_then_split.txt"][0]["text"],
            "Read the worked example before attempting the exercises.",
            "flush_then_split.txt must buffer a short sentence before the over-long one",
        )

    def test_no_chunk_in_the_fixture_exceeds_the_configured_size(self):
        for name, chunks in self.current().items():
            for chunk in chunks:
                with self.subTest(source=name, idx=chunk["chunk_idx"]):
                    self.assertLessEqual(len(chunk["text"]), rag.CHUNK_SIZE)


class GoldenMarkdownTests(SimpleTestCase):
    """The full markdown pipeline: strip, then chunk.

    Separate from GoldenChunkingTests because the stripping regexes are their
    own source of change, and because this is where the code-block handling is
    visible. Read golden_markdown.json to see what currently survives ingestion.
    """

    def current(self):
        collected = []
        original = rag.add_documents
        rag.add_documents = collected.extend
        try:
            rag.load_md_files(MARKDOWN_DIR, MARKDOWN_DIR)
        finally:
            rag.add_documents = original
        # os.listdir order is not guaranteed across platforms.
        return sorted(collected, key=lambda chunk: (chunk["source"], chunk["chunk_idx"]))

    def test_markdown_ingestion_matches_the_fixture(self):
        current = self.current()
        if UPDATE:
            _write_golden(GOLDEN_MARKDOWN, current)

        self.assertEqual(current, _read_golden(GOLDEN_MARKDOWN), REGENERATE_HINT)

    def test_both_markdown_fixtures_produce_chunks(self):
        sources = {chunk["source"] for chunk in self.current()}

        self.assertEqual(sources, {"lesson.md", "code_heavy.md"})
