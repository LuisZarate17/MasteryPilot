"""What a teacher sees of a student's transcript, and what an export can do to them.

Three defects pinned here:

* The bootstrap turn was recognised by its text, so a student could hide any
  message from their teacher and from exports by opening it with the same words.
  It is now recognised by position: a user row before the first assistant row.
* The CSV export wrote student-controlled text straight into cells, so a
  message starting with "=" ran as a formula in the teacher's spreadsheet.
* A second teacher uploading a file with an existing name overwrote the first
  teacher's document, and every upload failure was a silent redirect.
"""

import csv
import io
import json
import os
import shutil
import tempfile
from unittest import mock

from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

import rag

from ..views.chat import _has_student_message
from .base import MasteryPilotTestCase

BOOTSTRAP = (
    "Here is your student information:\nName: Ada\nSchool: WSU\n"
    "Grade: 11\nCurrent Classes: Algebra"
)
LOOKALIKES = [
    "Here is your student information, and I think I failed the test.",
    "Name: x School: y Grade: z",
]


class TranscriptVisibilityBase(MasteryPilotTestCase):
    def setUp(self):
        self.teacher = self.make_teacher("tv_teacher")
        self.student = self.make_student("tv_student", teacher=self.teacher.teacherprofile)
        self.session = self.make_session(self.student, title="Fractions")
        self.make_chat(self.session, "system", "THE TUTOR SYSTEM PROMPT")
        self.make_chat(self.session, "user", BOOTSTRAP)
        self.make_chat(self.session, "assistant", "Hello, Ada.")

    def teacher_messages(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("api_session_messages", args=[self.session.id]))
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)["messages"]

    def export(self, fmt):
        self.client.force_login(self.teacher)
        response = self.client.get(
            reverse("api_export_chats"), {"student_id": self.student.id, "format": fmt}
        )
        self.assertEqual(response.status_code, 200)
        return response.content.decode("utf-8")

    def csv_rows(self):
        return list(csv.DictReader(io.StringIO(self.export("csv"))))

    def json_texts(self):
        payload = json.loads(self.export("json"))
        return [m["text"] for m in payload["sessions"][0]["messages"]]


class StudentMessagesAreNotHiddenTests(TranscriptVisibilityBase):
    def test_a_message_that_opens_like_the_bootstrap_stays_visible(self):
        for text in LOOKALIKES:
            with self.subTest(text=text):
                self.make_chat(self.session, "user", text)
                self.make_chat(self.session, "assistant", "Noted.")

                self.assertIn(text, [m["text"] for m in self.teacher_messages()])
                self.assertIn(text, [r["message"] for r in self.csv_rows()])
                self.assertIn(text, self.json_texts())

    def test_the_real_bootstrap_and_system_rows_stay_hidden_from_the_teacher(self):
        self.make_chat(self.session, "user", LOOKALIKES[0])

        shown = json.dumps(self.teacher_messages())

        self.assertNotIn("THE TUTOR SYSTEM PROMPT", shown)
        self.assertNotIn("Current Classes: Algebra", shown)

    def test_the_real_bootstrap_and_system_rows_stay_hidden_from_exports(self):
        self.make_chat(self.session, "user", LOOKALIKES[0])

        for name, text in (("csv", self.export("csv")), ("json", self.export("json"))):
            with self.subTest(format=name):
                self.assertNotIn("THE TUTOR SYSTEM PROMPT", text)
                self.assertNotIn("Current Classes: Algebra", text)

    def test_the_real_bootstrap_and_system_rows_stay_hidden_from_the_student(self):
        self.make_chat(self.session, "user", "What is a fraction?")
        self.client.force_login(self.student)

        response = self.client.get(reverse("api_session_messages", args=[self.session.id]))
        messages = json.loads(response.content)["messages"]

        self.assertEqual([m["text"] for m in messages], ["Hello, Ada.", "What is a fraction?"])

    def test_a_legacy_bootstrap_turn_is_hidden_by_position_too(self):
        session = self.make_session(self.student, title="Old")
        self.make_chat(session, "user", "Name: Ada\nSchool: WSU\nGrade: 11\nClasses: Math")
        self.make_chat(session, "assistant", "Hello!")
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("api_session_messages", args=[session.id]))

        self.assertEqual([m["text"] for m in json.loads(response.content)["messages"]], ["Hello!"])


