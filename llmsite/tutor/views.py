#import profile
from django.http import FileResponse, Http404, HttpResponseRedirect, JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import login, get_user_model
from django.shortcuts import render, redirect
from django.conf import settings
from django.utils.text import get_valid_filename
from .forms import SignupForm, UploadRagForm
import json
import os

from httpx import request
from languagemodel import StartAIChat, Initialization, SendMessage
from .models import Session, Chat as DBChat, StudentProgress
from .utils import is_teacher_or_admin, is_admin, calculate_student_progress
from .models import TeacherProfile, AdminProfile, StudentProfile

# in-memory registry for prototype use
CHAT_REGISTRY = {}

def _session_id(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key

@login_required
def landing_page(request):
    """
    Authenticated landing page for students.
    Shows welcome message, progress summary widget, and CTAs.
    Teachers/admins are redirected to dashboard.
    """
    if is_teacher_or_admin(request.user):
        return redirect("dashboard")
    
    # Get or calculate progress for the current user
    try:
        progress = StudentProgress.objects.get(user=request.user)
    except StudentProgress.DoesNotExist:
        # First time user - calculate initial progress
        calculate_student_progress(request.user)
        progress = StudentProgress.objects.get(user=request.user)
    
    context = {
        'progress': progress,
        'has_activity': progress.total_sessions > 0 or progress.total_quizzes > 0,
    }
    
    return render(request, "landing.html", context)

def chat_page(request):
    if is_teacher_or_admin(request.user):
        return redirect("dashboard")
    return render(request, "chat.html")

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

    context = {
        "teachers": teachers,
        "admins": admins,
        "students": students,
        "curriculum_files": files,
        "is_admin": is_admin_flag,
        "is_teacher": is_teacher_flag,
    }

    return render(request, "dashboard_admin_mentor.html", context)

@login_required
@user_passes_test(is_teacher_or_admin)
def curriculum_view(request, filename):
    path = os.path.join(settings.CURRICULUM_ROOT, filename)

    if not os.path.exists(path):
        raise Http404("File not found")

    return FileResponse(open(path, "rb"), as_attachment=False)

@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def curriculum_delete(request):
    filename = request.POST.get("filename") or ""

    path = os.path.join(settings.CURRICULUM_ROOT, filename)

    if os.path.exists(path):
        os.remove(path)

    return redirect("dashboard")

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

@require_http_methods(["POST"])
@login_required
@user_passes_test(is_admin)
def account_create(request):
    User = get_user_model()

    role = (request.POST.get("role") or "").strip()
    username = (request.POST.get("username") or "").strip()
    email = (request.POST.get("email") or "").strip()
    password = request.POST.get("password") or ""

    grade = (request.POST.get("grade") or "").strip()
    classes = (request.POST.get("classes") or "").strip()

    if not role or not username or not password:
        return redirect("dashboard")
    
    if User.objects.filter(username=username).exists():
        return redirect("dashboard")
    
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
    )

    if role == "teacher":
        TeacherProfile.objects.create(user=user)
    elif role == "admin":
        AdminProfile.objects.create(user=user)
    elif role == "student":
        StudentProfile.objects.create(
            user=user,
            grade=grade,
            classes=classes,
        )
    else:
        user.delete()

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
    student.save()

    return redirect("dashboard")

@csrf_exempt
@require_http_methods(["POST"])
@login_required
def api_new_session(request):
    """Create a new Session for the authenticated user and return its metadata."""
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    title = (data.get("title") or "New session").strip() or "New session"
    session = Session.objects.create(owner=request.user, title=title)

    # Refresh progress on new session creation
    try:
        calculate_student_progress(request.user)
    except Exception as e:
        # Don't fail session creation if progress calc fails
        print(f"Progress calculation error: {e}")

    return JsonResponse({
        "ok": True,
        "id": str(session.id),
        "title": session.title,
        "createdAt": session.created_at.isoformat(),
    })

