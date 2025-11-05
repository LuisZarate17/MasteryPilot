from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
import json
from languagemodel import StartAIChat, Initialization, SendMessage
from .models import Session, Chat as DBChat

# in-memory registry for prototype use
CHAT_REGISTRY = {}

def _session_id(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key

def chat_page(request):
    return render(request, "chat.html")


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

    sid = _session_id(request)
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
