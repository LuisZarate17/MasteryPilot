"""Signup, the staff dashboard, and account administration."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
import os

from ..forms import SignupForm
from ..models import AdminProfile, Quiz, StudentProfile, StudentProgress, TeacherProfile
from ..utils import is_admin, is_teacher_or_admin

# Fewest graded questions before a low quiz average flags a student for
# intervention; one wrong answer on a one-question quiz is not a trend.
MIN_GRADED_QUESTIONS_FOR_FLAG = 5


def _split_full_name(full_name: str) -> tuple[str, str, str]:
    cleaned = (full_name or "").strip()
    if not cleaned:
        return "", "", ""

    parts = cleaned.split(None, 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""
    return cleaned, first_name, last_name


def _display_name_for_user(user, explicit_name: str = "") -> str:
    explicit = (explicit_name or "").strip()
    if explicit:
        return explicit

    full_name = (user.get_full_name() or "").strip()
    if full_name:
        return full_name

    return user.username


def _password_problems(password, user) -> list[str]:
    """Messages from the configured password validators; empty means acceptable."""
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        return list(exc.messages)
    return []


def _may_manage(actor, target) -> bool:
    """Only a superuser may touch a superuser's account."""
    return actor.is_superuser or not target.is_superuser


def signup(request):
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("/")
    else:
        form = SignupForm()
    return render(request, "signup.html", {"form": form})


@login_required
@user_passes_test(is_teacher_or_admin)
def dashboard_page(request):
    teachers = TeacherProfile.objects.select_related("user").all()
    admins = AdminProfile.objects.select_related("user").all()
    is_admin_flag = is_admin(request.user)
    try:
        teacher_profile = TeacherProfile.objects.get(user=request.user)
    except TeacherProfile.DoesNotExist:
        teacher_profile = None

    is_teacher_flag = teacher_profile is not None

    # Provide all students to admins
    if is_admin_flag:
        students = StudentProfile.objects.select_related("user", "teacher").all()
    # Provide only assigned students to teachers
    elif is_teacher_flag:
        students = StudentProfile.objects.select_related("user", "teacher").filter(
            teacher=teacher_profile
        )
    else:
        students = StudentProfile.objects.none()

    files = []
    if os.path.exists(settings.CURRICULUM_ROOT):
        files = sorted(os.listdir(settings.CURRICULUM_ROOT))

    # Get intervention list
    intervention_list = []
    intervention_alert = False
    for student in students:
        progress = StudentProgress.objects.filter(user=student.user).first()
        if progress is None:
            continue

        if progress.quiz_average is None:
            continue

        # Every question is worth one point, so possible_pts is the number of
        # questions the student has been graded on. A handful of answers is too
        # little evidence to flag anyone.
        graded_questions = int(
            Quiz.objects.filter(session__owner=student.user, status="graded")
            .aggregate(total=Sum("possible_pts"))["total"]
            or 0
        )
        if graded_questions < MIN_GRADED_QUESTIONS_FOR_FLAG:
            continue

        if progress.quiz_average < 0.7:
            if progress.quiz_average < 0.5:
                intervention_list.append((student, 1, graded_questions))
                intervention_alert = True
            else:
                intervention_list.append((student, 0, graded_questions))


    context = {
        "intervention_alert": intervention_alert,
        "teachers": teachers,
        "admins": admins,
        "students": students,
        "intervention_list": intervention_list,
        "curriculum_files": files,
        "is_admin": is_admin_flag,
        "is_teacher": is_teacher_flag,
    }

    return render(request, "dashboard_admin_mentor.html", context)


@login_required(login_url="login")
@user_passes_test(is_teacher_or_admin)
def chat_history(request):
    return render(request, "chat_history.html")


@require_http_methods(["POST"])
@login_required
@user_passes_test(is_admin)
def account_create(request):
    User = get_user_model()

    role = (request.POST.get("role") or "").strip()
    username = (request.POST.get("username") or "").strip()
    full_name = (request.POST.get("full_name") or "").strip()
    email = (request.POST.get("email") or "").strip()
    password = request.POST.get("password") or ""

    grade = (request.POST.get("grade") or "").strip()
    classes = (request.POST.get("classes") or "").strip()

    if not role or not username or not password:
        messages.error(request, "Role, username and password are required.")
        return redirect("dashboard")

    if role not in ("teacher", "admin", "student"):
        messages.error(request, "Choose teacher, admin or student as the role.")
        return redirect("dashboard")

    if User.objects.filter(username=username).exists():
        messages.error(request, f"The username {username} is already taken.")
        return redirect("dashboard")

    _, first_name, last_name = _split_full_name(full_name)

    # Unsaved user, so the similarity validator can compare against its fields.
    candidate = User(
        username=username,
        email=email,
        first_name=first_name,
        last_name=last_name,
    )
    problems = _password_problems(password, candidate)
    if problems:
        messages.error(request, " ".join(problems))
        return redirect("dashboard")

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
    )

    display_name = _display_name_for_user(user, full_name)

    if role == "teacher":
        TeacherProfile.objects.create(user=user, display_name=display_name)
    elif role == "admin":
        AdminProfile.objects.create(user=user, display_name=display_name)
    else:
        StudentProfile.objects.create(
            user=user,
            display_name=display_name,
            grade=grade,
            classes=classes,
        )

    messages.success(request, f"Created {role} account {username}.")
    return redirect("dashboard")