@csrf_exempt
@require_http_methods(["POST"])
def api_init(request):
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "authentication required"}, status=401)
    #try:
        #data = json.loads(request.body.decode("utf-6"))
    #except Exception:
        #return HttpResponseBadRequest("Invalid JSON")

    #name   = "John Doe" #(data.get("studentName") or "").strip()
    #school = "George Washington High School" #(data.get("studentSchool") or "").strip()
    #grade  = "Sophomore" #(data.get("studentGrade") or "").strip()
    #classes = "Algebra 2, History, AP Language/Composition" #(data.get("studentClasses") or "").strip()
    try:
        profile = request.user.studentprofile
        name = profile.user.get_full_name() or profile.user.username
        school = profile.school
        grade = profile.grade
        classes = profile.classes
    except Exception:
        name = request.user.get_full_name() or request.user.username
        school = ""
        grade = ""
        classes = ""


    # start a fresh chat
    chat = StartAIChat()
    # call Initialization
    init_text = Initialization(chat, name, school, grade, classes) or ""

    # store the live chat object for this user session
    sid = _session_id(request)
    CHAT_REGISTRY[sid] = chat

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    name = (data.get("studentName") or request.user.get_full_name() or request.user.username).strip()
    school = (data.get("studentSchool") or "").strip()
    grade = (data.get("studentGrade") or "").strip()
    classes = (data.get("studentClasses") or "").strip()

    # determine target session id (optional)
    session_id = data.get("session_id")
    session = None
    if session_id:
        try:
            session = Session.objects.get(id=session_id, owner=request.user)
        except Session.DoesNotExist:
            return HttpResponseBadRequest("session not found or not owned by user")

    # if no session provided, create a new one
    if session is None:
        session = Session.objects.create(owner=request.user)
        request.session["session_id"] = str(session.id)
    else:
        request.session["session_id"] = str(session.id)

    # start a fresh LLM chat and initialize
    llm_chat = StartAIChat()
    init_text = Initialization(llm_chat, name, school, grade, classes) or ""

    # persist initial assistant message if DBChat model available
    try:
        DBChat.objects.create(session=session, role="assistant", message=init_text)
    except Exception:
        pass

    # store the live chat object in-memory keyed by session id
    CHAT_REGISTRY[str(session.id)] = llm_chat

    return JsonResponse({"ok": True, "model_text": init_text, "session_id": str(session.id)})

