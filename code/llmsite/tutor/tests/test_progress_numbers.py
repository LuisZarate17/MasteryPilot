"""Progress numbers that used to mislead.

A real 0% was treated as "no data", one wrong answer flagged a student as
Failing, abandoned quizzes were invisible, empty sessions earned completion
credit, escapejs mangled class names, and a student could borrow the teacher's
view with ?student_id=.
"""

from django.urls import reverse

from ..models import Quiz, QuizAnswer
from ..utils import calculate_student_progress
from ..views.accounts import MIN_GRADED_QUESTIONS_FOR_FLAG
from .base import MasteryPilotTestCase


def graded_quiz(session, earned, possible, correct_flags=None):
    """A graded quiz; *correct_flags* also writes the per-item graded_json."""
    quiz = Quiz.objects.create(
        session=session,
        status="graded",
        quiz_json={"test": {}},
        earned_pts=earned,
        possible_pts=possible,
    )
    if correct_flags is not None:
        QuizAnswer.objects.create(
            quiz=quiz,
            answers_json={},
            graded_json={f"q{n}": {"isCorrect": flag} for n, flag in enumerate(correct_flags)},
        )
    return quiz


class ZeroPercentTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("zero_student")
        session = self.make_session(self.student, title="Failed session")
        graded_quiz(session, earned=0, possible=2, correct_flags=[False, False])

    def test_the_landing_page_shows_zero_not_no_data(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse("landing"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["quiz_avg"])
        self.assertEqual(response.context["quiz_avg"], 0)
        self.assertContains(response, "0.0%")
        self.assertNotContains(response, "No quizzes yet")

    def test_progress_summary_says_to_review_topics(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse("progress_summary"))

        self.assertEqual(response.json()["quiz_average"], 0)
        self.assertEqual(response.json()["next_step"], "Review topics and improve quiz scores")

    def test_progress_detail_session_history_shows_zero(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse("progress_detail"))

        history = response.context["session_history"]
        self.assertEqual(len(history), 1)
        self.assertIsNotNone(history[0]["quiz_average"])
        self.assertEqual(history[0]["quiz_average"], 0)
        self.assertContains(response, "bg-red-100 text-red-800")

    def test_progress_detail_renders_zero_for_the_average(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse("progress_detail"))

        self.assertEqual(response.context["metrics"]["quiz_average"], 0)
        self.assertContains(response, "0.0%")


class InterventionFlagTests(MasteryPilotTestCase):
    def setUp(self):
        self.teacher = self.make_teacher("flag_teacher")
        self.student = self.make_student("flag_student", teacher=self.teacher.teacherprofile)
        self.session = self.make_session(self.student)

    def flags(self):
        calculate_student_progress(self.student)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        return response, response.context["intervention_list"]

    def test_the_minimum_is_five_questions(self):
        self.assertEqual(MIN_GRADED_QUESTIONS_FOR_FLAG, 5)

    def test_one_wrong_question_is_not_flagged(self):
        graded_quiz(self.session, earned=0, possible=1)

        response, flagged = self.flags()

        self.assertEqual(flagged, [])
        self.assertFalse(response.context["intervention_alert"])

    def test_four_questions_at_zero_are_not_flagged(self):
        graded_quiz(self.session, earned=0, possible=4)

        _, flagged = self.flags()

        self.assertEqual(flagged, [])

    def test_five_questions_at_zero_are_failing(self):
        graded_quiz(self.session, earned=0, possible=5)

        response, flagged = self.flags()

        self.assertEqual(len(flagged), 1)
        student, level, count = flagged[0]
        self.assertEqual(student.user, self.student)
        self.assertEqual(level, 1)
        self.assertEqual(count, 5)
        self.assertIsInstance(count, int)
        self.assertTrue(response.context["intervention_alert"])
        self.assertContains(response, "Failing")
        self.assertContains(response, "· 5 questions")

    def test_five_questions_at_sixty_percent_are_struggling(self):
        graded_quiz(self.session, earned=3, possible=5)

        response, flagged = self.flags()

        self.assertEqual(len(flagged), 1)
        _, level, count = flagged[0]
        self.assertEqual(level, 0)
        self.assertEqual(count, 5)
        self.assertFalse(response.context["intervention_alert"])

    def test_the_count_spans_every_graded_quiz(self):
        graded_quiz(self.session, earned=0, possible=3)
        graded_quiz(self.make_session(self.student, title="Second"), earned=0, possible=4)

        _, flagged = self.flags()

        self.assertEqual(flagged[0][2], 7)

    def test_ungraded_quizzes_do_not_count_toward_the_minimum(self):
        graded_quiz(self.session, earned=0, possible=2)
        Quiz.objects.create(
            session=self.make_session(self.student, title="Walked away"),
            status="submitted",
            quiz_json={"test": {}},
            possible_pts=10,
        )

        _, flagged = self.flags()

        self.assertEqual(flagged, [])


class AbandonedQuizTests(MasteryPilotTestCase):
    def setUp(self):
        self.teacher = self.make_teacher("ab_teacher")
        self.student = self.make_student("ab_student", teacher=self.teacher.teacherprofile)

    def add_quiz(self, status, title):
        return Quiz.objects.create(
            session=self.make_session(self.student, title=title),
            status=status,
            quiz_json={"test": {}},
        )

    def test_only_submitted_quizzes_are_counted(self):
        self.add_quiz("submitted", "one")
        self.add_quiz("submitted", "two")
        self.add_quiz("active", "three")
        self.add_quiz("graded", "four")

        metrics = calculate_student_progress(self.student)

        self.assertEqual(metrics["abandoned_quizzes"], 2)
        self.assertEqual(metrics["total_quizzes"], 1)

    def test_another_students_quizzes_are_not_counted(self):
        other = self.make_student("ab_other")
        Quiz.objects.create(
            session=self.make_session(other), status="submitted", quiz_json={"test": {}}
        )

        metrics = calculate_student_progress(self.student)

        self.assertEqual(metrics["abandoned_quizzes"], 0)

    def test_a_teacher_sees_the_count(self):
        self.add_quiz("submitted", "one")
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("progress_detail"), {"student_id": self.student.id})

        self.assertEqual(response.context["metrics"]["abandoned_quizzes"], 1)
        self.assertContains(response, "Quizzes abandoned: 1")

    def test_a_student_does_not_see_it_on_their_own_page(self):
        self.add_quiz("submitted", "one")
        self.client.force_login(self.student)

        response = self.client.get(reverse("progress_detail"))

        self.assertNotContains(response, "Quizzes abandoned")


