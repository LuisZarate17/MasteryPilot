from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import AdminProfile, StudentProfile, TeacherProfile


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
