"""Quiz extraction, persistence and grading.

The centrepiece here is the answer-index convention, which is split across two
languages and was wrong in the template for months (fixed in 6d9d6ec).

    model emits `correct`  ->  0-based, as a string
    radio input value      ->  1-based  (chat.html: value='${i + 1}')
    api_grade_quiz         ->  (int(user) - 1) == int(correct)

The server side has always been right. The original fix was in template
JavaScript, where nothing guards it, so these tests pin the convention on the
server instead — if anyone "corrects" the -1 in api_grade_quiz, this fails.
"""

from django.urls import reverse
import json

from ..models import Quiz, QuizAnswer
from ..views.chat import (
    _is_duplicate_quiz,
    _looks_like_quiz_request,
    _maybe_persist_quiz,
    _try_extract_quiz_json,
    shuffle_quiz,
)
from .base import MasteryPilotTestCase


class QuizGradingConventionTests(MasteryPilotTestCase):
    """Regression coverage for 6d9d6ec — the off-by-one correct-answer index."""

    def setUp(self):
        self.student = self.make_student("quiz_student")
        self.client.force_login(self.student)
        self.session = self.make_session(self.student)
        self.set_active_session(self.session)

    def grade(self, answers):
        return self.client.post(
            reverse("api_grade_quiz"),
            data=json.dumps({"answers": answers}),
            content_type="application/json",
        )

    def graded_json(self):
        return QuizAnswer.objects.get(quiz__session=self.session).graded_json

    def test_correct_zero_is_graded_against_the_first_choice(self):
        """correct="0" + the student picking choice 1 must grade correct.

        This is the exact case 6d9d6ec was about: the old template compared
        `correct` to the 1-based label, so correct=0 matched no choice at all
        and highlighted nothing.
        """
        self.make_quiz(self.session, {"q1": self.mc_question(correct="0")})

        response = self.grade("1")

        self.assertEqual(response.status_code, 200)
        graded = self.graded_json()
        self.assertTrue(graded["q1"]["isCorrect"])
        self.assertEqual(graded["q1"]["correctAnswer"], "4")
        self.assertEqual(graded["q1"]["studentAnswer"], "4")

    def test_matching_the_raw_index_is_graded_incorrect(self):
        """correct="0" + answer "0" is -1 == 0, i.e. wrong.

        Pins the asymmetry: the two sides are not on the same base, so a
        student "answer" that equals the correct index must not pass.
        """
        self.make_quiz(self.session, {"q1": self.mc_question(correct="0")})

        self.grade("0")

        self.assertFalse(self.graded_json()["q1"]["isCorrect"])

    def test_last_choice_index_grades_correct(self):
        self.make_quiz(self.session, {"q1": self.mc_question(correct="3")})

        self.grade("4")

        graded = self.graded_json()
        self.assertTrue(graded["q1"]["isCorrect"])
        self.assertEqual(graded["q1"]["correctAnswer"], "7")

    def test_off_by_one_answer_grades_incorrect(self):
        """The failure the old template made invisible: neighbouring choice."""
        self.make_quiz(self.session, {"q1": self.mc_question(correct="1")})

        self.grade("3")

        graded = self.graded_json()
        self.assertFalse(graded["q1"]["isCorrect"])
        self.assertEqual(graded["q1"]["correctAnswer"], "5")
        self.assertEqual(graded["q1"]["studentAnswer"], "6")

    def test_every_index_in_a_four_choice_question_lines_up(self):
        """Walk the whole range rather than trusting two sampled points."""
        for zero_based in range(4):
            with self.subTest(correct=zero_based):
                Quiz.objects.filter(session=self.session).delete()
                self.make_quiz(
                    self.session, {"q1": self.mc_question(correct=str(zero_based))}
                )

                self.grade(str(zero_based + 1))

                graded = QuizAnswer.objects.get(
                    quiz__session=self.session
                ).graded_json
                self.assertTrue(graded["q1"]["isCorrect"])


class QuizGradingTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("grade_student")
        self.client.force_login(self.student)
        self.session = self.make_session(self.student)
        self.set_active_session(self.session)

    def grade(self, answers):
        return self.client.post(
            reverse("api_grade_quiz"),
            data=json.dumps({"answers": answers}),
            content_type="application/json",
        )

    def test_grading_scores_and_closes_the_quiz(self):
        quiz = self.make_quiz(
            self.session,
            {
                "q1": self.mc_question(correct="0"),
                "q2": self.mc_question(correct="1"),
                "q3": self.mc_question(correct="2"),
            },
        )

        response = self.grade("1,3,3")

        self.assertEqual(response.status_code, 200)
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, "graded")
        self.assertEqual(quiz.possible_pts, 3.0)
        self.assertEqual(quiz.earned_pts, 2.0)  # q2 wrong
        self.assertIsNotNone(quiz.ended_at)

    def test_points_key_is_honoured(self):
        self.make_quiz(
            self.session,
            {
                "q1": self.mc_question(correct="0", points=5),
                "q2": self.mc_question(correct="0"),
            },
        )

        self.grade("1,2")

        quiz = Quiz.objects.get(session=self.session)
        self.assertEqual(quiz.possible_pts, 6.0)
        self.assertEqual(quiz.earned_pts, 5.0)

    def test_non_numeric_answers_compare_case_insensitively(self):
        self.make_quiz(
            self.session,
            {"q1": {"question": "Capital of France?", "type": "short-answer", "correct": "Paris"}},
        )

        self.grade("paris")

        graded = QuizAnswer.objects.get(quiz__session=self.session).graded_json
        self.assertTrue(graded["q1"]["isCorrect"])

    def test_missing_answers_are_graded_incorrect_not_an_error(self):
        """Fewer submitted answers than questions must not raise IndexError."""
        self.make_quiz(
            self.session,
            {"q1": self.mc_question(correct="0"), "q2": self.mc_question(correct="0")},
        )

        response = self.grade("1")

        self.assertEqual(response.status_code, 200)
        graded = QuizAnswer.objects.get(quiz__session=self.session).graded_json
        self.assertTrue(graded["q1"]["isCorrect"])
        self.assertFalse(graded["q2"]["isCorrect"])

    def test_out_of_range_correct_index_falls_back_to_the_raw_value(self):
        self.make_quiz(
            self.session,
            {"q1": self.mc_question(answers=["a", "b"], correct="9")},
        )

        self.grade("1")

        graded = QuizAnswer.objects.get(quiz__session=self.session).graded_json
        self.assertEqual(graded["q1"]["correctAnswer"], "9")

    def test_response_reports_per_question_feedback(self):
        self.make_quiz(
            self.session,
            {"q1": self.mc_question(correct="0"), "q2": self.mc_question(correct="0")},
        )

        response = self.grade("1,4")

        feedback = json.loads(json.loads(response.content)["model_text"])
        self.assertTrue(feedback["q1"].startswith("correct"))
        self.assertTrue(feedback["q2"].startswith("incorrect"))

    def test_grading_without_an_active_quiz_reports_an_error(self):
        response = self.grade("1")

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertTrue(payload["error"])
        self.assertEqual(payload["model_text"], "No active quiz")

    def test_grading_without_a_session_is_rejected(self):
        s = self.client.session
        s.pop("session_id", None)
        s.save()

        self.assertEqual(self.grade("1").status_code, 400)

    def test_grading_requires_owning_the_session(self):
        intruder = self.make_student("quiz_intruder")
        self.client.force_login(intruder)
        self.set_active_session(self.session)

        self.assertEqual(self.grade("1").status_code, 400)

    def test_empty_answers_are_rejected(self):
        self.make_quiz(self.session, {"q1": self.mc_question()})

        self.assertEqual(self.grade("").status_code, 400)

    def test_malformed_json_body_is_rejected(self):
        self.make_quiz(self.session, {"q1": self.mc_question()})

        response = self.client.post(
            reverse("api_grade_quiz"), data="not json", content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)