@require_http_methods(["POST"])
@login_required
@user_passes_test(is_admin)
def account_password_edit(request):
    user_id_raw = request.POST.get("user_id")
    pw = request.POST.get("password")
    pwc = request.POST.get("password_confirm")

    # Check the password first: with both fields absent `pw == pwc` is
    # None == None, and set_password(None) would lock the account.
    if not pw:
        messages.error(request, "Enter a new password.")
        return redirect("dashboard")

    if pw != pwc:
        messages.error(request, "The passwords do not match.")
        return redirect("dashboard")

    User = get_user_model()

    try:
        target = User.objects.get(id=int(user_id_raw))
    except (TypeError, ValueError, User.DoesNotExist):
        messages.error(request, "That account was not found.")
        return redirect("dashboard")

    if not _may_manage(request.user, target):
        messages.error(request, "Only a superuser can change a superuser's password.")
        return redirect("dashboard")

    problems = _password_problems(pw, target)
    if problems:
        messages.error(request, " ".join(problems))
        return redirect("dashboard")

    target.set_password(pw)
    target.save()
    messages.success(request, f"Password changed for {target.username}.")
    return redirect("dashboard")


@require_http_methods(["POST"])
@login_required
@user_passes_test(is_admin)
def account_delete(request):
    User = get_user_model()

    user_id = request.POST.get("user_id")

    try:
        user = User.objects.get(id=int(user_id))
    except (TypeError, ValueError, User.DoesNotExist):
        messages.error(request, "That account was not found.")
        return redirect("dashboard")

    # Do not let an admin delete themselves
    if user == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect("dashboard")

    if not _may_manage(request.user, user):
        messages.error(request, "Only a superuser can delete a superuser account.")
        return redirect("dashboard")

    username = user.username
    user.delete()
    messages.success(request, f"Deleted account {username}.")
    return redirect("dashboard")


@require_http_methods(["POST"])
@login_required
@user_passes_test(is_admin)
def student_edit(request):
    student_id_raw = request.POST.get("student_id")
    classes = (request.POST.get("classes") or "").strip()
    teacher_id_raw = request.POST.get("teacher_id")
    pw = request.POST.get("password")
    pwc = request.POST.get("password_confirm")

    # Guard against missing or non numeric student id
    try:
        student_id = int(student_id_raw)
    except (TypeError, ValueError):
        return redirect("dashboard")

    try:
        student = StudentProfile.objects.get(id=student_id)
    except StudentProfile.DoesNotExist:
        return redirect("dashboard")

    # A submitted password is checked before anything is saved, so a rejected
    # change does not leave the class or teacher edits half applied.
    password_submitted = bool(pw or pwc)
    if password_submitted:
        problem = None
        if not _may_manage(request.user, student.user):
            problem = "Only a superuser can change a superuser's password."
        elif pw != pwc:
            problem = "The passwords do not match."
        else:
            problems = _password_problems(pw, student.user)
            if problems:
                problem = " ".join(problems)
        if problem:
            messages.error(request, problem)
            return redirect("dashboard")

    student.classes = classes

    # Clean teacher id too
    teacher = None
    if teacher_id_raw not in (None, "", "undefined"):
        try:
            teacher_id = int(teacher_id_raw)
            teacher = TeacherProfile.objects.get(id=teacher_id)
        except (ValueError, TeacherProfile.DoesNotExist):
            teacher = None

    student.teacher = teacher
    # Only touch the password when one was actually submitted. The form posts
    # no password fields when the admin is just reassigning a teacher, and
    # `pw == pwc` was true for None == None — which called set_password(None)
    # and silently left the account with an unusable password.
    if password_submitted:
        student.user.set_password(pw)
    student.save()
    student.user.save()

    name = student.display_name or student.user.username
    messages.success(request, f"Saved changes for {name}.")
    return redirect("dashboard")
