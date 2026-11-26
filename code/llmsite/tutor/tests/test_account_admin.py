"""Account administration: password rules, superuser protection, user feedback."""

import csv
import os
import tempfile
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from ..models import StudentProfile
from .base import PASSWORD, MasteryPilotTestCase

NEW_PASSWORD = "BrandNewPass456!"
WEAK_PASSWORD = "1"


class AccountAdminTestCase(MasteryPilotTestCase):
    def post(self, url_name, data):
        """POST as the logged-in user and follow the redirect to the dashboard."""
        return self.client.post(reverse(url_name), data, follow=True)

    @staticmethod
    def shown(response):
        """(level_tag, text) for every message rendered on the response."""
        return [(m.level_tag, str(m)) for m in response.context["messages"]]

    def assertShown(self, response, level, fragment):
        shown = self.shown(response)
        self.assertTrue(
            any(tag == level and fragment in text for tag, text in shown),
            f"No {level!r} message containing {fragment!r}; got {shown}",
        )

    def assertPassword(self, user, password):
        user.refresh_from_db()
        self.assertTrue(user.check_password(password))


class PasswordChangeTests(AccountAdminTestCase):
    def setUp(self):
        self.admin = self.make_admin("pw_admin")
        self.student = self.make_student("pw_student")
        self.client.force_login(self.admin)

    def test_a_request_with_only_a_user_id_keeps_the_old_password(self):
        response = self.post("account_password_edit", {"user_id": self.student.id})

        self.assertPassword(self.student, PASSWORD)
        self.assertShown(response, "error", "Enter a new password.")

    def test_a_mismatched_pair_leaves_the_password_unchanged(self):
        response = self.post("account_password_edit", {
            "user_id": self.student.id,
            "password": NEW_PASSWORD,
            "password_confirm": "Different789!",
        })

        self.assertPassword(self.student, PASSWORD)
        self.assertShown(response, "error", "The passwords do not match.")

    def test_a_weak_password_is_rejected(self):
        response = self.post("account_password_edit", {
            "user_id": self.student.id,
            "password": WEAK_PASSWORD,
            "password_confirm": WEAK_PASSWORD,
        })

        self.assertPassword(self.student, PASSWORD)
        self.assertShown(response, "error", "too short")

    def test_a_strong_password_is_applied(self):
        response = self.post("account_password_edit", {
            "user_id": self.student.id,
            "password": NEW_PASSWORD,
            "password_confirm": NEW_PASSWORD,
        })

        self.assertPassword(self.student, NEW_PASSWORD)
        self.assertShown(response, "success", "Password changed for pw_student.")

    def test_an_unknown_user_is_reported(self):
        response = self.post("account_password_edit", {
            "user_id": "999999",
            "password": NEW_PASSWORD,
            "password_confirm": NEW_PASSWORD,
        })

        self.assertShown(response, "error", "That account was not found.")


class AccountCreateTests(AccountAdminTestCase):
    def setUp(self):
        self.admin = self.make_admin("create_admin")
        self.client.force_login(self.admin)

    def create(self, **overrides):
        data = {
            "role": "student",
            "username": "newkid",
            "full_name": "New Kid",
            "email": "newkid@example.com",
            "password": NEW_PASSWORD,
        }
        data.update(overrides)
        return self.post("account_create", data)

    def test_a_weak_password_creates_nothing(self):
        response = self.create(password=WEAK_PASSWORD)

        self.assertFalse(get_user_model().objects.filter(username="newkid").exists())
        self.assertShown(response, "error", "too short")

    def test_a_strong_password_creates_the_account(self):
        response = self.create()

        user = get_user_model().objects.get(username="newkid")
        self.assertTrue(user.check_password(NEW_PASSWORD))
        self.assertTrue(StudentProfile.objects.filter(user=user).exists())
        self.assertShown(response, "success", "Created student account newkid.")

    def test_a_bad_role_creates_nothing(self):
        response = self.create(role="janitor")

        self.assertFalse(get_user_model().objects.filter(username="newkid").exists())
        self.assertShown(response, "error", "role")

    def test_a_taken_username_is_reported(self):
        self.make_student("newkid")

        response = self.create()

        self.assertShown(response, "error", "already taken")

    def test_missing_fields_are_reported(self):
        response = self.create(username="")

        self.assertShown(response, "error", "required")


class StudentEditPasswordTests(AccountAdminTestCase):
    def setUp(self):
        self.admin = self.make_admin("se_admin")
        self.student = self.make_student("se_student")
        self.profile = self.student.studentprofile
        self.client.force_login(self.admin)

    def edit(self, **data):
        data.setdefault("student_id", self.profile.id)
        return self.post("student_edit", data)

    def test_a_weak_password_saves_nothing(self):
        response = self.edit(
            classes="Algebra",
            password=WEAK_PASSWORD,
            password_confirm=WEAK_PASSWORD,
        )

        self.assertPassword(self.student, PASSWORD)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.classes, "")
        self.assertShown(response, "error", "too short")

    def test_a_mismatched_pair_saves_nothing(self):
        teacher = self.make_teacher("se_teacher")

        response = self.edit(
            classes="Algebra",
            teacher_id=teacher.teacherprofile.id,
            password=NEW_PASSWORD,
            password_confirm="Different789!",
        )

        self.assertPassword(self.student, PASSWORD)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.classes, "")
        self.assertIsNone(self.profile.teacher)
        self.assertShown(response, "error", "The passwords do not match.")

    def test_one_field_alone_is_a_mismatch(self):
        response = self.edit(classes="Algebra", password=NEW_PASSWORD)

        self.assertPassword(self.student, PASSWORD)
        self.assertShown(response, "error", "The passwords do not match.")

    def test_a_strong_password_is_applied_with_the_other_edits(self):
        response = self.edit(
            classes="Algebra",
            password=NEW_PASSWORD,
            password_confirm=NEW_PASSWORD,
        )

        self.assertPassword(self.student, NEW_PASSWORD)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.classes, "Algebra")
        self.assertShown(response, "success", "Saved changes for Se_Student.")

    def test_an_edit_without_a_password_shows_success(self):
        response = self.edit(classes="Algebra")

        self.assertPassword(self.student, PASSWORD)
        self.assertShown(response, "success", "Saved changes for")

    def test_a_regular_admin_cannot_set_a_superuser_password(self):
        superuser = self.make_superuser("se_super")
        StudentProfile.objects.create(user=superuser, display_name="Super")

        response = self.edit(
            student_id=superuser.studentprofile.id,
            classes="Algebra",
            password=NEW_PASSWORD,
            password_confirm=NEW_PASSWORD,
        )

        self.assertPassword(superuser, PASSWORD)
        superuser.studentprofile.refresh_from_db()
        self.assertEqual(superuser.studentprofile.classes, "")
        self.assertShown(response, "error", "Only a superuser")


