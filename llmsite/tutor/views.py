from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
import json
from languagemodel import StartAIChat, Initialization, SendMessage

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
def api_init(request):
    #try:
        #data = json.loads(request.body.decode("utf-8"))
    #except Exception:
        #return HttpResponseBadRequest("Invalid JSON")

    name   = "John Doe" #(data.get("studentName") or "").strip()
    school = "George Washington High School" #(data.get("studentSchool") or "").strip()
    grade  = "Sophomore" #(data.get("studentGrade") or "").strip()
    classes = "Algebra 2, History, AP Language/Composition" #(data.get("studentClasses") or "").strip()

    # start a fresh chat
    chat = StartAIChat()
    # call Initialization
    init_text = Initialization(chat, name, school, grade, classes) or ""

    # store the live chat object for this user session
    sid = _session_id(request)
    CHAT_REGISTRY[sid] = chat

    return JsonResponse({"ok": True, "model_text": init_text})

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
