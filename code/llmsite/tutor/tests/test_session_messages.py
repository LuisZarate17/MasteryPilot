"""api_session_messages — the payload the chat and chat-history views render.

This endpoint is where the quiz answer-index convention crosses into the
template a second time, and where the read-only quiz renderers get their data.
The shape assertions here are deliberate: renderReadOnlyQuiz in
chat_history.html read `has_submission` off an *item* rather than off the
attempt, so the student-answer block never rendered for teachers. Pinning the
shape server-side is what makes that class of bug catchable.
"""

from django.urls import reverse
import json

from ..models import QuizAnswer
from .base import MasteryPilotTestCase


class SessionMessagesPayloadTests(MasteryPilotTestCase):
    def setUp(self):
        self.teacher = self.make_teacher("hist_teacher")
        self.student = self.make_student(
            "hist_student", teacher=self.teacher.teacherprofile
        )
        self.session = self.make_session(self.student, title="Fractions")

    def url(self):
        return reverse("api_session_messages", args=[self.session.id])

    def payload(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def graded_quiz(self):
        quiz = self.make_quiz(
            self.session,
            {"q1": self.mc_question(correct="0"), "q2": self.mc_question(correct="2")},
            status="graded",
        )
        QuizAnswer.objects.create(
            quiz=quiz,
            answers_json={"q1": "1", "q2": "1"},
            graded_json={
                "q1": {"isCorrect": True, "studentAnswer": "4", "correctAnswer": "4"},
                "q2": {"isCorrect": False, "studentAnswer": "4", "correctAnswer": "6"},
            },
        )
        return quiz

    def test_has_submission_is_on_the_attempt_not_its_items(self):
        """The exact shape renderReadOnlyQuiz got wrong.

        `has_submission` belongs to the attempt; items carry only
        qid/student_answer/correct_answer/is_correct. A template reading
        item.has_submission gets undefined and silently renders nothing.
        """
        self.graded_quiz()
        self.client.force_login(self.teacher)

        attempt = self.payload()["quiz_attempts"][0]

        self.assertTrue(attempt["has_submission"])
        self.assertEqual(
            set(attempt["items"][0]),
            {"qid", "student_answer", "correct_answer", "is_correct"},
        )
        self.assertNotIn("has_submission", attempt["items"][0])

    def test_an_ungraded_quiz_reports_no_submission(self):
        self.make_quiz(self.session, {"q1": self.mc_question()})
        self.client.force_login(self.teacher)

        self.assertFalse(self.payload()["quiz_attempts"][0]["has_submission"])

    def test_correct_answer_is_resolved_zero_based(self):
        """correct="2" is the third choice — not the second."""
        self.graded_quiz()
        self.client.force_login(self.teacher)

        items = {i["qid"]: i for i in self.payload()["quiz_attempts"][0]["items"]}

        self.assertEqual(items["q1"]["correct_answer"], "4")  # index 0
        self.assertEqual(items["q2"]["correct_answer"], "6")  # index 2

    def test_student_answer_is_resolved_one_based(self):
        """The stored token "1" means the student picked the first choice."""
        self.graded_quiz()
        self.client.force_login(self.teacher)

        items = {i["qid"]: i for i in self.payload()["quiz_attempts"][0]["items"]}

        self.assertEqual(items["q1"]["student_answer"], "4")
        self.assertEqual(items["q2"]["student_answer"], "4")
        self.assertTrue(items["q1"]["is_correct"])
        self.assertFalse(items["q2"]["is_correct"])

    def test_bootstrap_and_system_turns_are_hidden(self):
        self.make_chat(self.session, "system", "TUTOR SYSTEM PROMPT")
        self.make_chat(self.session, "user", "Here is your student information ...")
        self.make_chat(self.session, "user", "How do fractions work?")
        self.make_chat(self.session, "assistant", "A fraction is ...")
        self.client.force_login(self.student)

        messages = self.payload()["messages"]

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["text"], "How do fractions work?")
        self.assertNotIn(
            "student information", json.dumps(messages)
        )

    def test_legacy_bootstrap_shape_is_also_hidden(self):
        """Sessions written before the adapter consolidation used a bare form."""
        self.make_chat(
            self.session, "user", "Name: Ada\nSchool: WSU\nGrade: 11\nClasses: Math"
        )
        self.make_chat(self.session, "user", "Real question")
        self.client.force_login(self.student)

        messages = self.payload()["messages"]

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["text"], "Real question")

    def test_viewing_own_session_sets_it_active_for_chat(self):
        self.client.force_login(self.student)

        self.client.get(self.url())

        self.assertEqual(self.client.session["session_id"], str(self.session.id))

    def test_a_teacher_viewing_does_not_hijack_their_active_session(self):
        """Staff browsing history must not repoint their own chat session."""
        self.client.force_login(self.teacher)

        self.client.get(self.url())

        self.assertNotIn("session_id", self.client.session)
