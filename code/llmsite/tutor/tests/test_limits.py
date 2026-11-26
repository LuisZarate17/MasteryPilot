"""Abuse limits: request size, message length, session rate, sign-up, demo accounts.

Each of these exists to stop one person from costing everyone else something
(model time, memory, an open registration form), so most tests assert two
things: the request is refused, and the expensive thing behind it never ran.
"""

import json
import os
import shutil
import tempfile
from datetime import timedelta
from io import StringIO
from unittest import skipIf

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

import rag

from ..models import AdminProfile, Chat as DBChat, Session, StudentProfile, TeacherProfile
from ..views.chat import MAX_MESSAGE_CHARS, MAX_NEW_SESSIONS_PER_MINUTE
from .base import PASSWORD, MasteryPilotTestCase
from .test_chat import LoadedModel

User = get_user_model()


class MessageLengthTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("limits_student")
        self.session = self.make_session(self.student)
        self.bootstrap_session(self.session)
        self.client.force_login(self.student)

    def post(self, message):
        return self.client.post(
            reverse("api_chat"),
            data=json.dumps({"message": message, "session_id": str(self.session.id)}),
            content_type="application/json",
        )

    def test_a_message_over_the_limit_is_refused_before_anything_happens(self):
        stored = DBChat.objects.filter(session=self.session).count()

        with LoadedModel() as adapter:
            response = self.post("x" * (MAX_MESSAGE_CHARS + 1))

        self.assertEqual(response.status_code, 400)
        self.assertIn("too long", response.content.decode())
        self.assertEqual(DBChat.objects.filter(session=self.session).count(), stored)
        self.assertEqual(adapter.send_message_calls, [])
        self.assertEqual(adapter.derive_title_calls, [])

    def test_a_message_at_the_limit_is_accepted(self):
        with LoadedModel() as adapter:
            response = self.post("x" * MAX_MESSAGE_CHARS)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(adapter.send_message_calls), 1)

    def test_the_input_box_carries_the_same_limit(self):
        with LoadedModel():
            html = self.client.get(reverse("chat")).content.decode()

        self.assertIn(f'maxlength="{MAX_MESSAGE_CHARS}"', html)


