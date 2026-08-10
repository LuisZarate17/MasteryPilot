"""Signup, the staff dashboard, and account administration."""

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
import os

from ..forms import SignupForm
from ..models import AdminProfile, StudentProfile, StudentProgress, TeacherProfile
from ..utils import is_admin, is_teacher_or_admin


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

        if progress.quiz_average < 0.7:
            if progress.quiz_average < 0.5:
                intervention_list.append((student, 1))
                intervention_alert = True
            else:
                intervention_list.append((student, 0))
                

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
        return redirect("dashboard")
    
    if User.objects.filter(username=username).exists():
        return redirect("dashboard")

    _, first_name, last_name = _split_full_name(full_name)
    
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
    elif role == "student":
        StudentProfile.objects.create(
            user=user,
            display_name=display_name,
            grade=grade,
            classes=classes,
        )
    else:
        user.delete()

    return redirect("dashboard")


@require_http_methods(["POST"])
@login_required
@user_passes_test(is_admin)
def account_password_edit(request):
    user_id_raw = request.POST.get("user_id")
    pw = request.POST.get("password")
    pwc = request.POST.get("password_confirm")


    if pw == pwc:
        
        # Guard against missing or non numeric student id
        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError):
            return redirect("dashboard")


        User = get_user_model()


        try:
            user = User.objects.get(id=user_id)
            user.set_password(pw)
            user.save()

        except User.DoesNotExist:
            pass
        
    return redirect("dashboard")


@require_http_methods(["POST"])
@login_required
@user_passes_test(is_admin)
def account_delete(request):
    User = get_user_model()

    user_id = request.POST.get("user_id")
    role = (request.POST.get("role") or "").strip()

    if not user_id:
        return redirect("dashboard")

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return redirect("dashboard")

    # Do not let an admin delete themselves
    if user == request.user:
        return redirect("dashboard")

    user.delete()

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
    if pw == pwc:
        student.user.set_password(pw)
    student.save()
    student.user.save()

    return redirect("dashboard")
