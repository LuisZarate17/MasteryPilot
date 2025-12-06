# code/llmsite/tutor/views.py
from django.http import FileResponse, Http404, HttpResponseRedirect, JsonResponse, HttpResponseBadRequest
from django.contrib.auth.models import AnonymousUser
from django.shortcuts import render
from django.views.decorators.http import require_http_methods, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import login, get_user_model
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.utils.text import get_valid_filename
from .forms import SignupForm, UploadRagForm
import json
import os

from languagemodel import InitModel, StartChat, SendMessage
from languagemodel_legacy import *
from httpx import request
from .models import Session, Chat as DBChat, StudentProgress
from .utils import is_teacher_or_admin, is_admin, calculate_student_progress
from .models import TeacherProfile, AdminProfile, StudentProfile
from tutor.globals import GetModelAndTokenizer

# in-memory registry for prototype use
CHAT_REGISTRY = {}

model = None
tokenizer = None
gemini = None

def ensure_llm_initialized():
    """
    Ensure that either local model/tokenizer or Gemini client is initialized.
    Safe to call multiple times.
    """
    global model, tokenizer, gemini
    if settings.GEMINI_ENABLED:
        if gemini is None:
            try:
                # StartAIChat should be available via languagemodel_legacy import
                gemini = StartAIChat()
            except Exception as e:
                print(f"[ensure_llm_initialized] Failed to start Gemini: {e}")
                gemini = None
    else:
        if model is None or tokenizer is None:
            try:
                # Prefer the already-loaded globals (if apps.py set them)
                model, tokenizer = GetModelAndTokenizer()
            except Exception:
                # Fall back to InitModel if GetModelAndTokenizer isn't ready
                try:
                    model, tokenizer = InitModel()
                    # If you want the globals module to know about them:
                    try:
                        import tutor.globals as tglobals
                        tglobals.loaded_model = model
                        tglobals.loaded_tokenizer = tokenizer
                    except Exception:
                        pass
                except Exception as e:
                    print(f"[ensure_llm_initialized] Failed to init local model: {e}")
                    model = tokenizer = None


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

