"""The scoring behind `manage.py tutor_eval`.

The command itself needs a GPU and real weights; this file covers the part that
decides what counts as a failure, which is pure and belongs in the fast suite.

That split matters more than usual here. An earlier version of this scorer had
a false positive that inflated every rewind figure it produced for two days:
"what is the first step for 7 + 2 * 3" and the same sentence about 5x - 3 = 12
differ by ten characters in seventy, and difflib scored them 0.87 — above the
threshold. The tutor was correctly following the student to a new problem and
being marked for it. Requiring the numbers to match as well as the wording is
what fixed it, and the case is pinned below.
"""

from django.test import SimpleTestCase

from ..management.commands._tutor_harness import (
    SCENARIOS,
    same_question,
    score,
    score_replies,
    subject,
    summarise,
    trailing_question,
)


class TrailingQuestionTests(SimpleTestCase):
    def test_the_last_question_is_the_one_that_counts(self):
        text = "Subtract 7 from both sides. What is 15 divided by 3?"

        self.assertEqual(trailing_question(text), "what is 15 divided by 3")

    def test_a_reply_with_no_question_yields_nothing(self):
        self.assertEqual(trailing_question("Subtract 7 from both sides."), "")
        self.assertEqual(trailing_question(""), "")
        self.assertEqual(trailing_question(None), "")

    def test_punctuation_and_case_do_not_matter(self):
        self.assertEqual(
            trailing_question("What is 22 minus 7?"),
            trailing_question("what is 22 MINUS 7?"),
        )


class SubjectTests(SimpleTestCase):
    def test_two_questions_about_different_equations_differ(self):
        a = trailing_question("What is the first step for 5x - 3 = 12?")
        b = trailing_question("What is the first step for 7 + 2 * 3?")

        self.assertNotEqual(subject(a), subject(b))

    def test_the_same_question_has_the_same_subject(self):
        a = trailing_question("What is the first step for 5x - 3 = 12?")
        b = trailing_question("what is the first step for 5x - 3 = 12?")

        self.assertEqual(subject(a), subject(b))


class SameQuestionTests(SimpleTestCase):
    def test_identical_wording_about_a_different_problem_is_not_a_repeat(self):
        """The false positive that inflated two days of rewind figures."""
        a = trailing_question("What is the first step you would take to solve 5x - 3 = 12?")
        b = trailing_question("What is the first step you would take to solve 7 + 2 * 3?")

        self.assertFalse(same_question(a, b))

    def test_the_same_question_asked_again_is_a_repeat(self):
        a = trailing_question("What is the first step to solve 5x - 3 = 12?")
        b = trailing_question("What is the first step to solve 5x - 3 = 12?")

        self.assertTrue(same_question(a, b))


class ScoreTests(SimpleTestCase):
    def test_the_observed_failure_is_detected(self):
        """The 2026-08-13 transcript: turn 3 rewinds, turn 4 repeats turn 2."""
        replies = [
            "To solve 3x + 7 = 22, subtract 7 from both sides. What is 22 minus 7?",
            "The result is 15, so 3x = 15. Now divide by 3. What is 15 divided by 3?",
            "You must do the same to both sides to stay balanced. What is 22 minus 7?",
            "The result is 15, so 3x = 15. Now divide by 3. What is 15 divided by 3?",
        ]

        verdicts = score_replies(replies)

        self.assertEqual(verdicts.count("REWIND"), 2)

    def test_a_clean_progression_scores_no_failures(self):
        replies = [
            "Subtract 7 from both sides. What is 22 minus 7?",
            "So 3x = 15. What is 15 divided by 3?",
            "So x = 5. Does that make sense?",
            "Good. What problem would you like next?",
        ]

        verdicts = score_replies(replies)

        self.assertNotIn("REWIND", verdicts)
        self.assertNotIn("STALL", verdicts)

    def test_repeating_the_previous_reply_is_a_stall(self):
        replies = [
            "What is the first step for 7 + 2 * 3?",
            "What is the first step for 7 + 2 * 3?",
        ]

        self.assertEqual(score_replies(replies)[1], "STALL")

    def test_re_asking_in_new_words_is_a_hold_not_a_failure(self):
        """Pressing the same point differently is legitimate teaching."""
        replies = [
            "What is 22 minus 7?",
            "Take your time. What is 22 minus 7?",
        ]

        verdicts = score_replies(replies)

        self.assertEqual(verdicts[1], "hold")
        self.assertNotIn("REWIND", verdicts)

    def test_following_the_student_to_a_new_problem_is_advancing(self):
        replies = [
            "What is the first step you would take to solve 5x - 3 = 12?",
            "What is the next step after adding 3 to both sides?",
            "What is the first step you would take to solve 7 + 2 * 3?",
        ]

        verdicts = score_replies(replies)

        self.assertNotIn("REWIND", verdicts)
        self.assertNotIn("STALL", verdicts)


class SummariseTests(SimpleTestCase):
    def test_a_run_with_either_failure_is_not_clean(self):
        rows = [
            {"rewinds": 0, "stalls": 0},
            {"rewinds": 1, "stalls": 0},
            {"rewinds": 0, "stalls": 2},
            {"rewinds": 0, "stalls": 0},
        ]

        totals = summarise(rows)

        self.assertEqual(totals["runs"], 4)
        self.assertEqual(totals["clean_runs"], 2)
        self.assertEqual(totals["rewinds"], 1)
        self.assertEqual(totals["stalls"], 2)
        self.assertEqual(totals["clean_rate"], 0.5)

    def test_no_rows_does_not_divide_by_zero(self):
        self.assertEqual(summarise([])["clean_rate"], 0.0)


class ScenarioTests(SimpleTestCase):
    def test_every_scenario_is_usable(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario["name"]):
                self.assertTrue(scenario["expect"])
                self.assertGreaterEqual(len(scenario["turns"]), 2)

    def test_the_scenario_names_are_unique(self):
        names = [s["name"] for s in SCENARIOS]

        self.assertEqual(len(names), len(set(names)))

    def test_the_clarification_case_is_present(self):
        """The conversation shape that failed against real weights."""
        names = [s["name"] for s in SCENARIOS]

        self.assertIn("clarify-mid-problem", names)
        self.assertIn("abandon-and-switch", names)