class QuizExtractionTests(MasteryPilotTestCase):
    """_try_extract_quiz_json — pure, no DB, no model."""

    QUIZ = '{"test": {"q1": {"question": "2+2?", "answers": ["4"], "correct": "0"}}}'

    def test_bare_json_object(self):
        self.assertEqual(
            _try_extract_quiz_json(self.QUIZ)["test"]["q1"]["correct"], "0"
        )

    def test_fenced_json_block(self):
        self.assertIsNotNone(_try_extract_quiz_json(f"```json\n{self.QUIZ}\n```"))

    def test_unlabelled_fenced_block(self):
        self.assertIsNotNone(_try_extract_quiz_json(f"```\n{self.QUIZ}\n```"))

    def test_surrounding_prose_is_ignored(self):
        text = f"Sure! Here is your quiz:\n{self.QUIZ}\nGood luck!"
        self.assertIsNotNone(_try_extract_quiz_json(text))

    def test_single_quotes_are_recovered(self):
        self.assertIsNotNone(
            _try_extract_quiz_json("{'test': {'q1': {'correct': '0'}}}")
        )

    def test_trailing_commas_are_recovered(self):
        self.assertIsNotNone(
            _try_extract_quiz_json('{"test": {"q1": {"correct": "0",},}}')
        )

    def test_quiz_and_questions_keys_are_normalised_to_test(self):
        for key in ("quiz", "questions"):
            with self.subTest(key=key):
                result = _try_extract_quiz_json('{"%s": {"q1": {"correct": "0"}}}' % key)
                self.assertIn("test", result)

    def test_bare_question_keys_are_treated_as_a_test(self):
        result = _try_extract_quiz_json('{"q1": {"question": "2+2?", "correct": "0"}}')
        self.assertIn("q1", result["test"])

    def test_non_quiz_content_returns_none(self):
        for text in ("", None, "Just a normal reply.", "{not json at all", '{"foo": 1}'):
            with self.subTest(text=text):
                self.assertIsNone(_try_extract_quiz_json(text))


class QuizPersistenceTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("persist_student")
        self.session = self.make_session(self.student)

    def test_a_quiz_reply_creates_an_active_quiz(self):
        created = _maybe_persist_quiz(
            self.session, '{"test": {"q1": {"question": "2+2?", "correct": "0"}}}'
        )

        self.assertTrue(created)
        self.assertEqual(Quiz.objects.filter(session=self.session, status="active").count(), 1)

    def test_a_plain_reply_creates_nothing(self):
        self.assertFalse(_maybe_persist_quiz(self.session, "Let me explain fractions."))
        self.assertFalse(Quiz.objects.filter(session=self.session).exists())

    def test_a_new_quiz_supersedes_the_previous_active_one(self):
        """The one_active_quiz_per_session constraint makes this mandatory."""
        first = self.make_quiz(self.session, {"q1": self.mc_question()})

        _maybe_persist_quiz(
            self.session, '{"test": {"q2": {"question": "3+3?", "correct": "1"}}}'
        )

        first.refresh_from_db()
        self.assertEqual(first.status, "submitted")
        self.assertIsNotNone(first.ended_at)
        self.assertEqual(Quiz.objects.filter(session=self.session, status="active").count(), 1)

    def test_the_stored_quiz_is_returned_as_canonical_text(self):
        """The caller must send on what was stored, not the model's raw reply.

        The options are shuffled during persistence, so the two disagree about
        which index is correct. Showing the student the raw reply while grading
        against the stored quiz marks right answers wrong.
        """
        canonical = _maybe_persist_quiz(
            self.session,
            '{"test": {"q1": {"question": "2+2?", "type": "multiple-choice",'
            ' "answers": ["4", "5", "6", "7"], "correct": "0"}}}',
        )
        stored = Quiz.objects.get(session=self.session, status="active")

        self.assertEqual(json.loads(canonical), stored.quiz_json)

    def test_the_shuffled_correct_index_still_points_at_the_right_answer(self):
        _maybe_persist_quiz(
            self.session,
            '{"test": {"q1": {"question": "2+2?", "type": "multiple-choice",'
            ' "answers": ["4", "5", "6", "7"], "correct": "0"}}}',
        )
        item = Quiz.objects.get(session=self.session).quiz_json["test"]["q1"]

        self.assertEqual(item["answers"][int(item["correct"])], "4")


