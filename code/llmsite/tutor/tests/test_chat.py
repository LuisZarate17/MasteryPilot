"""Session bootstrap, auto-titling, and graceful degradation.

Two tiers here:

* No mocking at all. tutor.views.chat.model is None on a machine without the
  LLM extras, so every endpoint takes its "Model unavailable" path. Phase 5
  checked that by hand; this pins it.
* Mocked adapter. patch("tutor.views.chat._adapter") is the only seam —
  `get_adapter` is never bound in that namespace, it is re-imported inside
  _adapter() on each call, so patching it there would raise AttributeError.
  Both module globals must be patched too, since every endpoint gates on them.
"""

from unittest import mock
from unittest.mock import patch

from django.urls import reverse
import json

from ..models import Chat as DBChat, Quiz, Session
from ..views.chat import _has_student_message, _is_bootstrap_user_message
from .base import FakeAdapter, MasteryPilotTestCase


class LoadedModel:
    """Context manager installing a fake adapter plus the two globals."""

    def __init__(self, adapter=None):
        self.adapter = adapter or FakeAdapter()
        self._patches = []

    def __enter__(self):
        self._patches = [
            patch("tutor.views.chat.model", object()),
            patch("tutor.views.chat.tokenizer", object()),
            patch("tutor.views.chat._adapter", return_value=self.adapter),
        ]
        for p in self._patches:
            p.start()
        return self.adapter

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


