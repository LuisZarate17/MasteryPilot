from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
import json

from .models import AdminProfile, StudentProfile, TeacherProfile, Session, Chat


class SignupNameTests(TestCase):
    def test_signup_persists_full_name_to_user_and_profile(self):
        response = self.client.post(reverse("signup"), {
            "username": "student01",
            "full_name": "Ada Lovelace",
            "email": "ada@example.com",
            "password1": "ComplexPass123!",
            "password2": "ComplexPass123!",
            "school": "WSU",
            "grade": "Senior",
            "classes": "Math, CS",
        })

        self.assertEqual(response.status_code, 302)

        User = get_user_model()
        user = User.objects.get(username="student01")
        profile = StudentProfile.objects.get(user=user)

        self.assertEqual(user.first_name, "Ada")
        self.assertEqual(user.last_name, "Lovelace")
        self.assertEqual(profile.display_name, "Ada Lovelace")


class AccountCreateNameTests(TestCase):
    def test_admin_create_student_sets_display_name_and_user_name(self):
        User = get_user_model()
        admin_user = User.objects.create_user(
            username="admin01",
            password="ComplexPass123!",
            email="admin@example.com",
        )
        AdminProfile.objects.create(user=admin_user, display_name="Admin User")
        self.client.force_login(admin_user)

        response = self.client.post(reverse("account_create"), {
            "role": "student",
            "username": "student02",
            "full_name": "Grace Hopper",
            "email": "grace@example.com",
            "password": "ComplexPass123!",
            "grade": "Junior",
            "classes": "OS, Compilers",
        })

        self.assertEqual(response.status_code, 302)

        user = User.objects.get(username="student02")
        profile = StudentProfile.objects.get(user=user)

        self.assertEqual(user.first_name, "Grace")
        self.assertEqual(user.last_name, "Hopper")
        self.assertEqual(profile.display_name, "Grace Hopper")

    def test_admin_create_teacher_sets_display_name_and_user_name(self):
        User = get_user_model()
        admin_user = User.objects.create_user(
            username="admin02",
            password="ComplexPass123!",
            email="admin2@example.com",
        )
        AdminProfile.objects.create(user=admin_user, display_name="Admin User")
        self.client.force_login(admin_user)

        response = self.client.post(reverse("account_create"), {
            "role": "teacher",
            "username": "teacher01",
            "full_name": "Alan Turing",
            "email": "alan@example.com",
            "password": "ComplexPass123!",
        })

        self.assertEqual(response.status_code, 302)

        user = User.objects.get(username="teacher01")
        profile = TeacherProfile.objects.get(user=user)

        self.assertEqual(user.first_name, "Alan")
        self.assertEqual(user.last_name, "Turing")
        self.assertEqual(profile.display_name, "Alan Turing")


class ExportChatTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin_user = User.objects.create_user(
            username="admin_export",
            password="ComplexPass123!",
            email="admin_export@example.com",
        )
        AdminProfile.objects.create(user=self.admin_user, display_name="Admin Export")

        self.teacher_user = User.objects.create_user(
            username="teacher_export",
            password="ComplexPass123!",
            email="teacher_export@example.com",
        )
        self.teacher_profile = TeacherProfile.objects.create(
            user=self.teacher_user,
            display_name="Teacher Export",
        )

        self.student_user = User.objects.create_user(
            username="student_export",
            password="ComplexPass123!",
            email="student_export@example.com",
        )
        self.student_profile = StudentProfile.objects.create(
            user=self.student_user,
            display_name="Student Export",
            teacher=self.teacher_profile,
        )

        self.session = Session.objects.create(owner=self.student_user, title="Algebra practice")
        Chat.objects.create(session=self.session, role="user", message="How do I solve x + 3 = 8?")
        Chat.objects.create(session=self.session, role="assistant", message="Subtract 3 from both sides.")

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
        User = get_user_model()
        other_teacher_user = User.objects.create_user(
            username="teacher_other",
            password="ComplexPass123!",
            email="teacher_other@example.com",
        )
        TeacherProfile.objects.create(user=other_teacher_user, display_name="Teacher Other")

        self.client.force_login(other_teacher_user)
        url = reverse("api_export_chats")
        response = self.client.get(url, {"student_id": self.student_user.id, "format": "csv"})

        self.assertEqual(response.status_code, 403)
