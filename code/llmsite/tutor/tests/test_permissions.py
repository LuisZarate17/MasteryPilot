"""Role-based access across every endpoint.

Roles are profile rows, not Django Groups (tutor/utils.py). Three things here
are easy to get wrong and are pinned deliberately:

* A superuser with no AdminProfile is still an admin — is_admin short-circuits
  on is_superuser.
* Decorator order differs by module. chat.py puts @require_http_methods
  outermost, so an anonymous GET to a POST-only endpoint is 405 before it is
  ever a redirect. curriculum.py and accounts.py put @login_required outermost
  and redirect first. Both are defensible; neither is documented anywhere else.
* A user with no profile at all is a de-facto student.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from unittest.mock import patch
import json

from ..models import AdminProfile, Chat, QuizAnswer, StudentProfile, TeacherProfile
from .base import PASSWORD, FakeAdapter, MasteryPilotTestCase


class RoleHelperTests(MasteryPilotTestCase):
    def test_superuser_without_a_profile_is_admin(self):
        from ..utils import is_admin, is_teacher_or_admin

        superuser = self.make_superuser()

        self.assertTrue(is_admin(superuser))
        self.assertTrue(is_teacher_or_admin(superuser))

    def test_profileless_user_is_neither_teacher_nor_admin(self):
        from ..utils import is_admin, is_teacher_or_admin

        user = self.make_user("nobody")

        self.assertFalse(is_admin(user))
        self.assertFalse(is_teacher_or_admin(user))

    def test_teacher_is_not_admin(self):
        from ..utils import is_admin, is_teacher_or_admin

        teacher = self.make_teacher("plain_teacher")

        self.assertTrue(is_teacher_or_admin(teacher))
        self.assertFalse(is_admin(teacher))

    def test_anonymous_is_neither(self):
        from django.contrib.auth.models import AnonymousUser

        from ..utils import is_admin, is_teacher_or_admin

        self.assertFalse(is_admin(AnonymousUser()))
        self.assertFalse(is_teacher_or_admin(AnonymousUser()))


class AnonymousAccessTests(MasteryPilotTestCase):
    """Nothing but signup and login is reachable without a session."""

    def test_get_endpoints_redirect_to_login(self):
        for name in ("landing", "chat", "dashboard", "chat_history", "progress_detail"):
            with self.subTest(view=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertIn("login", response["Location"])

    def test_api_chat_requires_login(self):
        """Regression: api_chat carried only @require_http_methods.

        It failed closed by accident — _load_messages_from_db returned None for
        AnonymousUser, giving a 400 — but nothing declared the requirement, and
        every sibling endpoint in the module has it.
        """
        response = self.client.post(
            reverse("api_chat"),
            data=json.dumps({"message": "hi"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_post_only_chat_endpoints_reject_anonymous(self):
        for name in ("api_new_session", "api_reset", "api_grade_quiz"):
            with self.subTest(view=name):
                response = self.client.post(reverse(name))
                self.assertEqual(response.status_code, 302)

    def test_method_check_precedes_auth_in_the_chat_module(self):
        """chat.py stacks @require_http_methods outermost, so this is 405."""
        self.assertEqual(self.client.get(reverse("api_chat")).status_code, 405)

    def test_auth_check_precedes_method_in_the_curriculum_module(self):
        """curriculum.py stacks @login_required outermost, so this redirects."""
        self.assertEqual(
            self.client.get(reverse("curriculum_delete")).status_code, 302
        )

    def test_signup_is_public(self):
        self.assertEqual(self.client.get(reverse("signup")).status_code, 200)


class StudentAccessTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("perm_student")
        self.client.force_login(self.student)

    def test_student_reaches_the_chat_page(self):
        self.assertEqual(self.client.get(reverse("chat")).status_code, 200)

    def test_student_is_denied_staff_pages(self):
        """@user_passes_test bounces to LOGIN_URL, not to the page itself."""
        for name in ("dashboard", "chat_history"):
            with self.subTest(view=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith("/login/"))

    def test_student_cannot_export_chats(self):
        response = self.client.get(
            reverse("api_export_chats"), {"student_id": self.student.id}
        )
        self.assertEqual(response.status_code, 302)

    def test_student_cannot_reach_admin_account_endpoints(self):
        for name in (
            "account_create",
            "account_delete",
            "account_password_edit",
            "student_edit",
        ):
            with self.subTest(view=name):
                self.assertEqual(self.client.post(reverse(name)).status_code, 302)

    def test_student_cannot_upload_or_delete_curriculum(self):
        self.assertEqual(self.client.post(reverse("upload_curriculum")).status_code, 302)
        self.assertEqual(self.client.post(reverse("curriculum_delete")).status_code, 302)

    def test_student_only_sees_their_own_sessions(self):
        mine = self.make_session(self.student, title="Mine")
        other = self.make_student("perm_other")
        self.make_session(other, title="Theirs")

        payload = json.loads(self.client.get(reverse("api_list_sessions")).content)

        titles = [s["title"] for s in payload["sessions"]]
        self.assertEqual(titles, ["Mine"])
        self.assertNotIn(str(mine.id), json.dumps(titles))

    def test_student_cannot_read_another_students_session(self):
        other = self.make_student("perm_other2")
        session = self.make_session(other)

        response = self.client.get(reverse("api_session_messages", args=[session.id]))

        self.assertEqual(response.status_code, 403)

    def test_student_cannot_delete_another_students_session(self):
        other = self.make_student("perm_other3")
        session = self.make_session(other)

        response = self.client.delete(reverse("api_delete_session", args=[session.id]))

        self.assertEqual(response.status_code, 404)

    def test_student_progress_summary_is_self_scoped(self):
        response = self.client.get(reverse("progress_summary"))

        self.assertEqual(response.status_code, 200)


class TeacherAccessTests(MasteryPilotTestCase):
    def setUp(self):
        self.teacher = self.make_teacher("perm_teacher")
        self.other_teacher = self.make_teacher("perm_teacher2")
        self.mine = self.make_student("assigned", teacher=self.teacher.teacherprofile)
        self.theirs = self.make_student(
            "unassigned", teacher=self.other_teacher.teacherprofile
        )
        self.client.force_login(self.teacher)

    def test_teacher_reaches_the_dashboard(self):
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_teacher_is_redirected_off_the_student_chat_page(self):
        response = self.client.get(reverse("chat"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("dashboard"), response["Location"])

    def test_teacher_can_list_sessions_for_an_assigned_student(self):
        self.make_session(self.mine, title="Assigned work")

        response = self.client.get(
            reverse("api_list_sessions"), {"student_id": self.mine.id}
        )

        self.assertEqual(response.status_code, 200)
        titles = [s["title"] for s in json.loads(response.content)["sessions"]]
        self.assertEqual(titles, ["Assigned work"])

    def test_teacher_cannot_enumerate_an_unassigned_students_sessions(self):
        """Regression: api_list_sessions had no assignment check at all.

        Any teacher could pass any user id — including other teachers' and
        admins' — and read back their session titles.
        """
        self.make_session(self.theirs, title="Private work")

        response = self.client.get(
            reverse("api_list_sessions"), {"student_id": self.theirs.id}
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Private work", response.content.decode())

    def test_teacher_cannot_enumerate_another_teachers_sessions(self):
        """A non-student target has no StudentProfile, so it must 403 too."""
        self.make_session(self.other_teacher, title="Teacher notes")

        response = self.client.get(
            reverse("api_list_sessions"), {"student_id": self.other_teacher.id}
        )

        self.assertEqual(response.status_code, 403)

    def test_teacher_can_read_an_assigned_students_session(self):
        session = self.make_session(self.mine)

        response = self.client.get(reverse("api_session_messages", args=[session.id]))

        self.assertEqual(response.status_code, 200)

    def test_teacher_cannot_read_an_unassigned_students_session(self):
        session = self.make_session(self.theirs)

        response = self.client.get(reverse("api_session_messages", args=[session.id]))

        self.assertEqual(response.status_code, 403)

    def test_teacher_cannot_reach_admin_account_endpoints(self):
        for name in ("account_create", "account_delete", "student_edit"):
            with self.subTest(view=name):
                self.assertEqual(self.client.post(reverse(name)).status_code, 302)

    def test_teacher_cannot_delete_curriculum(self):
        self.assertEqual(self.client.post(reverse("curriculum_delete")).status_code, 302)

    def test_teacher_can_view_an_assigned_students_progress(self):
        response = self.client.get(reverse("progress_detail"), {"student_id": self.mine.id})

        self.assertEqual(response.status_code, 200)

    def test_teacher_cannot_view_an_unassigned_students_progress(self):
        response = self.client.get(
            reverse("progress_detail"), {"student_id": self.theirs.id}
        )

        self.assertEqual(response.status_code, 403)


class AdminAccessTests(MasteryPilotTestCase):
    def setUp(self):
        self.admin = self.make_admin("perm_admin")
        self.teacher = self.make_teacher("perm_admin_teacher")
        self.student = self.make_student(
            "perm_admin_student", teacher=self.teacher.teacherprofile
        )
        self.client.force_login(self.admin)

    def test_admin_reaches_staff_pages(self):
        for name in ("dashboard", "chat_history"):
            with self.subTest(view=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_admin_lists_any_students_sessions(self):
        self.make_session(self.student, title="Anything")

        response = self.client.get(
            reverse("api_list_sessions"), {"student_id": self.student.id}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [s["title"] for s in json.loads(response.content)["sessions"]], ["Anything"]
        )

    def test_admin_reads_any_session(self):
        session = self.make_session(self.student)

        self.assertEqual(
            self.client.get(reverse("api_session_messages", args=[session.id])).status_code,
            200,
        )

    def test_admin_views_any_students_progress(self):
        response = self.client.get(
            reverse("progress_detail"), {"student_id": self.student.id}
        )

        self.assertEqual(response.status_code, 200)


class SuperuserAccessTests(MasteryPilotTestCase):
    """A superuser has no AdminProfile but must still be treated as admin."""

    def setUp(self):
        self.superuser = self.make_superuser("perm_super")
        self.teacher = self.make_teacher("perm_super_teacher")
        self.student = self.make_student(
            "perm_super_student", teacher=self.teacher.teacherprofile
        )
        self.client.force_login(self.superuser)

    def test_superuser_reaches_the_dashboard(self):
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_superuser_reaches_admin_only_endpoints(self):
        response = self.client.post(reverse("student_edit"), {"student_id": "not-a-number"})

        # Redirects back to the dashboard on bad input rather than 302ing to
        # login, which is what a permission failure would look like.
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("dashboard"), response["Location"])

    def test_superuser_lists_any_students_sessions(self):
        self.make_session(self.student, title="Super view")

        response = self.client.get(
            reverse("api_list_sessions"), {"student_id": self.student.id}
        )

        self.assertEqual(response.status_code, 200)


class CrossStudentSessionTests(MasteryPilotTestCase):
    """A student who knows another student's session id cannot act on it.

    Each test plays the attacker and then re-reads the victim's rows from the
    database, so a pass means nothing changed rather than only that the status
    code looked right.
    """

    def setUp(self):
        self.attacker = self.make_student("xs_attacker")
        self.victim = self.make_student("xs_victim")
        self.victim_session = self.make_session(self.victim, title="Victim original")
        self.make_chat(self.victim_session, "user", "victim says hi")
        self.attacker_session = self.make_session(self.attacker, title="Attacker own")
        self.client.force_login(self.attacker)

    def post_json(self, name, payload, **url_kwargs):
        return self.client.post(
            reverse(name, **url_kwargs),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_cannot_rename_another_students_session(self):
        response = self.post_json(
            "api_rename_session", {"title": "pwned"}, args=[self.victim_session.id]
        )

        self.assertEqual(response.status_code, 404)
        self.victim_session.refresh_from_db()
        self.assertEqual(self.victim_session.title, "Victim original")

    def test_cannot_select_another_students_session(self):
        self.set_active_session(self.attacker_session)

        response = self.client.post(
            reverse("api_select_session", args=[self.victim_session.id])
        )

        self.assertEqual(response.status_code, 404)
        active = self.client.session.get("session_id")
        self.assertNotEqual(active, str(self.victim_session.id))
        self.assertEqual(active, str(self.attacker_session.id))

    def test_cannot_init_another_students_session(self):
        before = Chat.objects.filter(session=self.victim_session).count()

        with patch("tutor.views.chat._adapter", return_value=FakeAdapter()):
            response = self.client.post(
                reverse("api_session_init", args=[self.victim_session.id])
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            Chat.objects.filter(session=self.victim_session).count(), before
        )
        self.assertNotEqual(
            self.client.session.get("session_id"), str(self.victim_session.id)
        )

    def test_cannot_grade_against_another_students_session(self):
        quiz = self.make_quiz(self.victim_session, {"q1": self.mc_question()})
        quiz_json_before = json.loads(json.dumps(quiz.quiz_json))
        self.set_active_session(self.victim_session)

        response = self.post_json("api_grade_quiz", {"answers": "1"})

        self.assertEqual(response.status_code, 400)
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, "active")
        self.assertEqual(quiz.quiz_json, quiz_json_before)
        self.assertEqual(quiz.earned_pts, 0.0)
        self.assertEqual(quiz.possible_pts, 0.0)
        self.assertIsNone(quiz.ended_at)
        self.assertFalse(QuizAnswer.objects.filter(quiz=quiz).exists())

    def test_cannot_chat_into_another_students_session(self):
        before = Chat.objects.filter(session=self.victim_session).count()
        self.set_active_session(self.victim_session)
        adapter = FakeAdapter()

        with patch("tutor.views.chat._adapter", return_value=adapter):
            response = self.post_json("api_chat", {"message": "planted message"})

        # The planted id fails the owner filter, so there is no active chat.
        self.assertEqual(response.status_code, 400)
        self.assertEqual(adapter.send_message_calls, [])
        self.assertEqual(
            Chat.objects.filter(session=self.victim_session).count(), before
        )
        self.assertFalse(
            Chat.objects.filter(message__contains="planted message").exists()
        )

    def test_anonymous_cannot_touch_a_session(self):
        self.client.logout()
        cases = (
            ("api_rename_session", {"title": "pwned"}),
            ("api_select_session", {}),
            ("api_session_init", {}),
        )
        before = Chat.objects.filter(session=self.victim_session).count()

        for name, payload in cases:
            with self.subTest(view=name):
                response = self.post_json(
                    name, payload, args=[self.victim_session.id]
                )
                self.assertIn(response.status_code, (302, 405))
                if response.status_code == 302:
                    self.assertIn("login", response["Location"])

        self.victim_session.refresh_from_db()
        self.assertEqual(self.victim_session.title, "Victim original")
        self.assertEqual(
            Chat.objects.filter(session=self.victim_session).count(), before
        )
        self.assertIsNone(self.client.session.get("session_id"))


class StudentIdParameterTests(MasteryPilotTestCase):
    """?student_id= is a teacher/admin feature; a student's copy is ignored."""

    def setUp(self):
        self.student = self.make_student("sid_student")
        self.other = self.make_student("sid_other")
        self.make_session(self.student, title="Own distinctive title")
        self.make_session(self.other, title="Other distinctive title")
        self.client.force_login(self.student)

    def test_progress_detail_ignores_student_id_for_a_student(self):
        response = self.client.get(
            reverse("progress_detail"), {"student_id": self.other.id}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["target_user"], self.student)
        self.assertNotEqual(response.context["target_user"], self.other)
        titles = [s["title"] for s in response.context["session_history"]]
        self.assertEqual(titles, ["Own distinctive title"])
        content = response.content.decode()
        self.assertNotIn("Other distinctive title", content)
        self.assertNotIn(self.other.username, content)

    def test_list_sessions_ignores_student_id_for_a_student(self):
        response = self.client.get(
            reverse("api_list_sessions"), {"student_id": self.other.id}
        )

        self.assertEqual(response.status_code, 200)
        titles = [s["title"] for s in json.loads(response.content)["sessions"]]
        self.assertEqual(titles, ["Own distinctive title"])
        self.assertNotIn("Other distinctive title", response.content.decode())


class SignupCannotCreateStaffTests(MasteryPilotTestCase):
    def test_extra_privilege_fields_are_ignored(self):
        from ..utils import is_admin, is_teacher_or_admin

        response = self.client.post(
            reverse("signup"),
            {
                "username": "sneaky_signup",
                "email": "sneaky@example.com",
                "full_name": "Sneaky Signup",
                "password1": PASSWORD,
                "password2": PASSWORD,
                "is_staff": "on",
                "is_superuser": "on",
                "role": "admin",
                "teacher": "1",
                "is_teacher": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username="sneaky_signup")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(StudentProfile.objects.filter(user=user).exists())
        self.assertFalse(TeacherProfile.objects.filter(user=user).exists())
        self.assertFalse(AdminProfile.objects.filter(user=user).exists())
        self.assertFalse(is_admin(user))
        self.assertFalse(is_teacher_or_admin(user))


class StudentCurriculumViewTests(MasteryPilotTestCase):
    def test_student_cannot_view_curriculum_files(self):
        self.client.force_login(self.make_student("cur_student"))

        response = self.client.get(
            reverse("curriculum_view", args=["anything.pdf"])
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/"))
