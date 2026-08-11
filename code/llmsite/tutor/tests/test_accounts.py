"""Signup, admin account creation, and student record edits."""

from django.contrib.auth import get_user_model
from django.urls import reverse

from ..models import StudentProfile, TeacherProfile
from .base import PASSWORD, MasteryPilotTestCase


class SignupNameTests(MasteryPilotTestCase):
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


class AccountCreateNameTests(MasteryPilotTestCase):
    def test_admin_create_student_sets_display_name_and_user_name(self):
        User = get_user_model()
        admin_user = self.make_admin("admin01")
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
        admin_user = self.make_admin("admin02")
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


class StudentEditTests(MasteryPilotTestCase):
    def setUp(self):
        self.admin = self.make_admin("edit_admin")
        self.teacher = self.make_teacher("edit_teacher")
        self.student = self.make_student("edit_student")
        self.profile = self.student.studentprofile
        self.client.force_login(self.admin)

    def post(self, **data):
        data.setdefault("student_id", self.profile.id)
        return self.client.post(reverse("student_edit"), data)

    def test_editing_classes_without_a_password_leaves_login_working(self):
        """Regression: `pw == pwc` was True for None == None.

        The form posts no password fields when an admin is only reassigning a
        teacher or editing classes, so this called set_password(None) and left
        the student unable to log in at all.
        """
        self.post(classes="Algebra, Geometry")

        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(PASSWORD))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.classes, "Algebra, Geometry")

    def test_blank_password_fields_do_not_reset_the_password(self):
        self.post(classes="Algebra", password="", password_confirm="")

        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(PASSWORD))

    def test_a_matching_password_pair_is_applied(self):
        self.post(password="BrandNewPass456!", password_confirm="BrandNewPass456!")

        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password("BrandNewPass456!"))

    def test_a_mismatched_password_pair_is_ignored(self):
        self.post(password="BrandNewPass456!", password_confirm="Different789!")

        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(PASSWORD))

    def test_a_teacher_can_be_assigned(self):
        self.post(classes="Algebra", teacher_id=self.teacher.teacherprofile.id)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.teacher, self.teacher.teacherprofile)

    def test_an_unknown_student_id_redirects_without_raising(self):
        response = self.client.post(reverse("student_edit"), {"student_id": "999999"})

        self.assertEqual(response.status_code, 302)

    def test_a_non_numeric_student_id_redirects_without_raising(self):
        response = self.client.post(reverse("student_edit"), {"student_id": "abc"})

        self.assertEqual(response.status_code, 302)