class SuperuserProtectionTests(AccountAdminTestCase):
    def setUp(self):
        self.regular_admin = self.make_admin("regular_admin")
        self.superuser = self.make_superuser("boss")
        self.other_superuser = self.make_superuser("boss_two")
        self.student = self.make_student("protect_student")

    def change_password(self, target):
        return self.post("account_password_edit", {
            "user_id": target.id,
            "password": NEW_PASSWORD,
            "password_confirm": NEW_PASSWORD,
        })

    def delete(self, target):
        return self.post("account_delete", {"user_id": target.id})

    def test_a_regular_admin_cannot_delete_a_superuser(self):
        self.client.force_login(self.regular_admin)

        response = self.delete(self.superuser)

        self.assertTrue(get_user_model().objects.filter(id=self.superuser.id).exists())
        self.assertShown(response, "error", "Only a superuser can delete")

    def test_a_regular_admin_cannot_change_a_superuser_password(self):
        self.client.force_login(self.regular_admin)

        response = self.change_password(self.superuser)

        self.assertPassword(self.superuser, PASSWORD)
        self.assertShown(response, "error", "Only a superuser can change")

    def test_a_superuser_can_delete_another_superuser(self):
        self.client.force_login(self.superuser)

        response = self.delete(self.other_superuser)

        self.assertFalse(
            get_user_model().objects.filter(id=self.other_superuser.id).exists()
        )
        self.assertShown(response, "success", "Deleted account boss_two.")

    def test_a_superuser_can_change_another_superuser_password(self):
        self.client.force_login(self.superuser)

        response = self.change_password(self.other_superuser)

        self.assertPassword(self.other_superuser, NEW_PASSWORD)
        self.assertShown(response, "success", "Password changed for boss_two.")

    def test_a_regular_admin_can_delete_a_student(self):
        self.client.force_login(self.regular_admin)

        response = self.delete(self.student)

        self.assertFalse(get_user_model().objects.filter(id=self.student.id).exists())
        self.assertShown(response, "success", "Deleted account protect_student.")

    def test_a_regular_admin_can_change_a_student_password(self):
        self.client.force_login(self.regular_admin)

        self.change_password(self.student)

        self.assertPassword(self.student, NEW_PASSWORD)

    def test_an_admin_cannot_delete_themselves(self):
        self.client.force_login(self.regular_admin)

        response = self.delete(self.regular_admin)

        self.assertTrue(
            get_user_model().objects.filter(id=self.regular_admin.id).exists()
        )
        self.assertShown(response, "error", "You cannot delete your own account.")

    def test_deleting_an_unknown_account_is_reported(self):
        self.client.force_login(self.regular_admin)

        response = self.post("account_delete", {"user_id": "999999"})

        self.assertShown(response, "error", "That account was not found.")


class ImportStudentsStaffProtectionTests(MasteryPilotTestCase):
    def import_rows(self, *rows):
        """Run import_students on a CSV of (username, password, full_name) rows."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "students.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["username", "password", "full_name"])
                writer.writerows(rows)
            call_command("import_students", path, stdout=StringIO())

    def assert_refused(self, target):
        before_name = (target.first_name, target.last_name)

        with self.assertRaises(CommandError) as ctx:
            self.import_rows(
                (target.username, "ImportedPass789!", "Hijacked Name"),
                ("fresh_student", "ImportedPass789!", "Fresh Student"),
            )

        self.assertIn("staff account", str(ctx.exception))
        target.refresh_from_db()
        self.assertFalse(StudentProfile.objects.filter(user=target).exists())
        self.assertTrue(target.check_password(PASSWORD))
        self.assertEqual((target.first_name, target.last_name), before_name)
        # The whole import is rolled back, not just the offending row.
        self.assertFalse(
            get_user_model().objects.filter(username="fresh_student").exists()
        )

    def test_a_teacher_username_is_refused(self):
        self.assert_refused(self.make_teacher("staff_teacher"))

    def test_an_admin_username_is_refused(self):
        self.assert_refused(self.make_admin("staff_admin"))

    def test_a_superuser_username_is_refused(self):
        self.assert_refused(self.make_superuser("staff_super"))

    def test_an_existing_student_still_imports(self):
        student = self.make_student("roster_student")

        self.import_rows(("roster_student", "ImportedPass789!", "Roster Student"))

        student.refresh_from_db()
        self.assertEqual(student.first_name, "Roster")
        self.assertTrue(student.check_password(PASSWORD))
        self.assertEqual(
            StudentProfile.objects.get(user=student).display_name, "Roster Student"
        )