@login_required(login_url="login")
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
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    title = (data.get("title") or "New session").strip() or "New session"

    # Create DB session (we keep the session record)
    session = Session.objects.create(owner=request.user, title=title)
    request.session['session_id'] = str(session.id)

    # Student info
    name   = request.user.get_full_name() or request.user.username
    school = "George Washington High School"
    grade  = "Sophomore"
    classes = "Algebra 2, History, AP Language/Composition"

    # Ensure LLM/Gemini is initialized
    ensure_llm_initialized()

    global gemini
    messages = []
    assistant_msg = "Hello!"  # fallback

    if settings.GEMINI_ENABLED:
        # Gemini path: call but DON'T persist error messages into DB/history
        try:
            if gemini is None:
                gemini = StartAIChat()
            initial_msg = Initialization(gemini, name, school, grade, classes) if gemini else None
            if initial_msg:
                messages = [{"role": "assistant", "content": initial_msg}]
                assistant_msg = initial_msg
        except Exception as e:
            # Log but do NOT append an assistant error entry into messages/db.
            print(f"[api_new_session] Gemini initialization error: {e}")
            # keep messages empty so nothing is persisted
            messages = []
            assistant_msg = "Model unavailable. Please try again later."
    else:
        # Local LLM path
        if model is None or tokenizer is None:
            messages = []
            assistant_msg = "Model unavailable. Please try again later."
        else:
            try:
                chat, messages = StartChat(model, tokenizer, name, school, grade, classes)
                assistant_msg = next((m.get("content") for m in messages if m.get("role") == "assistant"), assistant_msg)
            except Exception as e:
                print(f"[api_new_session] StartChat error: {e}")
                messages = []
                assistant_msg = "Model error. Please try again later."

    # store in-memory registry (keep consistent format)
    sid = _session_id(request)
    CHAT_REGISTRY[sid] = messages

    # persist messages to DB **only if there are real messages** (i.e. no init-error placeholders)
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if content:
            DBChat.objects.create(session=session, role=role, message=content)

    # Return assistant_msg (whether real or generic fallback)
    try:
        calculate_student_progress(request.user)
    except Exception as e:
        print(f"Progress calculation error: {e}")

    return JsonResponse({
        "ok": True,
        "id": str(session.id),
        "title": session.title,
        "createdAt": session.created_at.isoformat(),
        "model_text": assistant_msg
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_init(request):
    name   = "John Doe"
    school = "George Washington High School"
    grade  = "Sophomore"
    classes = "Algebra 2, History, AP Language/Composition"

    # Ensure LLM/Gemini is initialized
    ensure_llm_initialized()
    sid = _session_id(request)

    global gemini
    messages = []
    assistant_msg = "Hello!"

    if not settings.GEMINI_ENABLED:
        if model is None or tokenizer is None:
            messages = []
            assistant_msg = "Model unavailable. Please try again later."
        else:
            try:
                chat, messages = StartChat(model, tokenizer, name, school, grade, classes)
                assistant_msg = next((m.get("content") for m in messages if m.get("role") == "assistant"), assistant_msg)
            except Exception as e:
                print(f"[api_init] StartChat error: {e}")
                messages = []
                assistant_msg = "Model error. Please try again later."

        # store the live chat object (only real messages)
        CHAT_REGISTRY[sid] = messages
        return JsonResponse({"ok": True, "model_text": assistant_msg})
    else:
        try:
            if gemini is None:
                gemini = StartAIChat()
            response = Initialization(gemini, name, school, grade, classes) if gemini else None
            if response:
                CHAT_REGISTRY[sid] = [{"role": "assistant", "content": response}]
                assistant_msg = response
            else:
                CHAT_REGISTRY[sid] = []
                assistant_msg = "Model unavailable. Please try again later."
        except Exception as e:
            print(f"[api_init] Gemini initialization error: {e}")
            CHAT_REGISTRY[sid] = []
            assistant_msg = "Model error. Please try again later."

        return JsonResponse({"ok": True, "model_text": assistant_msg})


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

    sid = _session_id(request)
    chat = CHAT_REGISTRY.get(sid)
    if chat is None:
        return HttpResponseBadRequest("No active chat, initialize first")

    # Ensure LLM/Gemini ready
    ensure_llm_initialized()

    assistant_reply_text = None
    error_occurred = False

    global gemini
    if not settings.GEMINI_ENABLED:
        # local model path
        if model is None or tokenizer is None:
            assistant_reply_text = "Model unavailable. Please try again later."
            error_occurred = True
        else:
            try:
                reply, messages = SendMessage(model, tokenizer, chat, msg)
                # Update registry with the messages returned by SendMessage (these are real model outputs)
                CHAT_REGISTRY[sid] = messages
                # Extract assistant reply text
                assistant_reply_text = reply.split("<|assistant|>")[-1].strip() if isinstance(reply, str) else None
                if not assistant_reply_text and messages:
                    assistant_reply_text = next((m.get("content") for m in messages if m.get("role") == "assistant"), "")
            except Exception as e:
                print(f"[api_chat] Local SendMessage error: {e}")
                assistant_reply_text = "Model error, please try again later."
                error_occurred = True
    else:
        # Gemini path
        try:
            if gemini is None:
                try:
                    gemini = StartAIChat()
                except Exception:
                    gemini = None
            if gemini:
                # assume SendMessage(gemini, msg) returns a text assistant reply (legacy helper)
                assistant_reply_text = SendMessage(gemini, msg)
            else:
                assistant_reply_text = "Model unavailable. Please try again later."
                error_occurred = True
        except Exception as e:
            print(f"[api_chat] Gemini SendMessage error: {e}")
            assistant_reply_text = "Model error, please try again later."
            error_occurred = True

        # Only append user + assistant to in-memory registry if the assistant reply is a normal text (no init error)
        existing = CHAT_REGISTRY.get(sid)
        if not isinstance(existing, list):
            existing = []
        existing.append({"role": "user", "content": msg})
        if not error_occurred:
            existing.append({"role": "assistant", "content": assistant_reply_text})
        CHAT_REGISTRY[sid] = existing

    # Persist to DB: only persist user + assistant when there was no model error.
    try:
        session_id = request.session.get("session_id")
        if session_id:
            session = Session.objects.get(id=session_id, owner=request.user)
            # Always persist the user message
            DBChat.objects.create(session=session, role="user", message=msg)
            # Persist assistant message only when model returned a real reply (no error)
            if not error_occurred and assistant_reply_text:
                DBChat.objects.create(session=session, role="assistant", message=assistant_reply_text)

            # Refresh progress periodically (every 5th user message)
            user_message_count = DBChat.objects.filter(session=session, role="user").count()
            if user_message_count % 5 == 0:
                calculate_student_progress(request.user)
    except Exception as e:
        print(f"Chat persistence or progress calc error: {e}")

    # If error_occurred, include an 'error' flag so frontend can show it without inserting into history.
    if error_occurred:
        return JsonResponse({"ok": True, "model_text": assistant_reply_text, "error": True})
    else:
        return JsonResponse({"ok": True, "model_text": assistant_reply_text})


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

@login_required
def api_list_sessions(request):
    """Return all sessions for the current user."""
    sessions = Session.objects.filter(owner=request.user).order_by("-created_at")
    data = [
        {"id": str(s.id), "title": s.title, "created_at": s.created_at.isoformat()}
        for s in sessions
    ]
    return JsonResponse({"sessions": data})


@login_required
@require_GET
def api_session_messages(request, session_id):
    try:
        session = Session.objects.get(id=session_id, owner=request.user)
    except Session.DoesNotExist:
        return HttpResponseBadRequest("Session not found or not owned by user")

    chats = DBChat.objects.filter(session=session).order_by("id")  # keep chronological order
    messages = [{"role": c.role, "text": c.message} for c in chats]

    # Also populate in-memory chat registry in the format the LLM functions expect:
    llm_messages = []
    for c in chats:
        # DB stores role and message text; ensure keys are 'role' and 'content'
        llm_messages.append({"role": c.role, "content": c.message})

    sid = _session_id(request)
    CHAT_REGISTRY[sid] = llm_messages

    # set the active session for subsequent api_chat persistence
    request.session['session_id'] = str(session.id)

    return JsonResponse({"ok": True, "messages": messages})

@csrf_exempt
@require_http_methods(["POST"])
@login_required
def api_session_init(request, session_id):
    """
    Initialize an existing session (StartChat + persist first messages).
    Use this when the session exists but has no messages yet.
    """
    try:
        session = Session.objects.get(id=session_id, owner=request.user)
    except Session.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Session not found"}, status=404)

    # Start LLM chat and persist initial messages
    name = request.user.get_full_name() or request.user.username
    school = "George Washington High School"
    grade = "Sophomore"
    classes = "Algebra 2, History, AP Language/Composition"

    try:
        chat, messages = StartChat(model, tokenizer, name, school, grade, classes)
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"LLM init error: {e}"}, status=500)

    # store in-memory
    sid = _session_id(request)
    CHAT_REGISTRY[sid] = messages

    # persist messages to DB
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if content:
            DBChat.objects.create(session=session, role=role, message=content)

    # set server session pointer
    request.session['session_id'] = str(session.id)

    # return assistant first message
    assistant_msg = next((m.get("content") for m in messages if m.get("role") == "assistant"), None)
    return JsonResponse({"ok": True, "model_text": assistant_msg or "Hello!"})