class OnlyTheFirstRowCanBeTheBootstrapTests(MasteryPilotTestCase):
    """Hiding too little is the safe failure for oversight."""

    def setUp(self):
        self.teacher = self.make_teacher("fr_teacher")
        self.student = self.make_student("fr_student", teacher=self.teacher.teacherprofile)
        self.client.force_login(self.teacher)

    def shown(self, session):
        response = self.client.get(reverse("api_session_messages", args=[session.id]))
        return [m["text"] for m in json.loads(response.content)["messages"]]

    def test_with_no_greeting_the_first_student_message_is_still_shown(self):
        # start_chat persists a greeting only when it has text, so a session
        # can go straight from the bootstrap turn to the student's message.
        session = self.make_session(self.student)
        self.make_chat(session, "system", "THE TUTOR SYSTEM PROMPT")
        self.make_chat(session, "user", BOOTSTRAP)
        self.make_chat(session, "user", "I need help, someone is bothering me")
        self.make_chat(session, "assistant", "I'm sorry to hear that.")

        self.assertEqual(
            self.shown(session),
            ["I need help, someone is bothering me", "I'm sorry to hear that."],
        )

    def test_a_session_without_a_system_row_shows_an_ordinary_first_message(self):
        session = self.make_session(self.student)
        self.make_chat(session, "user", "What is a fraction?")
        self.make_chat(session, "assistant", "A part of a whole.")

        self.assertEqual(self.shown(session), ["What is a fraction?", "A part of a whole."])

    def test_a_bootstrap_shaped_message_after_the_first_row_is_shown(self):
        session = self.make_session(self.student)
        self.make_chat(session, "user", "Name: Ada\nSchool: WSU\nGrade: 11\nClasses: Math")
        self.make_chat(session, "assistant", "Hello!")
        self.make_chat(session, "user", "Name: x\nSchool: y\nGrade: z\nsecret")

        self.assertEqual(self.shown(session), ["Hello!", "Name: x\nSchool: y\nGrade: z\nsecret"])


class HasStudentMessageTests(TranscriptVisibilityBase):
    def test_false_with_only_scaffolding_and_the_greeting(self):
        self.assertFalse(_has_student_message(self.session))

    def test_true_once_a_student_row_follows_the_greeting(self):
        self.make_chat(self.session, "user", "What is a fraction?")

        self.assertTrue(_has_student_message(self.session))

    def test_true_even_if_that_row_opens_with_the_bootstrap_phrase(self):
        for text in LOOKALIKES:
            with self.subTest(text=text):
                session = self.make_session(self.student)
                self.make_chat(session, "system", "S")
                self.make_chat(session, "user", BOOTSTRAP)
                self.make_chat(session, "assistant", "Hello.")
                self.make_chat(session, "user", text)

                self.assertTrue(_has_student_message(session))


class CsvFormulaInjectionTests(TranscriptVisibilityBase):
    def message_cells(self):
        return [r["message"] for r in self.csv_rows() if r["role"] == "user"]

    def test_a_leading_formula_character_is_neutralised(self):
        cases = ["=HYPERLINK(\"http://evil\",\"x\")", "+1+1", "-2+3", "@SUM(A1)", "\tcmd", "\rcmd"]
        for text in cases:
            with self.subTest(text=text):
                self.make_chat(self.session, "user", text)

                self.assertIn("'" + text, self.message_cells())

    def test_an_ordinary_message_is_unchanged(self):
        self.make_chat(self.session, "user", "What is 3 - 1?")

        self.assertIn("What is 3 - 1?", self.message_cells())

    def test_a_session_title_is_neutralised(self):
        self.session.title = "=1+1"
        self.session.save()

        self.assertEqual({r["session_title"] for r in self.csv_rows()}, {"'=1+1"})

    def test_the_username_and_display_name_are_neutralised(self):
        self.student.studentprofile.display_name = "=cmd|' /C calc'!A0"
        self.student.studentprofile.save()

        self.assertEqual(
            {r["student_name"] for r in self.csv_rows()}, {"'=cmd|' /C calc'!A0"}
        )

    def test_json_keeps_the_raw_text(self):
        self.make_chat(self.session, "user", "=HYPERLINK(\"http://evil\")")

        self.assertIn("=HYPERLINK(\"http://evil\")", self.json_texts())