class QuizShuffleTests(MasteryPilotTestCase):
    """Answer order is randomised so the first option is not usually right.

    Measured 2026-08-13: the correct answer sat at index 0 in 9 of 13 quizzes
    (11 of 12 on Qwen3-8B), so always picking the first option scored ~70%.
    """

    class FixedRng:
        """A deterministic stand-in: reverses instead of shuffling."""

        @staticmethod
        def shuffle(seq):
            seq.reverse()

    def question(self, correct="0", answers=None):
        return {
            "test": {
                "q1": {
                    "question": "2+2?",
                    "type": "multiple-choice",
                    "answers": answers if answers is not None else ["4", "5", "6", "7"],
                    "correct": correct,
                }
            }
        }

    def test_the_correct_answer_moves_with_its_options(self):
        out = shuffle_quiz(self.question(correct="0"), rng=self.FixedRng)["test"]["q1"]

        self.assertEqual(out["answers"], ["7", "6", "5", "4"])
        self.assertEqual(out["correct"], "3")
        self.assertEqual(out["answers"][int(out["correct"])], "4")

    def test_the_right_answer_text_survives_every_starting_position(self):
        for index in range(4):
            with self.subTest(correct=index):
                original = self.question(correct=str(index))
                was = original["test"]["q1"]["answers"][index]

                out = shuffle_quiz(original, rng=self.FixedRng)["test"]["q1"]

                self.assertEqual(out["answers"][int(out["correct"])], was)

    def test_a_real_shuffle_does_not_leave_the_answer_pinned_to_index_zero(self):
        """The point of the exercise, over enough draws to be meaningful."""
        positions = {
            shuffle_quiz(self.question(correct="0"))["test"]["q1"]["correct"]
            for _ in range(40)
        }

        self.assertGreater(len(positions), 1)

    def test_the_input_is_not_mutated(self):
        original = self.question(correct="0")

        shuffle_quiz(original, rng=self.FixedRng)

        self.assertEqual(original["test"]["q1"]["answers"], ["4", "5", "6", "7"])
        self.assertEqual(original["test"]["q1"]["correct"], "0")

    def test_a_short_answer_question_is_left_alone(self):
        quiz = {"test": {"q1": {"question": "2+2?", "type": "short-answer",
                                "correct": "four"}}}

        self.assertEqual(shuffle_quiz(quiz, rng=self.FixedRng), quiz)

    def test_a_non_numeric_correct_value_is_left_alone(self):
        """Grading falls back to string comparison; reordering would break it."""
        quiz = self.question(correct="four")

        out = shuffle_quiz(quiz, rng=self.FixedRng)["test"]["q1"]

        self.assertEqual(out["answers"], ["4", "5", "6", "7"])
        self.assertEqual(out["correct"], "four")

    def test_an_out_of_range_index_is_left_alone(self):
        out = shuffle_quiz(self.question(correct="9"), rng=self.FixedRng)["test"]["q1"]

        self.assertEqual(out["answers"], ["4", "5", "6", "7"])
        self.assertEqual(out["correct"], "9")

    def test_a_single_option_is_left_alone(self):
        out = shuffle_quiz(
            self.question(correct="0", answers=["only"]), rng=self.FixedRng
        )["test"]["q1"]

        self.assertEqual(out["answers"], ["only"])
        self.assertEqual(out["correct"], "0")

    def test_every_question_is_shuffled_not_just_the_first(self):
        quiz = {"test": {
            "q1": {"type": "multiple-choice", "answers": ["a", "b"], "correct": "0"},
            "q2": {"type": "multiple-choice", "answers": ["c", "d"], "correct": "0"},
        }}

        out = shuffle_quiz(quiz, rng=self.FixedRng)["test"]

        self.assertEqual(out["q1"]["correct"], "1")
        self.assertEqual(out["q2"]["correct"], "1")