class RequestSizeTests(MasteryPilotTestCase):
    def test_an_oversized_json_body_is_a_client_error_not_a_crash(self):
        student = self.make_student("big_body")
        session = self.make_session(student)
        self.bootstrap_session(session)
        self.client.force_login(student)
        stored = DBChat.objects.filter(session=session).count()

        with LoadedModel() as adapter:
            response = self.client.post(
                reverse("api_chat"),
                data=json.dumps({"message": "x" * (1024 * 1024 + 1), "session_id": str(session.id)}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(adapter.send_message_calls, [])
        self.assertEqual(DBChat.objects.filter(session=session).count(), stored)

    def test_an_oversized_body_to_new_session_is_a_client_error(self):
        student = self.make_student("big_new_session")
        self.client.force_login(student)

        with LoadedModel() as adapter:
            response = self.client.post(
                reverse("api_new_session"),
                data=json.dumps({"title": "x" * (1024 * 1024 + 1)}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"], "Request is too large.")
        self.assertEqual(adapter.start_chat_calls, [])
        self.assertFalse(Session.objects.filter(owner=student).exists())


class UploadStillWorksTests(MasteryPilotTestCase):
    """The 1 MB body cap must not apply to file parts of a multipart upload."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="limits-curriculum-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

        rag.default_index.invalidate = lambda: None
        self.addCleanup(rag.default_index.__dict__.pop, "invalidate", None)

        self.client.force_login(self.make_admin("limits_admin"))

    def test_a_two_megabyte_document_is_accepted(self):
        content = b"Fractions divide a whole into equal parts.\n" * 50000
        self.assertGreater(len(content), 2 * 1024 * 1024)
        upload = SimpleUploadedFile("big.txt", content, content_type="text/plain")

        # A dict with a file is encoded as multipart by the test client, which
        # is the path a browser takes.
        with override_settings(CURRICULUM_ROOT=self.tmp):
            response = self.client.post(
                reverse("upload_curriculum"), {"title": "Big", "file": upload}
            )

        self.assertEqual(response.status_code, 302)
        saved = os.path.join(self.tmp, "big.txt")
        self.assertTrue(os.path.exists(saved))
        self.assertEqual(os.path.getsize(saved), len(content))


class NewSessionRateTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("rate_student")
        self.client.force_login(self.student)

    def post(self):
        return self.client.post(
            reverse("api_new_session"), data=json.dumps({}), content_type="application/json"
        )

    def make_recent_sessions(self, count):
        for _ in range(count):
            self.make_session(self.student)

    def test_the_call_after_the_limit_is_refused_without_generating(self):
        self.make_recent_sessions(MAX_NEW_SESSIONS_PER_MINUTE)

        with LoadedModel() as adapter:
            response = self.post()

        self.assertEqual(response.status_code, 429)
        self.assertFalse(response.json()["ok"])
        self.assertIn("too quickly", response.json()["error"])
        self.assertEqual(adapter.start_chat_calls, [])
        self.assertEqual(
            Session.objects.filter(owner=self.student).count(), MAX_NEW_SESSIONS_PER_MINUTE
        )

    def test_the_last_call_under_the_limit_succeeds(self):
        self.make_recent_sessions(MAX_NEW_SESSIONS_PER_MINUTE - 1)

        with LoadedModel() as adapter:
            response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(adapter.start_chat_calls), 1)

    def test_sessions_older_than_a_minute_do_not_count(self):
        self.make_recent_sessions(MAX_NEW_SESSIONS_PER_MINUTE)
        Session.objects.filter(owner=self.student).update(
            created_at=timezone.now() - timedelta(minutes=2)
        )

        with LoadedModel() as adapter:
            response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(adapter.start_chat_calls), 1)

    def test_another_students_sessions_do_not_count(self):
        other = self.make_student("rate_other")
        for _ in range(MAX_NEW_SESSIONS_PER_MINUTE):
            self.make_session(other)

        with LoadedModel():
            response = self.post()

        self.assertEqual(response.status_code, 200)


SIGNUP_FORM = {
    "username": "newcomer",
    "full_name": "New Comer",
    "email": "newcomer@example.com",
    "password1": PASSWORD,
    "password2": PASSWORD,
}


@skipIf(
    os.getenv("DJANGO_ALLOW_SIGNUP") is not None,
    "DJANGO_ALLOW_SIGNUP is set in this environment, so the default is not in effect",
)
class SignupDefaultTests(MasteryPilotTestCase):
    def test_signup_is_off_by_default(self):
        from django.conf import settings

        self.assertFalse(settings.ALLOW_SIGNUP)


# Pinned off so a developer with DJANGO_ALLOW_SIGNUP=1 in their .env still runs
# these; the methods that need it on override it again.
@override_settings(ALLOW_SIGNUP=False)
class SignupSwitchTests(MasteryPilotTestCase):
    def test_get_is_404_when_off(self):
        self.assertEqual(self.client.get(reverse("signup")).status_code, 404)

    def test_post_is_404_and_creates_no_user_when_off(self):
        response = self.client.post(reverse("signup"), SIGNUP_FORM)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(User.objects.filter(username="newcomer").exists())

    def test_no_signup_link_when_off(self):
        for url in (reverse("login"), reverse("login") + "?next=/"):
            html = self.client.get(url).content.decode()
            self.assertNotIn("/signup/", html)

    @override_settings(ALLOW_SIGNUP=True)
    def test_signup_works_when_on(self):
        self.assertEqual(self.client.get(reverse("signup")).status_code, 200)

        response = self.client.post(reverse("signup"), SIGNUP_FORM)

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="newcomer")
        self.assertTrue(StudentProfile.objects.filter(user=user).exists())

    @override_settings(ALLOW_SIGNUP=True)
    def test_signup_links_show_when_on(self):
        html = self.client.get(reverse("login")).content.decode()

        # Once in the nav bar and once under the sign-in form.
        self.assertEqual(html.count('href="/signup/"'), 2)


@override_settings(DEBUG=True)
class DemoAccountsTests(MasteryPilotTestCase):
    STRONG = "Correct-Horse-Battery-9"

    def run_command(self, *args, **kwargs):
        out = StringIO()
        call_command("create_demo_accounts", *args, stdout=out, **kwargs)
        return out.getvalue()

    def demo_users(self):
        return User.objects.filter(username__startswith="demo_")

    def test_refuses_when_debug_is_off(self):
        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError) as ctx:
                self.run_command("--password", self.STRONG)

        self.assertIn("local testing", str(ctx.exception))
        self.assertFalse(self.demo_users().exists())

    def test_creates_the_five_accounts_with_their_profiles(self):
        self.run_command("--password", self.STRONG)

        self.assertEqual(self.demo_users().count(), 5)
        self.assertTrue(AdminProfile.objects.filter(user__username="demo_admin").exists())
        teacher = TeacherProfile.objects.get(user__username="demo_teacher")

        one = StudentProfile.objects.get(user__username="demo_student")
        self.assertEqual((one.teacher, one.grade, one.classes), (teacher, "9", "Algebra I; Biology"))
        two = StudentProfile.objects.get(user__username="demo_student2")
        self.assertEqual((two.teacher, two.grade, two.classes), (teacher, "10", "Geometry; Chemistry"))
        three = StudentProfile.objects.get(user__username="demo_student3")
        self.assertIsNone(three.teacher)

        for user in self.demo_users():
            self.assertFalse(user.is_superuser)
            self.assertFalse(user.is_staff)
            self.assertTrue(user.check_password(self.STRONG))
            self.assertTrue(user.get_full_name())

    def test_output_has_a_table_of_username_role_and_teacher(self):
        output = self.run_command("--password", self.STRONG)

        self.assertIn("demo_student2", output)
        line = next(l for l in output.splitlines() if l.startswith("demo_student2"))
        self.assertIn("student", line)
        self.assertIn("demo_teacher", line)

    def test_a_second_run_changes_nothing(self):
        self.run_command("--password", self.STRONG)
        before = {u.username: u.password for u in self.demo_users()}
        profiles = (
            AdminProfile.objects.count(),
            TeacherProfile.objects.count(),
            StudentProfile.objects.count(),
        )

        output = self.run_command("--password", "Another-Strong-Pass-7")

        self.assertEqual({u.username: u.password for u in self.demo_users()}, before)
        self.assertEqual(
            (AdminProfile.objects.count(), TeacherProfile.objects.count(), StudentProfile.objects.count()),
            profiles,
        )
        self.assertEqual(output.count("exists"), 5)
        self.assertNotIn("created", output)

    def test_reset_passwords_changes_the_password(self):
        self.run_command("--password", self.STRONG)
        new = "Another-Strong-Pass-7"

        self.run_command("--password", new, "--reset-passwords")

        for user in self.demo_users():
            self.assertTrue(user.check_password(new))
            self.assertFalse(user.check_password(self.STRONG))

    def test_a_username_with_a_different_role_stops_everything(self):
        self.make_teacher("demo_student")

        with self.assertRaises(CommandError):
            self.run_command("--password", self.STRONG)

        self.assertEqual(self.demo_users().count(), 1)
        self.assertFalse(User.objects.filter(username="demo_admin").exists())
        self.assertFalse(StudentProfile.objects.filter(user__username="demo_student").exists())

    def test_a_superuser_with_a_demo_name_stops_everything(self):
        self.make_superuser("demo_admin")

        with self.assertRaises(CommandError):
            self.run_command("--password", self.STRONG)

        self.assertEqual(self.demo_users().count(), 1)
        self.assertFalse(User.objects.filter(username="demo_teacher").exists())

    def test_a_superuser_with_the_matching_profile_keeps_its_password(self):
        # The role check alone would pass here (demo_admin is an admin), so
        # only the superuser check stops --reset-passwords from changing the
        # owner's password.
        owner = self.make_superuser("demo_admin")
        AdminProfile.objects.create(user=owner, display_name="Owner")
        old_hash = User.objects.get(pk=owner.pk).password

        with self.assertRaises(CommandError):
            self.run_command("--password", self.STRONG, "--reset-passwords")

        self.assertEqual(User.objects.get(pk=owner.pk).password, old_hash)
        self.assertFalse(User.objects.filter(username="demo_teacher").exists())

    def test_a_weak_password_is_refused(self):
        with self.assertRaises(CommandError):
            self.run_command("--password", "password")

        self.assertFalse(self.demo_users().exists())

    def test_a_generated_password_is_printed_and_works(self):
        with self.env_without_demo_password():
            output = self.run_command()

        marker = "Generated password: "
        self.assertIn(marker, output)
        password = output.split(marker, 1)[1].split()[0]
        self.assertTrue(User.objects.get(username="demo_student").check_password(password))

    def test_a_supplied_password_is_never_printed(self):
        output = self.run_command("--password", self.STRONG)

        self.assertNotIn(self.STRONG, output)
        self.assertNotIn("Generated password", output)

    def test_the_environment_password_is_used_and_not_printed(self):
        from unittest.mock import patch

        with patch.dict(os.environ, {"DEMO_PASSWORD": self.STRONG}):
            output = self.run_command()

        self.assertNotIn(self.STRONG, output)
        self.assertTrue(User.objects.get(username="demo_admin").check_password(self.STRONG))

    @staticmethod
    def env_without_demo_password():
        from unittest.mock import patch

        env = {k: v for k, v in os.environ.items() if k != "DEMO_PASSWORD"}
        return patch.dict(os.environ, env, clear=True)