class CompletionTests(MasteryPilotTestCase):
    def setUp(self):
        self.student = self.make_student("comp_student")

    def test_sessions_without_a_student_message_earn_nothing(self):
        for i in range(10):
            self.bootstrap_session(self.make_session(self.student, title=f"S{i}"))

        metrics = calculate_student_progress(self.student)

        self.assertEqual(metrics["total_sessions"], 10)
        self.assertEqual(metrics["overall_completion_percent"], 0)

    def test_sessions_with_a_student_message_earn_the_full_thirty(self):
        for i in range(10):
            session = self.make_session(self.student, title=f"S{i}")
            self.bootstrap_session(session)
            self.make_chat(session, "user", f"my question {i}")

        metrics = calculate_student_progress(self.student)

        self.assertEqual(metrics["total_sessions"], 10)
        self.assertAlmostEqual(metrics["overall_completion_percent"], 30.0, places=4)

    def test_the_bootstrap_row_alone_does_not_count(self):
        self.bootstrap_session(self.make_session(self.student))

        metrics = calculate_student_progress(self.student)

        self.assertEqual(metrics["total_sessions"], 1)
        self.assertEqual(metrics["overall_completion_percent"], 0)

    def test_one_active_session_earns_a_tenth(self):
        self.bootstrap_session(self.make_session(self.student, title="Idle"))
        active = self.make_session(self.student, title="Active")
        self.bootstrap_session(active)
        self.make_chat(active, "user", "hello")

        metrics = calculate_student_progress(self.student)

        self.assertAlmostEqual(metrics["overall_completion_percent"], 3.0, places=4)


class DashboardAttributeEscapingTests(MasteryPilotTestCase):
    def test_classes_reach_the_data_attribute_unmangled(self):
        teacher = self.make_teacher("esc_teacher")
        self.make_student(
            "esc_student",
            teacher=teacher.teacherprofile,
            classes="Pre-Calculus; History",
        )
        self.client.force_login(teacher)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, 'data-classes="Pre-Calculus; History"')
        self.assertNotContains(response, "\\u002D")

    def test_every_admin_edit_attribute_is_unmangled(self):
        # The admin view renders the student Edit button (whose value is saved
        # back by student_edit) and the teacher/admin password buttons.
        admin = self.make_admin("esc_admin", display_name="Ann-Marie; Admin")
        teacher = self.make_teacher("esc_teacher2", display_name="Jo-Ann; Teacher")
        self.make_student(
            "esc_student2",
            teacher=teacher.teacherprofile,
            classes="Pre-Calculus; History",
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("dashboard"))

        # One Chat History button and one Edit button carry the classes.
        self.assertContains(response, 'data-classes="Pre-Calculus; History"', count=2)
        self.assertContains(response, 'data-display-name="Jo-Ann; Teacher"')
        self.assertContains(response, 'data-display-name="Ann-Marie; Admin"')
        self.assertNotContains(response, "\\u00")

    def test_markup_in_classes_still_cannot_leave_the_attribute(self):
        # Without escapejs, Django's HTML autoescaping is what keeps a quote
        # from closing the attribute.
        admin = self.make_admin("esc_admin3")
        self.make_student("esc_student3", classes='"><img src=x onerror=alert(1)>')
        self.client.force_login(admin)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(
            response, 'data-classes="&quot;&gt;&lt;img src=x onerror=alert(1)&gt;"'
        )
        self.assertNotContains(response, "<img src=x onerror")


class IsViewingOtherTests(MasteryPilotTestCase):
    def setUp(self):
        self.teacher = self.make_teacher("vo_teacher")
        self.student = self.make_student("vo_student", teacher=self.teacher.teacherprofile)
        self.other = self.make_student("vo_other")

    def test_a_student_naming_someone_else_is_not_viewing_other(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse("progress_detail"), {"student_id": self.other.id})

        self.assertEqual(response.context["target_user"], self.student)
        self.assertFalse(response.context["is_viewing_other"])
        self.assertContains(response, "Your Progress Dashboard")

    def test_a_student_naming_themselves_is_not_viewing_other(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse("progress_detail"), {"student_id": self.student.id})

        self.assertFalse(response.context["is_viewing_other"])

    def test_a_student_with_a_junk_id_is_not_viewing_other(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse("progress_detail"), {"student_id": "anything"})

        self.assertFalse(response.context["is_viewing_other"])

    def test_a_teacher_viewing_their_student_is_viewing_other(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("progress_detail"), {"student_id": self.student.id})

        self.assertEqual(response.context["target_user"], self.student)
        self.assertTrue(response.context["is_viewing_other"])

    def test_a_teacher_without_a_student_id_is_not_viewing_other(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("progress_detail"))

        self.assertFalse(response.context["is_viewing_other"])