@csrf_exempt
@require_http_methods(["DELETE"])
@login_required
def api_delete_session(request, session_id):
    session = get_object_or_404(Session, id=session_id, owner=request.user)
    # remove in-memory chat if present
    CHAT_REGISTRY.pop(str(session_id), None)
    session.delete()
    return JsonResponse({"ok": True, "status": "deleted"})


@csrf_exempt
@require_http_methods(["POST"])
@login_required
def api_rename_session(request, session_id):
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")
    new_title = (data.get("title") or "").strip()
    if not new_title:
        return HttpResponseBadRequest("title is required")
    session = get_object_or_404(Session, id=session_id, owner=request.user)
    session.title = new_title
    session.save(update_fields=["title"])
    return JsonResponse({"ok": True, "id": str(session.id), "title": session.title})


@csrf_exempt
@require_http_methods(["POST"])
@login_required
def api_select_session(request, session_id):
    """
    Select an existing DB session. Sets request.session['session_id'] and
    rebuilds CHAT_REGISTRY for this user session from DB messages so
    subsequent api_chat works and persists messages correctly.
    """
    try:
        session = Session.objects.get(id=session_id, owner=request.user)
    except Session.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Session not found"}, status=404)

    # set server-side session id so api_chat knows which DB session to attach to
    request.session['session_id'] = str(session.id)

    # rebuild messages list for in-memory chat registry
    chats = DBChat.objects.filter(session=session).order_by('id')
    messages = []
    for c in chats:
        messages.append({"role": c.role, "content": c.message})

    sid = _session_id(request)
    CHAT_REGISTRY[sid] = messages

    return JsonResponse({"ok": True})







