"""Chat export: payload formats and the teacher-assignment boundary."""

from django.urls import reverse
import json

from .base import MasteryPilotTestCase


class ExportChatTests(MasteryPilotTestCase):
    def setUp(self):
        self.admin_user = self.make_admin("admin_export")
        self.teacher_user = self.make_teacher("teacher_export")
        self.teacher_profile = self.teacher_user.teacherprofile
        self.student_user = self.make_student(
            "student_export", teacher=self.teacher_profile
        )
        self.student_profile = self.student_user.studentprofile

        self.session = self.make_session(self.student_user, title="Algebra practice")
        self.make_chat(self.session, "user", "How do I solve x + 3 = 8?")
        self.make_chat(self.session, "assistant", "Subtract 3 from both sides.")

    def test_admin_can_export_student_chats_as_csv(self):
        self.client.force_login(self.admin_user)
        url = reverse("api_export_chats")
        response = self.client.get(url, {"student_id": self.student_user.id, "format": "csv"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("attachment; filename=", response["Content-Disposition"])

        text = response.content.decode("utf-8")
        self.assertIn("Algebra practice", text)
        self.assertIn("How do I solve x + 3 = 8?", text)
        self.assertIn("Subtract 3 from both sides.", text)

    def test_assigned_teacher_can_export_student_chats_as_json(self):
        self.client.force_login(self.teacher_user)
        url = reverse("api_export_chats")
        response = self.client.get(url, {"student_id": self.student_user.id, "format": "json"})

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload["student"]["username"], "student_export")
        self.assertEqual(len(payload["sessions"]), 1)
        self.assertEqual(payload["sessions"][0]["title"], "Algebra practice")
        self.assertEqual(len(payload["sessions"][0]["messages"]), 2)

    def test_unassigned_teacher_cannot_export_student_chats(self):
        other_teacher_user = self.make_teacher("teacher_other")

        self.client.force_login(other_teacher_user)
        url = reverse("api_export_chats")
        response = self.client.get(url, {"student_id": self.student_user.id, "format": "csv"})

        self.assertEqual(response.status_code, 403)


class ExportScaffoldingTests(MasteryPilotTestCase):
    """Backend scaffolding must not reach the export.

    A live export of 64 sessions was 62% repetitions of the same system prompt,
    because api_export_chats applied no role filter while api_session_messages
    filtered these same two kinds of row for display.
    """

    BOOTSTRAP = (
        "Here is your student information:\nName: Ada\nSchool: WSU\n"
        "Grade: 11\nCurrent Classes: Algebra"
    )

    def setUp(self):
        self.admin_user = self.make_admin("admin_scaffold")
        self.student_user = self.make_student("student_scaffold")
        self.session = self.make_session(self.student_user, title="Fractions")
        self.make_chat(self.session, "system", "THE TUTOR SYSTEM PROMPT")
        self.make_chat(self.session, "user", self.BOOTSTRAP)
        self.make_chat(self.session, "assistant", "Hello, Ada.")
        self.make_chat(self.session, "user", "What is a fraction?")
        self.make_chat(self.session, "assistant", "A fraction is a part of a whole.")
        self.client.force_login(self.admin_user)

    def export(self, fmt):
        return self.client.get(
            reverse("api_export_chats"),
            {"student_id": self.student_user.id, "format": fmt},
        )

    def test_csv_omits_the_system_prompt_and_the_bootstrap_turn(self):
        text = self.export("csv").content.decode("utf-8")

        self.assertNotIn("THE TUTOR SYSTEM PROMPT", text)
        self.assertNotIn("Here is your student information", text)

    def test_csv_keeps_the_real_conversation(self):
        text = self.export("csv").content.decode("utf-8")

        self.assertIn("What is a fraction?", text)
        self.assertIn("A fraction is a part of a whole.", text)
        self.assertIn("Hello, Ada.", text)

    def test_json_carries_only_the_three_real_turns(self):
        payload = json.loads(self.export("json").content.decode("utf-8"))
        messages = payload["sessions"][0]["messages"]

        self.assertEqual(len(messages), 3)
        self.assertEqual([m["role"] for m in messages],
                         ["assistant", "user", "assistant"])
        self.assertNotIn("system", [m["role"] for m in messages])

    def test_a_session_of_pure_scaffolding_exports_no_messages(self):
        empty = self.make_session(self.student_user, title="Never used")
        self.make_chat(empty, "system", "THE TUTOR SYSTEM PROMPT")
        self.make_chat(empty, "user", self.BOOTSTRAP)

        payload = json.loads(self.export("json").content.decode("utf-8"))
        by_title = {s["title"]: s for s in payload["sessions"]}

        self.assertEqual(by_title["Never used"]["messages"], [])