class UnloadedModel:
    """The inverse of LoadedModel: generation is unavailable.

    Pinning the globals to None is not enough on its own. Every view calls
    ensure_llm_initialized() first, which sees model is None and loads one — so
    a bare patch is overwritten before the view reads it. With the stack
    installed that meant these tests downloaded Qwen3-4B and ran real
    inference, which is why the rag-verify job took eight minutes and returned
    200 where 503 was expected.

    So the adapter's init is made to fail instead. That is the real condition
    being described — a machine where loading weights does not work — and it
    exercises ensure_llm_initialized's own except branch, which is what sets
    both globals back to None.
    """

    def __init__(self):
        self._patches = []

    def __enter__(self):
        failing = mock.Mock()
        failing.init_model.side_effect = RuntimeError("no weights on this machine")
        self._patches = [
            patch("tutor.views.chat.model", None),
            patch("tutor.views.chat.tokenizer", None),
            patch("tutor.views.chat._adapter", return_value=failing),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


class BootstrapHelperTests(MasteryPilotTestCase):
    def test_the_generated_bootstrap_turn_is_recognised(self):
        self.assertTrue(
            _is_bootstrap_user_message("Here is your student information:\nName: Ada")
        )

    def test_the_pre_consolidation_shape_is_recognised(self):
        """Sessions written by the old adapters used a bare field list."""
        self.assertTrue(
            _is_bootstrap_user_message("Name: Ada\nSchool: WSU\nGrade: 11\nClasses: Math")
        )

    def test_a_real_question_is_not_a_bootstrap_turn(self):
        for text in ("How do fractions work?", "", None, "Name the largest prime."):
            with self.subTest(text=repr(text)):
                self.assertFalse(_is_bootstrap_user_message(text))

    def test_a_session_with_only_a_bootstrap_turn_has_no_student_message(self):
        student = self.make_student("boot_student")
        session = self.make_session(student)
        self.make_chat(session, "user", "Here is your student information:\nName: Ada")
        self.make_chat(session, "assistant", "Hello!")

        self.assertFalse(_has_student_message(session))

    def test_a_typed_message_counts(self):
        student = self.make_student("boot_student2")
        session = self.make_session(student)
        self.make_chat(session, "user", "Here is your student information:\nName: Ada")
        self.make_chat(session, "user", "How do fractions work?")

        self.assertTrue(_has_student_message(session))


class SessionInitTests(MasteryPilotTestCase):
    """Promotes the throwaway Phase 5 verification script into a real test."""

    def setUp(self):
        self.student = self.make_student(
            "init_student", school="WSU", grade="11", classes="Algebra, CS"
        )
        self.client.force_login(self.student)
        self.session = self.make_session(self.student)

    def url(self):
        return reverse("api_session_init", args=[self.session.id])

    def test_the_bootstrap_persists_the_system_prompt_and_greeting(self):
        with LoadedModel():
            response = self.client.post(self.url())

        self.assertEqual(response.status_code, 200)
        roles = list(
            DBChat.objects.filter(session=self.session)
            .order_by("created_at", "id")
            .values_list("role", flat=True)
        )
        self.assertEqual(roles, ["system", "user", "assistant"])

    def test_the_greeting_is_returned_to_the_caller(self):
        with LoadedModel(FakeAdapter(greeting="Hi Ada!")):
            response = self.client.post(self.url())

        self.assertEqual(json.loads(response.content)["model_text"], "Hi Ada!")

    def test_the_students_real_profile_reaches_the_model(self):
        """Regression: this path used to hard-code school, grade and classes.

        The tutor was told the student attended a school they did not, in a
        grade they were not in, taking classes they were not taking.
        """
        with LoadedModel() as adapter:
            self.client.post(self.url())

        self.assertEqual(
            adapter.start_chat_calls,
            [{"name": "init_student", "school": "WSU", "grade": "11", "classes": "Algebra, CS"}],
        )

    def test_the_session_becomes_active_for_subsequent_chat(self):
        with LoadedModel():
            self.client.post(self.url())

        self.assertEqual(self.client.session["session_id"], str(self.session.id))

    def test_another_users_session_is_not_found(self):
        other = self.make_student("init_other")
        session = self.make_session(other)

        with LoadedModel():
            response = self.client.post(reverse("api_session_init", args=[session.id]))

        self.assertEqual(response.status_code, 404)

    def test_an_unavailable_model_reports_service_unavailable(self):
        with UnloadedModel():
            response = self.client.post(self.url())

        self.assertEqual(response.status_code, 503)
        self.assertFalse(DBChat.objects.filter(session=self.session).exists())


class NewSessionTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student(
            "new_student", school="WSU", grade="12", classes="Calculus"
        )
        self.client.force_login(self.student)

    def post(self, **body):
        return self.client.post(
            reverse("api_new_session"),
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_a_session_is_created_and_bootstrapped(self):
        with LoadedModel():
            response = self.post(title="Fractions")

        self.assertEqual(response.status_code, 200)
        session = Session.objects.get(owner=self.student)
        self.assertEqual(session.title, "Fractions")
        self.assertEqual(DBChat.objects.filter(session=session).count(), 3)

    def test_the_default_title_is_used_when_none_is_given(self):
        with LoadedModel():
            self.post()

        self.assertEqual(Session.objects.get(owner=self.student).title, "New session")

    def test_the_profile_reaches_the_model(self):
        with LoadedModel() as adapter:
            self.post()

        self.assertEqual(adapter.start_chat_calls[0]["school"], "WSU")
        self.assertEqual(adapter.start_chat_calls[0]["classes"], "Calculus")

    def test_a_user_without_a_student_profile_still_gets_a_session(self):
        staff = self.make_user("no_profile")
        self.client.force_login(staff)

        with LoadedModel():
            response = self.post()

        self.assertEqual(response.status_code, 200)

    def test_an_unavailable_model_still_creates_the_session(self):
        """Degrades rather than 500s — the session row is the useful part."""
        with UnloadedModel():
            response = self.post(title="Offline")

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertIn("Model unavailable", payload["model_text"])
        self.assertTrue(Session.objects.filter(owner=self.student).exists())

    def test_a_start_chat_failure_is_reported_not_raised(self):
        adapter = FakeAdapter()
        adapter.start_chat = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))

        with LoadedModel(adapter):
            response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Model error", json.loads(response.content)["model_text"])

    def test_a_malformed_body_is_rejected(self):
        response = self.client.post(
            reverse("api_new_session"), data="not json", content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)


class ChatTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("chat_student")
        self.client.force_login(self.student)
        self.session = self.make_session(self.student)
        self.set_active_session(self.session)

    def send(self, message):
        return self.client.post(
            reverse("api_chat"),
            data=json.dumps({"message": message}),
            content_type="application/json",
        )

    def test_the_exchange_is_persisted(self):
        with LoadedModel(FakeAdapter(reply="Subtract three.")):
            response = self.send("How do I solve x + 3 = 8?")

        self.assertEqual(response.status_code, 200)
        messages = list(
            DBChat.objects.filter(session=self.session)
            .order_by("created_at", "id")
            .values_list("role", "message")
        )
        self.assertEqual(
            messages,
            [("user", "How do I solve x + 3 = 8?"), ("assistant", "Subtract three.")],
        )

    def test_the_step_taught_is_recorded_on_the_session(self):
        with LoadedModel(FakeAdapter(reply="Subtract 7 from both sides. What is 15 / 3?")):
            self.send("How do I solve 3x + 7 = 22?")

        self.session.refresh_from_db()
        self.assertEqual(
            self.session.progress_ledger, ["Subtract 7 from both sides."]
        )

    def test_the_recorded_steps_are_handed_back_on_the_next_turn(self):
        """The point of the ledger: the tutor is told where it is."""
        with LoadedModel(FakeAdapter(reply="Subtract 7 from both sides.")):
            self.send("How do I solve 3x + 7 = 22?")

        adapter = FakeAdapter(reply="Now divide by 3.")
        with LoadedModel(adapter):
            self.send("15")

        self.assertEqual(adapter.ledgers_seen, [["Subtract 7 from both sides."]])

    def test_the_first_turn_of_a_session_carries_an_empty_ledger(self):
        adapter = FakeAdapter(reply="Subtract 7.")
        with LoadedModel(adapter):
            self.send("How do I solve 3x + 7 = 22?")

        self.assertEqual(adapter.ledgers_seen, [[]])

    def test_a_quiz_reply_is_not_recorded_as_a_step(self):
        """A quiz is not a step, and its JSON would be noise in the ledger."""
        quiz = ('{"test": {"q1": {"question": "2+2?", "type": "multiple-choice",'
                ' "answers": ["4", "5"], "correct": "0"}}}')
        with LoadedModel(FakeAdapter(reply=quiz)):
            self.send("Give me a quiz.")

        self.session.refresh_from_db()
        self.assertEqual(self.session.progress_ledger, [])

    def test_a_failed_turn_records_nothing(self):
        with UnloadedModel():
            self.send("How do I solve 3x + 7 = 22?")

        self.session.refresh_from_db()
        self.assertEqual(self.session.progress_ledger, [])

    def test_abandoning_the_problem_clears_the_recorded_steps(self):
        """Otherwise the tutor keeps teaching the problem the student left.

        Measured: with the ledger and without this, abandon-and-switch fell
        from 2 clean runs in 3 to 1 in 5, stalling on the old problem.
        """
        self.session.progress_ledger = ["Subtract 7 from both sides."]
        self.session.save(update_fields=["progress_ledger"])

        adapter = FakeAdapter(reply="Start with the multiplication.")
        with LoadedModel(adapter):
            self.send("Actually forget that, can you help me with 7 + 2 * 3 instead?")

        self.assertEqual(adapter.ledgers_seen, [[]])
        self.session.refresh_from_db()
        self.assertEqual(
            self.session.progress_ledger, ["Start with the multiplication."]
        )

    def test_an_ordinary_turn_keeps_the_recorded_steps(self):
        self.session.progress_ledger = ["Subtract 7 from both sides."]
        self.session.save(update_fields=["progress_ledger"])

        adapter = FakeAdapter(reply="Now divide by 3.")
        with LoadedModel(adapter):
            self.send("15")

        self.assertEqual(adapter.ledgers_seen, [["Subtract 7 from both sides."]])

    def test_an_empty_message_is_rejected(self):
        self.assertEqual(self.send("   ").status_code, 400)

    def test_chatting_without_an_active_session_is_rejected(self):
        s = self.client.session
        s.pop("session_id", None)
        s.save()

        self.assertEqual(self.send("hello").status_code, 400)

    def test_an_unavailable_model_does_not_persist_an_assistant_turn(self):
        with UnloadedModel():
            response = self.send("hello")

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertTrue(payload["error"])
        self.assertIn("Model unavailable", payload["model_text"])
        roles = list(DBChat.objects.filter(session=self.session).values_list("role", flat=True))
        self.assertEqual(roles, ["user"])

    def test_a_quiz_reply_is_captured_as_an_active_quiz(self):
        quiz = '{"test": {"q1": {"question": "2+2?", "answers": ["4"], "correct": "0"}}}'

        with LoadedModel(FakeAdapter(reply=quiz)):
            self.send("Give me a quiz")

        self.assertEqual(Quiz.objects.filter(session=self.session, status="active").count(), 1)

    def test_a_plain_reply_creates_no_quiz(self):
        with LoadedModel(FakeAdapter(reply="Fractions divide a whole.")):
            self.send("Explain fractions")

        self.assertFalse(Quiz.objects.filter(session=self.session).exists())