@csrf_exempt
@require_http_methods(["POST"])
def api_chat(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    msg = (data.get("message") or "").strip()
    if not msg:
        return HttpResponseBadRequest("message is required")

    # The initialization endpoint stores the live chat in CHAT_REGISTRY
    # keyed by the created Session DB id (stored in request.session['session_id']).
    # Use that stored session id to look up the live chat. Fall back to the
    # Django session key for backward compatibility.
    sid = request.session.get("session_id") or _session_id(request)
    # ensure string key form matches how we store it in api_init
    sid = str(sid)
    chat = CHAT_REGISTRY.get(sid)
    if chat is None:
        return HttpResponseBadRequest("No active chat, initialize first")

    # call SendMessage on the stored chat
    reply = SendMessage(chat, msg) or ""
    
    # Try to persist the user message and assistant reply to database
    try:
        session_id = request.session.get("session_id")
        if session_id:
            session = Session.objects.get(id=session_id, owner=request.user)
            DBChat.objects.create(session=session, role="user", message=msg)
            DBChat.objects.create(session=session, role="assistant", message=reply)
            
            # Refresh progress periodically (every 5th message to reduce overhead)
            user_message_count = DBChat.objects.filter(session=session, role="user").count()
            if user_message_count % 5 == 0:
                calculate_student_progress(request.user)
    except Exception as e:
        # Don't fail chat if persistence fails
        print(f"Chat persistence or progress calc error: {e}")
    
    return JsonResponse({"ok": True, "model_text": reply})

@csrf_exempt
@require_http_methods(["POST"])
def api_reset(request):
    sid = _session_id(request)
    CHAT_REGISTRY.pop(sid, None)
    return JsonResponse({"ok": True})


@login_required
@require_http_methods(["GET"])
def progress_summary(request):
    """
    API endpoint to fetch student progress summary.
    Returns: overall completion %, current module, last activity, streak, and next step.
    """
    user = request.user
    
    # Recalculate progress for current user
    metrics = calculate_student_progress(user)
    
    # Determine next recommended step
    next_step = ""
    if metrics['total_sessions'] == 0:
        next_step = "Start your first chat session"
    elif metrics['total_quizzes'] == 0:
        next_step = "Complete your first quiz"
    elif metrics['quiz_average'] and metrics['quiz_average'] < 70:
        next_step = "Review topics and improve quiz scores"
    else:
        next_step = "Continue learning with new topics"
    
    return JsonResponse({
        'ok': True,
        'overall_completion_percent': metrics['overall_completion_percent'],
        'current_module': metrics['current_module'],
        'last_activity': metrics['last_activity'],
        'activity_streak': metrics['activity_streak'],
        'next_step': next_step,
        'total_sessions': metrics['total_sessions'],
        'total_quizzes': metrics['total_quizzes'],
        'total_messages': metrics['total_messages'],
        'quiz_average': metrics['quiz_average'],
    })


@login_required
def progress_detail(request):
    """
    Full progress dashboard with charts, history, and detailed metrics.
    For students viewing their own progress or teachers viewing student progress.
    """
    # Check if viewing as teacher/admin with student_id parameter
    student_id = request.GET.get('student_id')
    
    if student_id and is_teacher_or_admin(request.user):
        # Teachers/admins can view student progress
        try:
            User = get_user_model()
            student_user = User.objects.get(id=student_id)
            
            # Verify teacher has access to this student
            if not is_admin(request.user):
                teacher_profile = TeacherProfile.objects.get(user=request.user)
                student_profile = StudentProfile.objects.get(user=student_user)
                if student_profile.teacher != teacher_profile:
                    return JsonResponse({'error': 'Access denied'}, status=403)
            
            target_user = student_user
        except (User.DoesNotExist, TeacherProfile.DoesNotExist, StudentProfile.DoesNotExist):
            return JsonResponse({'error': 'Student not found'}, status=404)
    else:
        # Students view their own progress
        target_user = request.user
    
    # Recalculate progress
    metrics = calculate_student_progress(target_user)
    
    # Get progress record for historical data
    try:
        progress = StudentProgress.objects.get(user=target_user)
    except StudentProgress.DoesNotExist:
        progress = None
    
    # Get session history with quiz data
    sessions = Session.objects.filter(owner=target_user).order_by('-created_at')[:20]
    session_history = []
    
    for session in sessions:
        quizzes = session.quizzes.filter(status='graded')
        quiz_count = quizzes.count()
        
        # Calculate session quiz average
        session_quiz_avg = None
        if quiz_count > 0:
            quiz_scores = []
            for quiz in quizzes:
                quiz_answer = quiz.answers.first()
                if quiz_answer and quiz_answer.graded_json:
                    correct = sum(1 for item in quiz_answer.graded_json.values() 
                                if isinstance(item, dict) and item.get('isCorrect'))
                    total = len(quiz_answer.graded_json)
                    if total > 0:
                        quiz_scores.append((correct / total) * 100)
            
            if quiz_scores:
                session_quiz_avg = sum(quiz_scores) / len(quiz_scores)
        
        session_history.append({
            'id': str(session.id),
            'title': session.title,
            'created_at': session.created_at.isoformat(),
            'quiz_count': quiz_count,
            'quiz_average': round(session_quiz_avg, 2) if session_quiz_avg else None,
        })
    
    context = {
        'target_user': target_user,
        'metrics': metrics,
        'progress': progress,
        'session_history': session_history,
        'is_viewing_other': student_id is not None,
    }
    
    return render(request, 'progress_detail.html', context)


@login_required
@user_passes_test(is_teacher_or_admin)
@require_http_methods(["POST"])
def upload_curriculum(request):
    title = (request.POST.get("title") or "").strip()
    file = request.FILES.get("file")

    if not file:
        return redirect("dashboard")

    filename = get_valid_filename(file.name)
    ext = filename.lower().split(".")[-1]

    if ext not in {"txt", "pdf"}:
        return redirect("dashboard")

    os.makedirs(settings.CURRICULUM_ROOT, exist_ok=True)

    destination = os.path.join(settings.CURRICULUM_ROOT, filename)

    with open(destination, "wb+") as dest:
        for chunk in file.chunks():
            dest.write(chunk)

    return redirect("dashboard")
    