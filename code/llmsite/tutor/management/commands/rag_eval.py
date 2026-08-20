"""Measure retrieval quality against the checked-in labelled set.

    python manage.py rag_eval
    python manage.py rag_eval -v 2                    # per-query detail
    python manage.py rag_eval --save-baseline b.json  # record where we are
    python manage.py rag_eval --compare b.json        # show the delta

Needs requirements-llm.txt. The test suite runs without it by design, so this
is the tool that answers "did that change help or hurt" — a question the suite
structurally cannot.

Thresholds are opt-in (--fail-under-*). They are not defaulted to invented
numbers: the floors get set from a measured baseline, not from a guess.
"""

import json
import os

from django.core.management.base import BaseCommand, CommandError

from ._rag_harness import (
    EVAL_CORPUS,
    EVAL_QUERIES,
    FIXTURE_MIN_SCORE,
    MissingStackError,
    evaluate,
    format_metric,
    isolated_index,
    load_query_set,
    require_stack,
)


class Command(BaseCommand):
    help = "Score retrieval against the labelled evaluation set (recall, MRR, rejection)."

    def add_arguments(self, parser):
        parser.add_argument("--corpus", default=EVAL_CORPUS, help="Corpus directory to index.")
        parser.add_argument("--queries", default=EVAL_QUERIES, help="Labelled query set (JSON).")
        parser.add_argument("--top-k", type=int, default=None, help="Defaults to rag.TOP_K.")
        parser.add_argument("--chunk-size", type=int, default=None, help="Override for sweeps.")
        parser.add_argument("--chunk-overlap", type=int, default=None, help="Override for sweeps.")
        parser.add_argument(
            "--min-score", type=float, default=None,
            help="Cosine floor. Defaults to FIXTURE_MIN_SCORE for the built-in "
                 "fixture and rag.MIN_SCORE for any other corpus.",
        )
        parser.add_argument("--save-baseline", default=None, help="Write metrics to this path.")
        parser.add_argument("--compare", default=None, help="Diff metrics against this baseline.")
        parser.add_argument("--json", dest="json_out", default=None, help="Dump per-query rows.")
        parser.add_argument("--fail-under-hit-rate", type=float, default=None)
        parser.add_argument("--fail-under-mrr", type=float, default=None)
        parser.add_argument("--fail-under-rejection", type=float, default=None)

    def handle(self, *args, **options):
        try:
            require_stack()
        except MissingStackError as exc:
            raise CommandError(str(exc)) from exc

        import rag

        top_k = options["top_k"] or rag.TOP_K
        queries = load_query_set(options["queries"])

        # The fixture's scores sit in a lower band than a real curriculum's, so
        # it needs its own floor — see FIXTURE_MIN_SCORE. Defaulting by corpus
        # rather than always using rag.MIN_SCORE keeps the built-in run honest
        # without misrepresenting what the production floor does.
        if options["min_score"] is not None:
            min_score = options["min_score"]
        elif os.path.abspath(options["corpus"]) == os.path.abspath(EVAL_CORPUS):
            min_score = FIXTURE_MIN_SCORE
        else:
            min_score = rag.MIN_SCORE

        self.stdout.write(f"Indexing {options['corpus']} ...")
        with isolated_index(
            options["corpus"],
            chunk_size=options["chunk_size"],
            chunk_overlap=options["chunk_overlap"],
        ) as indexed:
            chunks = len(indexed.documents)
            self.stdout.write(
                f"Indexed {chunks} chunks "
                f"(chunk_size={rag.CHUNK_SIZE}, overlap={rag.CHUNK_OVERLAP}, "
                f"model={rag.EMBED_MODEL}, min_score={min_score})\n"
            )
            rows, summary = evaluate(indexed, queries, top_k, min_score=min_score)

        summary["chunks"] = chunks
        summary["min_score"] = min_score
        self._report(rows, summary, top_k, options["verbosity"])

        if options["compare"]:
            self._compare(summary, options["compare"], top_k)

        if options["save_baseline"]:
            with open(options["save_baseline"], "w", encoding="utf-8", newline="\n") as handle:
                json.dump(summary, handle, indent=2, sort_keys=True)
                handle.write("\n")
            self.stdout.write(self.style.SUCCESS(f"\nBaseline written to {options['save_baseline']}"))

        if options["json_out"]:
            with open(options["json_out"], "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"summary": summary, "rows": rows}, handle, indent=2, sort_keys=True)
                handle.write("\n")

        self._enforce(summary, top_k, options)

    # ── Output ───────────────────────────────────────────────────────────────

    def _report(self, rows, summary, top_k, verbosity):
        if verbosity >= 2:
            self.stdout.write("Per query:")
            for row in rows:
                if row["relevant"]:
                    ok = row["hit"]
                    detail = f"want {row['relevant']}, got {row['retrieved'][:3]}"
                else:
                    ok = row["rejected"]
                    detail = "want nothing, got " + (str(row["retrieved"][:3]) or "nothing")
                mark = self.style.SUCCESS("  PASS") if ok else self.style.ERROR("  FAIL")
                self.stdout.write(f"{mark}  [{row['kind']}] {row['query']}\n         {detail}")
            self.stdout.write("")

        self.stdout.write("=" * 68)
        self.stdout.write(f"{'metric':<28}{'value':>12}")
        self.stdout.write("-" * 68)
        for label, key in (
            (f"hit rate @{top_k}", f"hit_rate@{top_k}"),
            ("MRR", "mrr"),
            ("rejection accuracy", "rejection_accuracy"),
            ("score separation", "score_separation"),
        ):
            self.stdout.write(f"{label:<28}{format_metric(summary.get(key)):>12}")

        self.stdout.write("-" * 68)
        self.stdout.write(f"{'by kind':<28}{'hit rate':>12}{'MRR':>12}{'reject':>12}")
        for kind, stats in summary["by_kind"].items():
            self.stdout.write(
                f"{kind:<28}"
                f"{format_metric(stats['hit_rate']):>12}"
                f"{format_metric(stats['mrr']):>12}"
                f"{format_metric(stats['rejection_accuracy']):>12}"
            )
        self.stdout.write("=" * 68)

    def _compare(self, summary, path, top_k):
        with open(path, "r", encoding="utf-8") as handle:
            before = json.load(handle)

        self.stdout.write("\nAgainst baseline:")
        for label, key in (
            (f"hit rate @{top_k}", f"hit_rate@{top_k}"),
            ("MRR", "mrr"),
            ("rejection accuracy", "rejection_accuracy"),
            ("score separation", "score_separation"),
        ):
            old, new = before.get(key), summary.get(key)
            if old is None or new is None:
                self.stdout.write(f"  {label:<26}{format_metric(old)} -> {format_metric(new)}")
                continue
            delta = new - old
            arrow = "+" if delta > 0 else ""
            style = self.style.SUCCESS if delta >= 0 else self.style.ERROR
            self.stdout.write(
                f"  {label:<26}{old:.3f} -> {new:.3f}  " + style(f"{arrow}{delta:.3f}")
            )

    def _enforce(self, summary, top_k, options):
        checks = (
            ("hit rate", summary.get(f"hit_rate@{top_k}"), options["fail_under_hit_rate"]),
            ("MRR", summary.get("mrr"), options["fail_under_mrr"]),
            ("rejection accuracy", summary.get("rejection_accuracy"), options["fail_under_rejection"]),
        )
        failures = [
            f"{name} {value:.3f} is below the required {floor:.3f}"
            for name, value, floor in checks
            if floor is not None and value is not None and value < floor
        ]
        if failures:
            raise CommandError("Retrieval quality regressed:\n  " + "\n  ".join(failures))
