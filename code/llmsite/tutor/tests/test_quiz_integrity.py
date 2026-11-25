"""Quiz integrity: the answer key, positional grading, and malformed quizzes.

Three things that were wrong together:

* The student's browser was sent the answer key (`correct`) with the quiz, both
  in the api_chat reply and in the history endpoint, so the quiz could be
  answered by reading the network tab.
* Grading was positional (a CSV), and the form pre-checked the first option, so
  a skipped question shifted every later answer onto the wrong question.
* A quiz the model got wrong (no question text, `correct` out of range, no
  options) was persisted as an active quiz that could not be answered correctly.
"""

import json
from unittest.mock import patch

from django.urls import reverse

from ..models import Chat as DBChat, Quiz, QuizAnswer
from ..views.chat import _redact_quiz, _try_extract_quiz_json
from .base import FakeAdapter, MasteryPilotTestCase
from .test_chat import LoadedModel


def quiz_reply(n=3):
    """A well-formed quiz as the model emits it: n four-option MC questions."""
    return json.dumps({
        "test": {
            f"q{i}": {
                "question": f"What is {i} + {i}?",
                "type": "multiple-choice",
                "answers": [str(i * 2), "100", "101", "102"],
                "correct": "0",
            }
            for i in range(1, n + 1)
        }
    })


def has_correct_key(value):
    """True if any dict anywhere inside *value* has a "correct" key."""
    if isinstance(value, dict):
        return "correct" in value or any(has_correct_key(v) for v in value.values())
    if isinstance(value, list):
        return any(has_correct_key(v) for v in value)
    return False


