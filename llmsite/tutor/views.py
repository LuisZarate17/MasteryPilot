#import profile
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import login, get_user_model
from django.shortcuts import render, redirect
from .forms import SignupForm
import json

from httpx import request
from languagemodel import StartAIChat, Initialization, SendMessage
from .models import Session, Chat as DBChat
from .utils import is_teacher_or_admin, is_admin
from .models import TeacherProfile, AdminProfile, StudentProfile

# in-memory registry for prototype use
CHAT_REGISTRY = {}

def _session_id(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key

def chat_page(request):
    return render(request, "chat.html")

@login_required
@user_passes_test(is_teacher_or_admin)
def dashboard_page(request):
    teachers = TeacherProfile.objects.select_related("user").all()
    admins = AdminProfile.objects.select_related("user").all()
    students = StudentProfile.objects.select_related("user").all()

    context = {
        "teachers": teachers,
        "admins": admins,
        "students": students,
    }

    return render(request, "dashboard_admin_mentor.html", context)

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
    return JsonResponse({"ok": True, "model_text": reply})

@csrf_exempt
@require_http_methods(["POST"])
def api_reset(request):
    sid = _session_id(request)
    CHAT_REGISTRY.pop(sid, None)
    return JsonResponse({"ok": True})
