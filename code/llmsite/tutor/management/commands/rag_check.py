"""Index a directory and run queries against it, printing what comes back.

    python manage.py rag_check --query "what is the discriminant"
    python manage.py rag_check /path/to/curriculum --query "photosynthesis"
    python manage.py rag_check --list

A debugging tool, not a test. Use rag_eval to measure; use this to look at what
a single query actually retrieves and why. Needs requirements-llm.txt.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ._rag_harness import EVAL_CORPUS, MissingStackError, isolated_index, require_stack

PREVIEW = 200


class Command(BaseCommand):
    help = "Index a curriculum directory and show what a query retrieves."

    def add_arguments(self, parser):
        parser.add_argument(
            "corpus",
            nargs="?",
            default=None,
            help=f"Directory to index. Defaults to CURRICULUM_ROOT, falling back to {EVAL_CORPUS}.",
        )
        parser.add_argument("--query", action="append", default=[], help="Repeatable.")
        parser.add_argument("--top-k", type=int, default=None, help="Defaults to rag.TOP_K.")
        parser.add_argument("--chunk-size", type=int, default=None)
        parser.add_argument("--chunk-overlap", type=int, default=None)
        parser.add_argument("--list", action="store_true", help="List indexed chunks and exit.")
        parser.add_argument("--full", action="store_true", help="Print whole chunks, not previews.")

    def handle(self, *args, **options):
        try:
            require_stack()
        except MissingStackError as exc:
            raise CommandError(str(exc)) from exc

        import rag

        corpus = options["corpus"] or self._default_corpus()
        if not options["query"] and not options["list"]:
            raise CommandError("Pass at least one --query, or --list to dump the index.")

        self.stdout.write(f"Indexing {corpus} ...")
        with isolated_index(
            corpus,
            chunk_size=options["chunk_size"],
            chunk_overlap=options["chunk_overlap"],
        ) as indexed:
            documents = list(indexed.documents)
            self.stdout.write(
                self.style.SUCCESS(f"{len(documents)} chunks from {self._source_count(documents)} sources\n")
            )

            if not documents:
                self.stdout.write(self.style.WARNING("Nothing indexed — is the directory empty?"))
                return

            if options["list"]:
                self._dump(documents, options["full"])
                return

            top_k = options["top_k"] or indexed.TOP_K
            for query in options["query"]:
                self._run(indexed, query, top_k, options["full"])

    def _default_corpus(self):
        root = str(settings.CURRICULUM_ROOT)
        import os

        if os.path.isdir(root) and os.listdir(root):
            return root
        self.stdout.write(
            self.style.WARNING(f"{root} is empty or absent — using the evaluation corpus instead.")
        )
        return EVAL_CORPUS

    @staticmethod
    def _source_count(documents):
        return len({doc["source"] for doc in documents})

    def _body(self, text, full):
        if full:
            return text
        flat = " ".join(text.split())
        return flat if len(flat) <= PREVIEW else flat[:PREVIEW] + " ..."

    def _dump(self, documents, full):
        for doc in documents:
            self.stdout.write(f"[{doc['source']} #{doc['chunk_idx']}]")
            self.stdout.write(f"  {self._body(doc['text'], full)}\n")

    def _run(self, indexed, query, top_k, full):
        self.stdout.write("=" * 68)
        self.stdout.write(f"Query: {query}")
        self.stdout.write("=" * 68)

        hits = indexed.retrieve(query, top_k=top_k)
        if not hits:
            self.stdout.write(
                self.style.WARNING(
                    f"No chunks cleared the score floor (MIN_SCORE={indexed.MIN_SCORE}). "
                    "For an off-topic query that is the correct answer."
                )
            )
            self.stdout.write("")
            return

        for rank, hit in enumerate(hits, start=1):
            # retrieve() only carries a score once the hybrid work lands; until
            # then this prints the rank alone rather than a fabricated 0.000.
            score = f"  score {hit['score']:.4f}" if "score" in hit else ""
            self.stdout.write(f"{rank}. [{hit['source']} #{hit['chunk_idx']}]{score}")
            self.stdout.write(f"   {self._body(hit['text'], full)}\n")
