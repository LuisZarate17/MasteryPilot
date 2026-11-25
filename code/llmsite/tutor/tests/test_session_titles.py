"""Session titles: escaped at display, bounded on the way in, stored as typed.

A session title is student-controlled text. The teacher/admin transcript viewer
renders it into the page, so an unescaped title runs as script in a staff
member's session. The fix is to escape at display time and to keep the stored
value exactly as typed; these tests pin both halves, plus the length limit that
SQLite does not enforce.
"""

import json
from pathlib import Path

from django.urls import reverse

from ..models import Session
from ..views.chat import MAX_TITLE_LENGTH
from .base import FakeAdapter, MasteryPilotTestCase
from .test_chat import LoadedModel

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


class TitleTemplateEscapingTests(MasteryPilotTestCase):
    """Static checks of the template source.

    The project has no JavaScript test runner, so the only way to guard these
    pages is to read the template and assert on its text. They exist because a
    student-controlled title rendered unescaped on a staff page runs as script
    in the staff member's session (stored XSS); chat_history.html once did
    exactly that.
    """

    def assert_title_is_escaped(self, name):
        source = (TEMPLATES / name).read_text(encoding="utf-8")
        self.assertNotIn("${session.title}", source)
        self.assertIn("${escapeHtml(session.title)}", source)

    def test_the_teacher_transcript_viewer_escapes_titles(self):
        self.assert_title_is_escaped("chat_history.html")

    def test_the_student_chat_page_escapes_titles(self):
        self.assert_title_is_escaped("chat.html")


class RenameTitleTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("rename_student")
        self.client.force_login(self.student)
        self.session = self.make_session(self.student, title="Original")

    def rename(self, title):
        return self.client.post(
            reverse("api_rename_session", args=[self.session.id]),
            data=json.dumps({"title": title}),
            content_type="application/json",
        )

    def test_the_limit_matches_the_model_field(self):
        self.assertEqual(MAX_TITLE_LENGTH, 200)

    def test_a_title_at_the_limit_is_accepted(self):
        title = "a" * MAX_TITLE_LENGTH

        response = self.rename(title)

        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.title, title)

    def test_a_title_over_the_limit_is_rejected_and_nothing_is_saved(self):
        response = self.rename("a" * (MAX_TITLE_LENGTH + 1))

        self.assertEqual(response.status_code, 400)
        self.session.refresh_from_db()
        self.assertEqual(self.session.title, "Original")

    def test_a_title_is_stored_exactly_as_typed(self):
        """Escaping happens at display, not on the way in."""
        title = '<b>hi</b> & "you"'

        response = self.rename(title)

        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.title, title)


class NewSessionTitleTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("newtitle_student")
        self.client.force_login(self.student)

    def post(self, title):
        return self.client.post(
            reverse("api_new_session"),
            data=json.dumps({"title": title}),
            content_type="application/json",
        )

    def test_a_title_over_the_limit_is_rejected_and_no_session_is_created(self):
        title = "a" * (MAX_TITLE_LENGTH + 1)

        with LoadedModel():
            response = self.post(title)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Session.objects.filter(owner=self.student).exists())

    def test_a_title_at_the_limit_is_accepted(self):
        title = "a" * MAX_TITLE_LENGTH

        with LoadedModel():
            response = self.post(title)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Session.objects.get(owner=self.student).title, title)


class DerivedTitleTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("derived_student")
        self.client.force_login(self.student)
        self.session = self.make_session(self.student, title="New session")
        self.set_active_session(self.session)
        self.make_chat(self.session, "system", "SYSTEM PROMPT")
        self.make_chat(self.session, "user", "Here is your student information:\nName: Ada")
        self.make_chat(self.session, "assistant", "Hello!")

    def send(self, message):
        return self.client.post(
            reverse("api_chat"),
            data=json.dumps({"message": message}),
            content_type="application/json",
        )

    def test_an_overlong_derived_title_is_truncated_not_rejected(self):
        with LoadedModel(FakeAdapter(title="x" * (MAX_TITLE_LENGTH + 50))):
            response = self.send("How do fractions work?")

        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.title, "x" * MAX_TITLE_LENGTH)
