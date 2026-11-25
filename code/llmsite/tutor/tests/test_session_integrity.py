"""A session must never run without the tutor's rules, and a tab must never
write into a session it was not looking at.

* A session is created only once start_chat has produced its system prompt, and
  api_chat refuses a history that does not begin with one. Without it the model
  answers unconstrained.
* The active session used to live only in the cookie, which is moved by
  whichever tab last selected a session. api_chat and api_grade_quiz now go by
  the session_id in the request body.

FakeAdapter is strict about the system prompt too, so a regression that reaches
the model without it fails loudly rather than quietly.
"""

import json
import uuid

from django.urls import reverse

from ..models import Chat as DBChat, Quiz, QuizAnswer, Session
from .base import FakeAdapter, MasteryPilotTestCase
from .test_chat import LoadedModel, UnloadedModel


class NewSessionIntegrityTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("integrity_new")
        self.client.force_login(self.student)

    def post(self):
        return self.client.post(
            reverse("api_new_session"), data=json.dumps({}), content_type="application/json"
        )

    def assert_cookie_points_at_nothing_real(self):
        session_id = self.client.session.get("session_id")
        if session_id:
            self.assertFalse(Session.objects.filter(id=session_id).exists())

    def test_an_unavailable_model_leaves_no_session_behind(self):
        with UnloadedModel():
            response = self.post()

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["ok"])
        self.assertFalse(Session.objects.filter(owner=self.student).exists())
        self.assert_cookie_points_at_nothing_real()

    def test_a_start_chat_failure_leaves_no_session_and_no_detail(self):
        adapter = FakeAdapter()
        adapter.start_chat = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))

        with LoadedModel(adapter):
            response = self.post()

        self.assertEqual(response.status_code, 503)
        self.assertFalse(Session.objects.filter(owner=self.student).exists())
        self.assertNotIn("boom", response.content.decode())
        self.assert_cookie_points_at_nothing_real()


class ChatNeedsSystemPromptTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("integrity_chat")
        self.client.force_login(self.student)
        self.session = self.make_session(self.student)

    def send(self, message="hello", **extra):
        return self.client.post(
            reverse("api_chat"),
            data=json.dumps({"message": message, **extra}),
            content_type="application/json",
        )

    def test_an_empty_session_is_refused_without_calling_the_model(self):
        with LoadedModel() as adapter:
            response = self.send(session_id=str(self.session.id))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(adapter.send_message_calls, [])
        self.assertFalse(DBChat.objects.filter(session=self.session).exists())

    def test_a_history_not_starting_with_the_system_prompt_is_refused(self):
        self.make_chat(self.session, "user", "Here is your student information ...")
        self.make_chat(self.session, "assistant", "Hello!")

        with LoadedModel() as adapter:
            response = self.send(session_id=str(self.session.id))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(adapter.send_message_calls, [])
        self.assertEqual(DBChat.objects.filter(session=self.session).count(), 2)


class SessionInitIntegrityTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("integrity_init")
        self.client.force_login(self.student)
        self.session = self.make_session(self.student)

    def init(self):
        return self.client.post(reverse("api_session_init", args=[self.session.id]))

    def test_a_session_that_already_has_rows_is_not_initialised_again(self):
        self.bootstrap_session(self.session)

        with LoadedModel() as adapter:
            response = self.init()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(DBChat.objects.filter(session=self.session).count(), 3)
        self.assertEqual(adapter.start_chat_calls, [])

    def test_a_start_chat_failure_does_not_leak_the_exception(self):
        adapter = FakeAdapter()
        adapter.start_chat = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret detail"))

        with LoadedModel(adapter):
            response = self.init()

        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret detail", response.content.decode())
        self.assertFalse(DBChat.objects.filter(session=self.session).exists())


class TwoTabTests(MasteryPilotTestCase):
    """The cookie points at whichever session was selected last; the body decides."""

    def setUp(self):
        self.student = self.make_student("integrity_tabs")
        self.client.force_login(self.student)
        self.a = self.make_session(self.student, title="A")
        self.b = self.make_session(self.student, title="B")
        self.bootstrap_session(self.a)
        self.bootstrap_session(self.b)
        self.set_active_session(self.b)

    def post_chat(self, body):
        return self.client.post(
            reverse("api_chat"), data=json.dumps(body), content_type="application/json"
        )

    def messages(self, session):
        return list(
            DBChat.objects.filter(session=session).values_list("message", flat=True)
        )

    def test_the_message_goes_to_the_session_named_in_the_body(self):
        with LoadedModel():
            response = self.post_chat({"message": "for A", "session_id": str(self.a.id)})

        self.assertEqual(response.status_code, 200)
        self.assertIn("for A", self.messages(self.a))
        self.assertNotIn("for A", self.messages(self.b))
        self.assertEqual(DBChat.objects.filter(session=self.b).count(), 3)

    def test_a_body_without_a_session_id_falls_back_to_the_cookie(self):
        with LoadedModel():
            response = self.post_chat({"message": "for B"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("for B", self.messages(self.b))
        self.assertNotIn("for B", self.messages(self.a))

    def test_another_students_session_id_is_rejected(self):
        other = self.make_student("integrity_other")
        theirs = self.make_session(other)
        self.bootstrap_session(theirs)

        with LoadedModel() as adapter:
            response = self.post_chat({"message": "sneaky", "session_id": str(theirs.id)})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(adapter.send_message_calls, [])
        for session in (self.a, self.b, theirs):
            self.assertNotIn("sneaky", self.messages(session))
            self.assertEqual(DBChat.objects.filter(session=session).count(), 3)

    def test_an_unknown_body_id_does_not_fall_back_to_the_cookie(self):
        with LoadedModel() as adapter:
            response = self.post_chat({"message": "lost", "session_id": str(uuid.uuid4())})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(adapter.send_message_calls, [])
        self.assertNotIn("lost", self.messages(self.b))

    def test_a_body_id_that_is_not_a_uuid_is_a_400_not_a_500(self):
        with LoadedModel() as adapter:
            response = self.post_chat({"message": "junk", "session_id": "not-a-uuid"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(adapter.send_message_calls, [])

    def test_grading_uses_the_session_named_in_the_body(self):
        quiz_a = self.make_quiz(self.a, {"q1": self.mc_question(correct="0")})

        response = self.client.post(
            reverse("api_grade_quiz"),
            data=json.dumps({"answers": "1", "session_id": str(self.a.id)}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        quiz_a.refresh_from_db()
        self.assertEqual(quiz_a.status, "graded")
        self.assertTrue(QuizAnswer.objects.filter(quiz=quiz_a).exists())
        self.assertFalse(Quiz.objects.filter(session=self.b).exists())
        self.assertFalse(QuizAnswer.objects.exclude(quiz=quiz_a).exists())

    def test_grading_another_students_session_id_is_rejected(self):
        other = self.make_student("integrity_other_quiz")
        theirs = self.make_session(other)
        quiz = self.make_quiz(theirs, {"q1": self.mc_question()})

        response = self.client.post(
            reverse("api_grade_quiz"),
            data=json.dumps({"answers": "1", "session_id": str(theirs.id)}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, "active")


class JunkSessionIdUrlTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("integrity_junk")
        self.client.force_login(self.student)

    def test_a_junk_id_on_select_is_a_404(self):
        response = self.client.post("/api/session/not-a-uuid/select/")

        self.assertEqual(response.status_code, 404)

    def test_a_junk_id_on_init_is_a_404(self):
        response = self.client.post("/api/session/not-a-uuid/init/")

        self.assertEqual(response.status_code, 404)