class QuizChatTestCase(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("integrity_student")
        self.client.force_login(self.student)
        self.session = self.make_session(self.student)
        self.set_active_session(self.session)
        self.bootstrap_session(self.session)

    def send(self, message="Give me a quiz", **extra):
        return self.client.post(
            reverse("api_chat"),
            data=json.dumps({"message": message, **extra}),
            content_type="application/json",
        )

    def ask_for_quiz(self, reply=None):
        with LoadedModel(FakeAdapter(reply=reply or quiz_reply())):
            response = self.send()
        self.assertEqual(response.status_code, 200)
        return response

    def messages(self, user=None):
        if user is not None:
            self.client.force_login(user)
        response = self.client.get(
            reverse("api_session_messages", args=[self.session.id])
        )
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def grade(self, answers):
        return self.client.post(
            reverse("api_grade_quiz"),
            data=json.dumps({"answers": answers, "session_id": str(self.session.id)}),
            content_type="application/json",
        )

    def right_answers(self, quiz):
        """{qid: 1-based option number} that grades every question correct."""
        return {
            qid: str(int(q["correct"]) + 1) for qid, q in quiz.quiz_json["test"].items()
        }


class AnswerKeyIsWithheldTests(QuizChatTestCase):
    def test_a_quiz_reply_sent_to_the_student_carries_no_answer_key(self):
        response = self.ask_for_quiz()

        body = json.loads(response.content)
        quiz = json.loads(body["model_text"])
        self.assertEqual(set(quiz["test"]), {"q1", "q2", "q3"})
        self.assertFalse(has_correct_key(quiz))
        self.assertNotIn(b'"correct"', response.content)
        # And what is left is still a usable quiz.
        self.assertEqual(len(quiz["test"]["q1"]["answers"]), 4)

    def test_the_stored_assistant_row_and_quiz_keep_the_answer_key(self):
        self.ask_for_quiz()

        stored = DBChat.objects.filter(session=self.session, role="assistant").last()
        self.assertIn('"correct"', stored.message)
        quiz = Quiz.objects.get(session=self.session, status="active")
        self.assertTrue(has_correct_key(quiz.quiz_json))
        # The row is the stored quiz as shuffled, so history and grading agree.
        self.assertEqual(json.loads(stored.message), quiz.quiz_json)

    def test_the_options_the_student_sees_are_the_options_graded_against(self):
        response = self.ask_for_quiz()

        shown = json.loads(json.loads(response.content)["model_text"])
        quiz = Quiz.objects.get(session=self.session)
        for qid, question in quiz.quiz_json["test"].items():
            self.assertEqual(shown["test"][qid]["answers"], question["answers"])

    def test_redacting_does_not_touch_the_original(self):
        original = json.loads(quiz_reply(1))

        redacted = _redact_quiz(original)

        self.assertTrue(has_correct_key(original))
        self.assertFalse(has_correct_key(redacted))
        self.assertEqual(redacted["test"]["q1"]["question"], original["test"]["q1"]["question"])

    def test_history_for_the_owner_hides_the_key_of_an_unanswered_quiz(self):
        self.ask_for_quiz()

        payload = self.messages()

        quiz_messages = [
            m for m in payload["messages"]
            if m["role"] == "assistant" and "multiple-choice" in m["text"]
        ]
        self.assertEqual(len(quiz_messages), 1)
        self.assertNotIn('"correct"', quiz_messages[0]["text"])
        self.assertEqual(len(json.loads(quiz_messages[0]["text"])["test"]), 3)
        self.assertEqual(len(payload["quiz_attempts"]), 1)
        for item in payload["quiz_attempts"][0]["items"]:
            self.assertEqual(item["correct_answer"], "")
        self.assertNotIn("correct\"", json.dumps(payload["messages"]))

    def test_history_for_the_owner_shows_the_key_once_the_quiz_is_graded(self):
        self.ask_for_quiz()
        quiz = Quiz.objects.get(session=self.session)
        self.assertEqual(self.grade(self.right_answers(quiz)).status_code, 200)

        payload = self.messages()

        quiz_text = next(
            m["text"] for m in payload["messages"]
            if m["role"] == "assistant" and "multiple-choice" in m["text"]
        )
        self.assertTrue(has_correct_key(json.loads(quiz_text)))
        for item in payload["quiz_attempts"][0]["items"]:
            self.assertNotEqual(item["correct_answer"], "")

    def test_a_teacher_sees_the_key_of_an_unanswered_quiz(self):
        teacher = self.make_teacher("integrity_teacher")
        self.student.studentprofile.teacher = teacher.teacherprofile
        self.student.studentprofile.save()
        self.ask_for_quiz()

        payload = self.messages(user=teacher)

        quiz_text = next(
            m["text"] for m in payload["messages"]
            if m["role"] == "assistant" and "multiple-choice" in m["text"]
        )
        self.assertTrue(has_correct_key(json.loads(quiz_text)))
        for item in payload["quiz_attempts"][0]["items"]:
            self.assertNotEqual(item["correct_answer"], "")

    def test_an_admin_sees_the_key_of_an_unanswered_quiz(self):
        self.ask_for_quiz()

        payload = self.messages(user=self.make_admin("integrity_admin"))

        for item in payload["quiz_attempts"][0]["items"]:
            self.assertNotEqual(item["correct_answer"], "")

    def test_quizzes_are_matched_to_messages_by_order(self):
        """Only the unanswered quiz is redacted, whichever position it is in."""
        first = self.make_quiz(self.session, json.loads(quiz_reply(2))["test"], status="graded")
        first.started_at = first.started_at.replace(year=2020)
        first.save(update_fields=["started_at"])
        QuizAnswer.objects.create(
            quiz=first,
            answers_json={"q1": "1", "q2": "1"},
            graded_json={
                "q1": {"isCorrect": True},
                "q2": {"isCorrect": True},
            },
        )
        second_test = {
            "q1": self.mc_question("Second quiz?", correct="2"),
        }
        self.make_quiz(self.session, second_test)
        self.make_chat(self.session, "user", "quiz me")
        self.make_chat(self.session, "assistant", quiz_reply(2))
        self.make_chat(self.session, "user", "another")
        self.make_chat(self.session, "assistant", json.dumps({"test": second_test}))

        payload = self.messages()

        quiz_texts = [
            m["text"] for m in payload["messages"]
            if m["role"] == "assistant" and "multiple-choice" in m["text"]
        ]
        self.assertEqual(len(quiz_texts), 2)
        self.assertTrue(has_correct_key(json.loads(quiz_texts[0])))
        self.assertFalse(has_correct_key(json.loads(quiz_texts[1])))
        answered, unanswered = payload["quiz_attempts"]
        self.assertTrue(all(i["correct_answer"] for i in answered["items"]))
        self.assertTrue(all(i["correct_answer"] == "" for i in unanswered["items"]))

    def test_grading_returns_the_full_quiz(self):
        self.ask_for_quiz()
        quiz = Quiz.objects.get(session=self.session)

        response = self.grade(self.right_answers(quiz))

        body = json.loads(response.content)
        self.assertEqual(body["quiz"], quiz.quiz_json["test"])
        self.assertTrue(has_correct_key(body["quiz"]))
        for question in body["quiz"].values():
            self.assertIn("correct", question)


class GradingByQuestionIdTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("by_qid_student")
        self.client.force_login(self.student)
        self.session = self.make_session(self.student)
        self.set_active_session(self.session)
        self.quiz = self.make_quiz(
            self.session,
            {
                "q1": self.mc_question(correct="0"),
                "q2": self.mc_question(correct="1"),
                "q3": self.mc_question(correct="2"),
            },
        )

    def grade(self, answers):
        return self.client.post(
            reverse("api_grade_quiz"),
            data=json.dumps({"answers": answers, "session_id": str(self.session.id)}),
            content_type="application/json",
        )

    def graded(self):
        return QuizAnswer.objects.get(quiz=self.quiz).graded_json

    def test_a_skipped_question_does_not_shift_the_later_answers(self):
        response = self.grade({"q1": "1", "q3": "3"})

        self.assertEqual(response.status_code, 200)
        graded = self.graded()
        self.assertTrue(graded["q1"]["isCorrect"])
        self.assertFalse(graded["q2"]["isCorrect"])
        self.assertTrue(graded["q3"]["isCorrect"])
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.earned_pts, 2.0)
        self.assertEqual(self.quiz.possible_pts, 3.0)

    def test_the_skipped_question_is_reported_as_unanswered(self):
        response = self.grade({"q1": "1", "q3": "3"})

        feedback = json.loads(json.loads(response.content)["model_text"])
        self.assertEqual(feedback["q2"], "incorrect: Answer was 5")
        self.assertEqual(feedback["q1"], "correct")
        stored = QuizAnswer.objects.get(quiz=self.quiz).answers_json
        self.assertEqual(stored, {"q1": "1", "q2": "", "q3": "3"})

    def test_answers_are_matched_by_id_not_by_order_in_the_object(self):
        self.grade({"q3": "3", "q2": "2", "q1": "1"})

        self.assertTrue(all(g["isCorrect"] for g in self.graded().values()))

    def test_an_answer_for_an_unknown_question_is_ignored(self):
        response = self.grade({"q1": "1", "q9": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(self.graded()), {"q1", "q2", "q3"})

    def test_the_old_csv_string_still_grades_positionally(self):
        response = self.grade("1,2,3")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(g["isCorrect"] for g in self.graded().values()))
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.earned_pts, 3.0)

    def test_an_empty_dict_is_rejected(self):
        response = self.grade({})

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"answers is required", response.content)

    def test_an_empty_string_is_rejected(self):
        response = self.grade("")

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"answers is required", response.content)

    def test_a_list_or_a_number_is_rejected(self):
        for bad in (["1", "2", "3"], 2, 1.5, True):
            with self.subTest(answers=bad):
                self.assertEqual(self.grade(bad).status_code, 400)

        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.status, "active")


