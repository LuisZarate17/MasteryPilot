"""Progress metrics, activity streaks, and the refresh_all_progress command.

Two units are in play and it is easy to conflate them:

    StudentProgress.quiz_average   0-1 fraction   (accounts.py compares < 0.7)
    the returned metrics dict      percentage     (progress.py compares < 70)

That split is deliberate and consistent. What was not consistent was the
weighting: overall_completion_percent divided the fraction by 100 again.
"""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from ..models import Quiz, StudentProgress
from ..utils import calculate_activity_streak, calculate_student_progress
from .base import MasteryPilotTestCase


class ProgressCalculationTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("prog_student")

    def graded_quiz(self, earned, possible):
        session = self.make_session(self.student)
        return Quiz.objects.create(
            session=session,
            status="graded",
            quiz_json={"test": {}},
            earned_pts=earned,
            possible_pts=possible,
        )

    def test_a_student_with_no_activity_is_at_zero(self):
        metrics = calculate_student_progress(self.student)

        self.assertEqual(metrics["overall_completion_percent"], 0.0)
        self.assertIsNone(metrics["quiz_average"])
        self.assertEqual(metrics["total_sessions"], 0)
        self.assertEqual(metrics["total_quizzes"], 0)
        self.assertIsNone(metrics["last_activity"])

    def test_a_perfect_quiz_contributes_the_full_seventy_points(self):
        """Regression: this used to contribute 0.7, not 70.

        quiz_average is earned/possible — already a 0-1 fraction — and the
        weighting divided it by 100 a second time, so quiz performance was
        worth almost nothing in overall_completion_percent.
        """
        self.graded_quiz(earned=10, possible=10)

        metrics = calculate_student_progress(self.student)

        # One session also exists (quizzes hang off one), worth 1/10 * 30 = 3.
        self.assertAlmostEqual(metrics["overall_completion_percent"], 73.0, places=4)

    def test_a_half_correct_quiz_contributes_half_the_weight(self):
        self.graded_quiz(earned=5, possible=10)

        metrics = calculate_student_progress(self.student)

        self.assertAlmostEqual(metrics["overall_completion_percent"], 35.0 + 3.0, places=4)

    def test_quiz_average_is_returned_as_a_percentage(self):
        self.graded_quiz(earned=3, possible=4)

        metrics = calculate_student_progress(self.student)

        self.assertAlmostEqual(metrics["quiz_average"], 75.0, places=4)

    def test_quiz_average_is_stored_as_a_fraction(self):
        """The model field and the returned dict deliberately differ."""
        self.graded_quiz(earned=3, possible=4)

        calculate_student_progress(self.student)

        progress = StudentProgress.objects.get(user=self.student)
        self.assertAlmostEqual(float(progress.quiz_average), 0.75, places=2)

    def test_quiz_average_spans_every_graded_attempt(self):
        self.graded_quiz(earned=10, possible=10)
        self.graded_quiz(earned=0, possible=10)

        metrics = calculate_student_progress(self.student)

        self.assertAlmostEqual(metrics["quiz_average"], 50.0, places=4)
        self.assertEqual(metrics["total_quizzes"], 2)

    def test_ungraded_quizzes_are_excluded(self):
        session = self.make_session(self.student)
        self.make_quiz(session, {"q1": self.mc_question()})  # active

        metrics = calculate_student_progress(self.student)

        self.assertEqual(metrics["total_quizzes"], 0)
        self.assertIsNone(metrics["quiz_average"])

    def test_the_session_component_caps_at_ten_sessions(self):
        for i in range(15):
            self.make_session(self.student, title=f"S{i}")

        metrics = calculate_student_progress(self.student)

        self.assertAlmostEqual(metrics["overall_completion_percent"], 30.0, places=4)
        self.assertEqual(metrics["total_sessions"], 15)

    def test_the_session_component_scales_below_the_cap(self):
        for i in range(4):
            self.make_session(self.student, title=f"S{i}")

        metrics = calculate_student_progress(self.student)

        self.assertAlmostEqual(metrics["overall_completion_percent"], 12.0, places=4)

    def test_completion_cannot_exceed_one_hundred(self):
        for i in range(12):
            self.make_session(self.student, title=f"S{i}")
        self.graded_quiz(earned=10, possible=10)

        metrics = calculate_student_progress(self.student)

        self.assertLessEqual(metrics["overall_completion_percent"], 100.0)

    def test_current_module_is_the_latest_session_title(self):
        self.make_session(self.student, title="Older")
        self.make_session(self.student, title="Newest")

        metrics = calculate_student_progress(self.student)

        self.assertEqual(metrics["current_module"], "Newest")

    def test_messages_are_counted(self):
        session = self.make_session(self.student)
        self.make_chat(session, "user", "one")
        self.make_chat(session, "user", "two")
        self.make_chat(session, "assistant", "not counted")

        metrics = calculate_student_progress(self.student)

        self.assertEqual(metrics["total_messages"], 2)

    def test_last_activity_tracks_the_most_recent_chat(self):
        session = self.make_session(self.student)
        self.make_chat(session, "user", "hello")

        metrics = calculate_student_progress(self.student)

        self.assertIsNotNone(metrics["last_activity"])

    def test_progress_row_is_created_once_and_reused(self):
        calculate_student_progress(self.student)
        calculate_student_progress(self.student)

        self.assertEqual(StudentProgress.objects.filter(user=self.student).count(), 1)

    def test_other_students_activity_does_not_leak_in(self):
        other = self.make_student("prog_other")
        for i in range(5):
            self.make_session(other, title=f"Theirs {i}")

        metrics = calculate_student_progress(self.student)

        self.assertEqual(metrics["total_sessions"], 0)


class ActivityStreakTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("streak_student")
        self.session = self.make_session(self.student)

    def chat_on(self, days_ago):
        chat = self.make_chat(self.session, "user", f"message {days_ago}")
        # auto_now_add ignores assignment, so write the timestamp directly.
        stamp = timezone.now() - timedelta(days=days_ago)
        type(chat).objects.filter(pk=chat.pk).update(created_at=stamp)
        return chat

    def test_no_activity_is_a_zero_streak(self):
        self.assertEqual(calculate_activity_streak(self.student), 0)

    def test_activity_today_is_a_streak_of_one(self):
        self.chat_on(0)

        self.assertEqual(calculate_activity_streak(self.student), 1)

    def test_consecutive_days_accumulate(self):
        for day in (0, 1, 2, 3):
            self.chat_on(day)

        self.assertEqual(calculate_activity_streak(self.student), 4)

    def test_a_gap_ends_the_streak(self):
        for day in (0, 1, 3, 4):
            self.chat_on(day)

        self.assertEqual(calculate_activity_streak(self.student), 2)

    def test_multiple_messages_in_one_day_count_once(self):
        self.chat_on(0)
        self.chat_on(0)
        self.chat_on(1)

        self.assertEqual(calculate_activity_streak(self.student), 2)

    def test_yesterday_still_counts_as_an_active_streak(self):
        self.chat_on(1)
        self.chat_on(2)

        self.assertEqual(calculate_activity_streak(self.student), 2)

    def test_a_stale_streak_is_broken(self):
        """Nothing today or yesterday means the streak is over."""
        self.chat_on(5)
        self.chat_on(6)

        self.assertEqual(calculate_activity_streak(self.student), 0)


class RefreshAllProgressCommandTests(MasteryPilotTestCase):
    def setUp(self):
        self.teacher = self.make_teacher("cmd_teacher")
        self.student = self.make_student("cmd_student", teacher=self.teacher.teacherprofile)
        self.make_session(self.student)

    def run_command(self, *args):
        out = StringIO()
        call_command("refresh_all_progress", *args, stdout=out)
        return out.getvalue()

    def test_it_creates_progress_for_every_user(self):
        output = self.run_command()

        self.assertIn("cmd_student", output)
        self.assertTrue(StudentProgress.objects.filter(user=self.student).exists())

    def test_a_single_user_can_be_targeted(self):
        output = self.run_command("--user-id", str(self.student.id))

        self.assertIn("cmd_student", output)
        self.assertNotIn("cmd_teacher", output)

    def test_students_only_skips_staff(self):
        output = self.run_command("--students-only")

        self.assertIn("cmd_student", output)
        self.assertNotIn("cmd_teacher", output)

    def test_an_unknown_user_id_is_reported_not_raised(self):
        output = self.run_command("--user-id", "999999")

        self.assertIn("999999", output)
        self.assertFalse(StudentProgress.objects.filter(user=self.student).exists())

    def test_it_refreshes_stale_stored_values(self):
        """The point of the command: recompute rows written by older code."""
        StudentProgress.objects.create(
            user=self.student, overall_completion_percent=99.0, total_sessions=42
        )

        self.run_command("--user-id", str(self.student.id))

        progress = StudentProgress.objects.get(user=self.student)
        self.assertEqual(progress.total_sessions, 1)
        self.assertAlmostEqual(float(progress.overall_completion_percent), 3.0, places=4)


class ProgressViewTests(MasteryPilotTestCase):
    def setUp(self):
        self.teacher = self.make_teacher("pv_teacher")
        self.student = self.make_student("pv_student", teacher=self.teacher.teacherprofile)

    def test_a_student_sees_their_own_progress(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse("progress_detail"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["target_user"], self.student)

    def test_progress_summary_returns_metrics(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse("progress_summary"))

        self.assertEqual(response.status_code, 200)

    def test_a_non_numeric_student_id_is_a_404_not_a_500(self):
        """Regression: User.objects.get(id="abc") raises ValueError.

        The except tuple caught only DoesNotExist variants, so a hand-edited
        query string produced an uncaught 500.
        """
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("progress_detail"), {"student_id": "not-a-number"})

        self.assertEqual(response.status_code, 404)

    def test_an_unknown_student_id_is_a_404(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("progress_detail"), {"student_id": "999999"})

        self.assertEqual(response.status_code, 404)

    def test_a_student_cannot_view_someone_else_by_id(self):
        """Non-staff fall through to themselves rather than being denied."""
        other = self.make_student("pv_other")
        self.client.force_login(self.student)

        response = self.client.get(reverse("progress_detail"), {"student_id": other.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["target_user"], self.student)
