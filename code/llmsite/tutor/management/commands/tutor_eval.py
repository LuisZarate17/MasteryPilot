"""Measure whether the tutor holds its place in a problem.

    python manage.py tutor_eval
    python manage.py tutor_eval --runs 5          # more samples per scenario
    python manage.py tutor_eval -v 2              # print every turn
    python manage.py tutor_eval --json out.json   # machine-readable rows

Needs requirements-llm.txt and a GPU worth using — it runs real generation.
The test suite mocks the adapter by design, so this is the tool that answers
"does the tutor still lose its place", which the suite structurally cannot.

Drives the real views through Django's test client rather than the adapter
directly, so the measurement includes everything api_chat does: the progress
ledger, the topic-change clear, the stall regeneration. Measuring the adapter
alone would miss the machinery that exists to fix the problem being measured.

Sampling is at temperature 0.7, so one run of one scenario is a draw and not a
measurement. --runs defaults to 3 for that reason; anything below that is
noise. Expect the whole thing to take a couple of minutes.
"""

import json
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.urls import reverse

from ._tutor_harness import SCENARIOS, score_replies, summarise, trailing_question

# django.test.Client sends Host: testserver, which ALLOWED_HOSTS rejects outside
# a test run - the suite gets away with it because setup_test_environment()
# whitelists it, and that has not run here. Every request then 400s.
#
# This is worth a comment because of how it failed: the first version treated a
# non-200 as an empty reply, so all four turns scored "no-question" and the
# command reported 2/2 clean while making no successful request at all. A
# measurement tool that reports success when it is broken is worse than no tool,
# which is why _post below raises instead.
TEST_CLIENT_HOST = "testserver"


class Command(BaseCommand):
    help = "Run scripted tutoring conversations and report rewinds and stalls."

    def add_arguments(self, parser):
        parser.add_argument("--runs", type=int, default=3,
                            help="Runs per scenario (default 3; fewer is noise).")
        parser.add_argument("--scenario", default=None,
                            help="Run only the scenario with this name.")
        parser.add_argument("--json", dest="json_out", default=None,
                            help="Write per-run rows to this path.")

    def handle(self, *args, **options):
        scenarios = SCENARIOS
        if options["scenario"]:
            scenarios = [s for s in SCENARIOS if s["name"] == options["scenario"]]
            if not scenarios:
                names = ", ".join(s["name"] for s in SCENARIOS)
                self.stderr.write(f"No scenario named {options['scenario']!r}. "
                                  f"Choose from: {names}")
                return

        runs = max(1, options["runs"])
        verbose = options["verbosity"] >= 2
        rows = []

        # A throwaway student, removed afterwards. Sessions and chats cascade,
        # so the evaluation leaves the database as it found it - this runs
        # against the real one, unlike the suite.
        User = get_user_model()
        username = f"tutor-eval-{uuid.uuid4().hex[:8]}"
        student = User.objects.create_user(
            username=username, password=uuid.uuid4().hex,
        )

        allowed = list(settings.ALLOWED_HOSTS)
        if TEST_CLIENT_HOST not in allowed:
            settings.ALLOWED_HOSTS = allowed + [TEST_CLIENT_HOST]

        try:
            for scenario in scenarios:
                self.stdout.write(self.style.MIGRATE_HEADING(
                    f"\n{scenario['name']} - tutor must {scenario['expect']} "
                    f"({runs} runs)"
                ))
                for run in range(1, runs + 1):
                    row = self._run_once(student, scenario, run, verbose)
                    rows.append(row)
                    self.stdout.write(
                        f"  run {run}: {row['verdicts']}  "
                        f"rewinds={row['rewinds']} stalls={row['stalls']}"
                    )
        finally:
            student.delete()
            settings.ALLOWED_HOSTS = allowed

        self._report(scenarios, rows, options["json_out"])

    def _post(self, client, name, payload):
        """POST to a named endpoint, refusing to continue on anything but 200.

        Never swallows a failure into an empty reply: an empty reply scores as
        "no-question", which counts as neither a rewind nor a stall, so a run
        that failed every request would report as perfectly clean.
        """
        response = client.post(
            reverse(name), data=json.dumps(payload),
            content_type="application/json",
        )
        if response.status_code != 200:
            body = response.content.decode("utf-8", "replace")[:200]
            raise CommandError(
                f"{name} returned {response.status_code}, so nothing was "
                f"measured: {body}"
            )
        return response.json()

    def _run_once(self, student, scenario, run, verbose):
        client = Client()
        client.force_login(student)
        self._post(client, "api_new_session", {})

        replies = []
        for turn in scenario["turns"]:
            reply = self._post(client, "api_chat", {"message": turn}).get("model_text", "")
            if not reply.strip():
                raise CommandError(
                    f"api_chat returned an empty reply for {turn!r}. The model "
                    f"is probably not loaded - check requirements-llm.txt."
                )
            replies.append(reply)
            if verbose:
                self.stdout.write(f"    student: {turn}")
                self.stdout.write(f"    tutor:   {reply[:120]}")

        verdicts = score_replies(replies)
        return {
            "scenario": scenario["name"],
            "run": run,
            "turns": scenario["turns"],
            "replies": replies,
            "questions": [trailing_question(r) for r in replies],
            "verdicts": verdicts,
            "rewinds": verdicts.count("REWIND"),
            "stalls": verdicts.count("STALL"),
        }

    def _report(self, scenarios, rows, json_out):
        self.stdout.write(self.style.MIGRATE_HEADING("\nSummary"))
        for scenario in scenarios:
            mine = [r for r in rows if r["scenario"] == scenario["name"]]
            clean = sum(1 for r in mine if not (r["rewinds"] + r["stalls"]))
            self.stdout.write(
                f"  {scenario['name']:<22} clean {clean}/{len(mine)}   "
                f"rewinds {sum(r['rewinds'] for r in mine)}   "
                f"stalls {sum(r['stalls'] for r in mine)}"
            )

        totals = summarise(rows)
        self.stdout.write("")
        self.stdout.write(f"  clean runs: {totals['clean_runs']}/{totals['runs']}"
                          f"  ({totals['clean_rate']:.0%})")
        self.stdout.write(f"  rewinds:    {totals['rewinds']}")
        self.stdout.write(f"  stalls:     {totals['stalls']}")

        if json_out:
            with open(json_out, "w", encoding="utf-8") as handle:
                json.dump({"summary": totals, "rows": rows}, handle,
                          indent=2, ensure_ascii=False)
            self.stdout.write(self.style.SUCCESS(f"\nwrote {json_out}"))