class QuizRequestDetectionTests(MasteryPilotTestCase):
    """Used only to decide whether an unparseable reply is worth regenerating."""

    def test_the_phrasings_that_failed_live_are_recognised(self):
        for text in ["Test me on combining like terms.",
                     "Test my knowledge of the distributive property.",
                     "Could you test me on solving for x?"]:
            with self.subTest(text=text):
                self.assertTrue(_looks_like_quiz_request(text))

    def test_ordinary_quiz_wording_is_recognised(self):
        for text in ["quiz me", "Can I have a quiz?", "practice questions please",
                     "check my understanding of slope"]:
            with self.subTest(text=text):
                self.assertTrue(_looks_like_quiz_request(text))

    def test_ordinary_tutoring_is_not(self):
        for text in ["I need help solving 3x + 7 = 22.", "Continue",
                     "Why did you subtract that?", ""]:
            with self.subTest(text=text):
                self.assertFalse(_looks_like_quiz_request(text))


class DuplicateQuizDetectionTests(MasteryPilotTestCase):
    """A second quiz request must not return the first quiz.

    The model is handed the whole conversation, its own previous quiz included,
    so on "give me another one" it frequently re-emits that quiz. Nothing used
    to catch it: the stall check in api_chat is deliberately skipped for quiz
    requests, and _try_extract_quiz_json only asks whether the JSON parses.
    """

    def setUp(self):
        self.student = self.make_student("dupe_student")
        self.session = self.make_session(self.student)

    @staticmethod
    def quiz(*questions):
        return {"test": {
            f"q{i}": {"question": q, "type": "multiple-choice",
                      "answers": ["a", "b"], "correct": "0"}
            for i, q in enumerate(questions, start=1)
        }}

    def test_nothing_asked_yet_is_never_a_duplicate(self):
        self.assertFalse(
            _is_duplicate_quiz(self.quiz("What is 2 + 2?"), self.session)
        )

    def test_the_same_questions_again_are_a_duplicate(self):
        self.make_quiz(self.session, self.quiz("What is 2 + 2?", "What is 3 + 3?")["test"])

        self.assertTrue(
            _is_duplicate_quiz(self.quiz("What is 2 + 2?", "What is 3 + 3?"), self.session)
        )

    def test_cosmetic_differences_are_still_a_duplicate(self):
        """Case and spacing are not a new quiz."""
        self.make_quiz(self.session, self.quiz("What is 2 + 2?", "What is 3 + 3?")["test"])

        self.assertTrue(
            _is_duplicate_quiz(
                self.quiz("what is 2 + 2?", "What  is   3 + 3?"), self.session
            )
        )

    def test_genuinely_different_questions_are_not_a_duplicate(self):
        self.make_quiz(self.session, self.quiz("What is 2 + 2?", "What is 3 + 3?")["test"])

        self.assertFalse(
            _is_duplicate_quiz(
                self.quiz("What is 9 - 4?", "Solve for x: x + 1 = 5"), self.session
            )
        )

    def test_one_shared_question_out_of_three_is_ordinary_overlap(self):
        """Two quizzes on one topic will collide sometimes. That is not a repeat."""
        self.make_quiz(
            self.session,
            self.quiz("What is 2 + 2?", "What is 3 + 3?", "What is 4 + 4?")["test"],
        )

        self.assertFalse(
            _is_duplicate_quiz(
                self.quiz("What is 2 + 2?", "What is 7 - 1?", "What is 8 / 2?"),
                self.session,
            )
        )

    def test_a_duplicate_of_an_older_quiz_still_counts(self):
        """Not just the most recent one — the whole session is checked."""
        self.make_quiz(self.session, self.quiz("What is 2 + 2?")["test"], status="graded")
        self.make_quiz(self.session, self.quiz("Name a prime number")["test"])

        self.assertTrue(_is_duplicate_quiz(self.quiz("What is 2 + 2?"), self.session))

    def test_a_quiz_with_no_questions_is_not_a_duplicate(self):
        """Nothing to compare. The JSON retry owns malformed replies, not this."""
        self.make_quiz(self.session, self.quiz("What is 2 + 2?")["test"])

        self.assertFalse(_is_duplicate_quiz({"test": {}}, self.session))
        self.assertFalse(_is_duplicate_quiz(None, self.session))

    def test_a_session_with_no_quizzes_short_circuits(self):
        self.assertFalse(_is_duplicate_quiz(self.quiz("What is 2 + 2?"), None))
