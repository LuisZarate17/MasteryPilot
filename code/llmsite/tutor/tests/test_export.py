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