class CurriculumOverwriteTests(MasteryPilotTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="curriculum-overwrite-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        rag.default_index.invalidate = lambda: None
        self.addCleanup(rag.default_index.__dict__.pop, "invalidate", None)
        # An upload rebuilds the index; there is no embedder in the test run.
        patcher = mock.patch.object(rag, "ensure_curriculum_loaded")
        patcher.start()
        self.addCleanup(patcher.stop)

        self.teacher_a = self.make_teacher("tv_teacher_a")
        self.teacher_b = self.make_teacher("tv_teacher_b")
        self.admin = self.make_admin("tv_admin")

    def upload(self, user, name, content, content_type="text/plain", **extra):
        self.client.force_login(user)
        with override_settings(CURRICULUM_ROOT=self.tmp):
            return self.client.post(
                reverse("upload_curriculum"),
                {"title": "t", "file": SimpleUploadedFile(name, content, content_type=content_type)},
                **extra,
            )

    def seed(self, name, content):
        """A document teacher A already uploaded, without queuing a message."""
        with open(os.path.join(self.tmp, name), "wb") as handle:
            handle.write(content)

    def stored(self, name):
        with open(os.path.join(self.tmp, name), "rb") as handle:
            return handle.read()

    def texts(self, response):
        return [(m.level_tag, str(m)) for m in get_messages(response.wsgi_request)]

    def test_a_teacher_cannot_overwrite_another_teachers_file(self):
        self.seed("x.txt", b"A's bytes")

        response = self.upload(self.teacher_b, "x.txt", b"B's bytes")

        self.assertEqual(self.stored("x.txt"), b"A's bytes")
        self.assertEqual(response.status_code, 302)
        levels = [level for level, _ in self.texts(response)]
        self.assertEqual(levels, ["error"])
        self.assertIn("already exists", self.texts(response)[0][1])

    def test_an_admin_replaces_an_existing_file(self):
        self.seed("x.txt", b"A's bytes")

        response = self.upload(self.admin, "x.txt", b"admin's bytes")

        self.assertEqual(self.stored("x.txt"), b"admin's bytes")
        self.assertEqual([level for level, _ in self.texts(response)], ["success"])

    def test_a_successful_upload_adds_a_success_message(self):
        response = self.upload(self.teacher_a, "fresh.txt", b"hello")

        self.assertEqual(self.stored("fresh.txt"), b"hello")
        self.assertEqual([level for level, _ in self.texts(response)], ["success"])

    def test_a_disallowed_extension_adds_an_error_message(self):
        response = self.upload(
            self.teacher_a, "run.exe", b"MZ", content_type="application/octet-stream"
        )

        self.assertFalse(os.path.exists(os.path.join(self.tmp, "run.exe")))
        self.assertEqual([level for level, _ in self.texts(response)], ["error"])

    def test_a_missing_file_adds_an_error_message(self):
        self.client.force_login(self.teacher_a)
        with override_settings(CURRICULUM_ROOT=self.tmp):
            response = self.client.post(reverse("upload_curriculum"), {"title": "t"})

        self.assertEqual([level for level, _ in self.texts(response)], ["error"])

    def test_the_message_is_rendered_on_the_next_page(self):
        self.seed("x.txt", b"A's bytes")

        response = self.upload(self.teacher_b, "x.txt", b"B's bytes", follow=True)

        self.assertContains(response, "A file named x.txt already exists")
        self.assertContains(response, 'role="status"')
