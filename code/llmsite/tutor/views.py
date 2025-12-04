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
from httpx import request
from .models import Session, Chat as DBChat
from .utils import is_teacher_or_admin, is_admin
from .models import TeacherProfile, AdminProfile, StudentProfile
from tutor.globals import GetModelAndTokenizer

# in-memory registry for prototype use
CHAT_REGISTRY = {}

model, tokenizer = GetModelAndTokenizer()

def _session_id(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key

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
    """Create a new Session for the authenticated user and return its metadata."""
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    title = (data.get("title") or "New session").strip() or "New session"
    session = Session.objects.create(owner=request.user, title=title)

    # store the session id in the user's django session to aid backwards compatibility
    request.session["session_id"] = str(session.id)

    return JsonResponse({
        "ok": True,
        "id": str(session.id),
        "title": session.title,
        "createdAt": session.created_at.isoformat(),
    })

@csrf_exempt
@require_http_methods(["POST"])
def api_init(request):
    #try:
        #data = json.loads(request.body.decode("utf-8"))
    #except Exception:
        #return HttpResponseBadRequest("Invalid JSON")

    name   = "John Doe" #(data.get("studentName") or "").strip()
    school = "George Washington High School" #(data.get("studentSchool") or "").strip()
    grade  = "Sophomore" #(data.get("studentGrade") or "").strip()
    classes = "Algebra 2, History, AP Language/Composition" #(data.get("studentClasses") or "").strip()

    # Initialize the chat.
    # TODO: Retreive chats and RAG from database.
    chat, messages = StartChat(model, tokenizer, name, school, grade, classes)

    # store the live chat object for this user session
    sid = _session_id(request)
    CHAT_REGISTRY[sid] = messages

    model_reply = chat.split("<|assistant|>")[-1].strip()

    return JsonResponse({"ok": True, "model_text": model_reply})

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

    # call SendMessage on the stored chat
    reply, messages = SendMessage(model, tokenizer, chat, msg)

    CHAT_REGISTRY[sid] = messages
    model_reply = reply.split("<|assistant|>")[-1].strip()
    
    return JsonResponse({"ok": True, "model_text": model_reply})

@csrf_exempt
@require_http_methods(["POST"])
def api_reset(request):
    sid = _session_id(request)
    CHAT_REGISTRY.pop(sid, None)
    return JsonResponse({"ok": True})

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

    chats = DBChat.objects.filter(session=session)
    messages = [{"role": c.role, "text": c.message} for c in chats]

    return JsonResponse({"ok": True, "messages": messages})

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