class AutoTitleTests(MasteryPilotTestCase):
    """Auto-titling had never actually run before Phase 5 fixed the guard."""

    def setUp(self):
        self.student = self.make_student("title_student")
        self.client.force_login(self.student)
        self.session = self.make_session(self.student, title="New session")
        self.set_active_session(self.session)

    def send(self, message):
        return self.client.post(
            reverse("api_chat"),
            data=json.dumps({"message": message}),
            content_type="application/json",
        )

    def bootstrap(self):
        self.make_chat(self.session, "system", "SYSTEM PROMPT")
        self.make_chat(self.session, "user", "Here is your student information:\nName: Ada")
        self.make_chat(self.session, "assistant", "Hello!")

    def test_the_first_typed_message_titles_the_session(self):
        self.bootstrap()

        with LoadedModel(FakeAdapter(title="Fractions")):
            response = self.send("How do fractions work?")

        self.session.refresh_from_db()
        self.assertEqual(self.session.title, "Fractions")
        self.assertEqual(json.loads(response.content)["session_title"], "Fractions")

    def test_the_bootstrap_turn_alone_does_not_block_titling(self):
        """The old guard counted the bootstrap turn as the student's first
        message, so this condition was false on every request and titling
        never ran at all."""
        self.bootstrap()

        with LoadedModel(FakeAdapter(title="Algebra")) as adapter:
            self.send("Teach me algebra")

        self.assertEqual(adapter.derive_title_calls, ["Teach me algebra"])

    def test_a_second_message_does_not_retitle(self):
        self.bootstrap()
        self.make_chat(self.session, "user", "An earlier real question")

        with LoadedModel(FakeAdapter(title="Should Not Apply")):
            self.send("A follow-up")

        self.session.refresh_from_db()
        self.assertEqual(self.session.title, "New session")

    def test_a_custom_title_is_left_alone(self):
        self.session.title = "My own title"
        self.session.save(update_fields=["title"])
        self.bootstrap()

        with LoadedModel(FakeAdapter(title="Derived")):
            self.send("First question")

        self.session.refresh_from_db()
        self.assertEqual(self.session.title, "My own title")

    def test_an_empty_derived_title_leaves_the_default(self):
        self.bootstrap()

        with LoadedModel(FakeAdapter(title="")):
            response = self.send("gibberish asdf")

        self.session.refresh_from_db()
        self.assertEqual(self.session.title, "New session")
        self.assertNotIn("session_title", json.loads(response.content))


class SessionManagementTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("mgmt_student")
        self.client.force_login(self.student)
        self.session = self.make_session(self.student, title="Original")

    def test_a_session_can_be_renamed(self):
        response = self.client.post(
            reverse("api_rename_session", args=[self.session.id]),
            data=json.dumps({"title": "Renamed"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.title, "Renamed")

    def test_a_session_can_be_deleted(self):
        response = self.client.delete(reverse("api_delete_session", args=[self.session.id]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Session.objects.filter(id=self.session.id).exists())

    def test_deleting_a_session_removes_its_messages(self):
        self.make_chat(self.session, "user", "hello")

        self.client.delete(reverse("api_delete_session", args=[self.session.id]))

        self.assertFalse(DBChat.objects.filter(session_id=self.session.id).exists())

    def test_selecting_a_session_makes_it_active(self):
        response = self.client.post(reverse("api_select_session", args=[self.session.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session["session_id"], str(self.session.id))

    def test_reset_clears_the_active_session(self):
        self.set_active_session(self.session)

        self.client.post(reverse("api_reset"))

        self.assertNotIn("session_id", self.client.session)