class PointsAreIgnoredTests(MasteryPilotTestCase):
    def test_a_model_supplied_points_value_cannot_change_the_total(self):
        student = self.make_student("points_student")
        self.client.force_login(student)
        session = self.make_session(student)
        self.set_active_session(session)
        quiz = self.make_quiz(
            session,
            {
                "q1": self.mc_question(correct="0", points="nan"),
                "q2": self.mc_question(correct="0", points="inf"),
                "q3": self.mc_question(correct="0", points="-5"),
                "q4": self.mc_question(correct="0", points="10"),
            },
        )

        response = self.client.post(
            reverse("api_grade_quiz"),
            data=json.dumps({"answers": {f"q{i}": "1" for i in range(1, 5)}}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        quiz.refresh_from_db()
        self.assertEqual(quiz.possible_pts, 4.0)
        self.assertEqual(quiz.earned_pts, 4.0)


class MalformedQuizTests(QuizChatTestCase):
    def extract(self, test):
        return _try_extract_quiz_json(json.dumps({"test": test}))

    def test_a_well_formed_quiz_is_accepted(self):
        self.assertIsNotNone(_try_extract_quiz_json(quiz_reply()))

    def test_a_question_that_is_not_an_object_is_rejected(self):
        self.assertIsNone(self.extract({"q1": "What is 2 + 2?"}))
        self.assertIsNone(self.extract({"q1": self.mc_question(), "q2": ["x"]}))

    def test_a_question_without_text_is_rejected(self):
        for bad in (None, "", "   ", 7):
            with self.subTest(question=bad):
                self.assertIsNone(self.extract({"q1": self.mc_question(question=bad)}))
        no_text = self.mc_question()
        del no_text["question"]
        self.assertIsNone(self.extract({"q1": no_text}))

    def test_a_correct_index_out_of_range_is_rejected(self):
        for bad in ("4", "9", "-1", "two", "", None, 4, [0], True):
            with self.subTest(correct=bad):
                self.assertIsNone(self.extract({"q1": self.mc_question(correct=bad)}))

    def test_a_correct_index_in_range_is_accepted_as_string_or_int(self):
        for good in ("0", "3", 0, 3):
            with self.subTest(correct=good):
                self.assertIsNotNone(self.extract({"q1": self.mc_question(correct=good)}))

    def test_a_multiple_choice_question_without_options_is_rejected(self):
        self.assertIsNone(self.extract({"q1": self.mc_question(answers=[], correct="0")}))
        no_options = self.mc_question()
        del no_options["answers"]
        self.assertIsNone(self.extract({"q1": no_options}))
        self.assertIsNone(self.extract({"q1": self.mc_question(answers="4,5,6")}))

    def test_an_empty_test_is_rejected(self):
        self.assertIsNone(self.extract({}))

    def test_one_bad_question_rejects_the_whole_quiz(self):
        self.assertIsNone(
            self.extract({"q1": self.mc_question(), "q2": self.mc_question(correct="9")})
        )

    def test_a_short_answer_question_with_no_options_is_still_accepted(self):
        """No `answers` list means nothing to index into; only the text is needed."""
        quiz = self.extract(
            {"q1": {"question": "Capital of France?", "type": "short-answer", "correct": "Paris"}}
        )

        self.assertIsNotNone(quiz)

    def test_a_malformed_quiz_reply_is_not_persisted_as_a_quiz(self):
        bad = {"q1": self.mc_question(correct="9")}
        with LoadedModel(FakeAdapter(reply=json.dumps({"test": bad}))) as adapter:
            response = self.send("Give me a quiz")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Quiz.objects.filter(session=self.session).exists())
        # The retry for an unparseable quiz ran: a second generation.
        self.assertEqual(len(adapter.send_message_calls), 2)

    def test_a_question_without_text_in_a_reply_is_not_persisted(self):
        bad = self.mc_question()
        del bad["question"]
        with LoadedModel(FakeAdapter(reply=json.dumps({"test": {"q1": bad}}))):
            self.send("Give me a quiz")

        self.assertFalse(Quiz.objects.filter(session=self.session).exists())


class QuizTurnStateTests(QuizChatTestCase):
    def test_the_turn_after_a_quiz_is_not_waiting_on_a_question(self):
        """The quiz JSON is full of question marks; none of them is pending."""
        self.ask_for_quiz()

        adapter = FakeAdapter(reply="Nice work.")
        with LoadedModel(adapter):
            self.send("Thanks")

        self.assertEqual(adapter.waiting_on_seen, [""])

    def test_a_prose_question_is_still_waited_on(self):
        """The control: the skip is for quizzes, not for every turn."""
        with LoadedModel(FakeAdapter(reply="Subtract 7. What is 15 / 3?")):
            self.send("How do I solve 3x + 7 = 22?")

        adapter = FakeAdapter(reply="Now divide.")
        with LoadedModel(adapter):
            self.send("15")

        self.assertEqual(adapter.waiting_on_seen, ["What is 15 / 3?"])


class QuizPersistenceFailureTests(QuizChatTestCase):
    def test_a_persistence_error_still_returns_a_normal_reply(self):
        with patch("tutor.views.chat._maybe_persist_quiz", side_effect=RuntimeError("db down")):
            with LoadedModel(FakeAdapter(reply="Subtract 7 from both sides.")):
                response = self.send("How do I solve 3x + 7 = 22?")

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["model_text"], "Subtract 7 from both sides.")
        self.assertNotIn("error", body)
        stored = DBChat.objects.filter(session=self.session, role="assistant").last()
        self.assertEqual(stored.message, "Subtract 7 from both sides.")
        # The reply was not a quiz, so it is recorded as a step as usual.
        self.session.refresh_from_db()
        self.assertEqual(self.session.progress_ledger, ["Subtract 7 from both sides."])

    def test_the_raw_reply_is_stored_and_its_key_still_withheld(self):
        raw = quiz_reply(1)
        with patch("tutor.views.chat._maybe_persist_quiz", side_effect=RuntimeError("db down")):
            with LoadedModel(FakeAdapter(reply=raw)):
                response = self.send("Give me a quiz")

        self.assertEqual(response.status_code, 200)
        stored = DBChat.objects.filter(session=self.session, role="assistant").last()
        self.assertEqual(stored.message, raw)
        self.assertNotIn(b'"correct"', response.content)
        self.assertFalse(Quiz.objects.filter(session=self.session).exists())
