from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from .forms import StudentInitForm, MessageForm
from .services import initialize_student, send_user_message

SESSION_HISTORY_KEY = "chat_history"
SESSION_INIT_DONE = "chat_init_done"

def _get_history(request):
    return request.session.get(SESSION_HISTORY_KEY, [])

def _save_history(request, history):
    request.session[SESSION_HISTORY_KEY] = history
    request.session.modified = True

@require_http_methods(["GET", "POST"])
def init_view(request):
    form = StudentInitForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        history = _get_history(request)
        init_text, updated = initialize_student(
            history,
            form.cleaned_data["studentName"],
            form.cleaned_data["studentSchool"],
            form.cleaned_data["studentGrade"],
            form.cleaned_data["studentClasses"],
        )
        _save_history(request, updated)
        request.session[SESSION_INIT_DONE] = True
        return redirect("chat")
    return render(request, "tutor/init.html", {"form": form})

@require_http_methods(["GET", "POST"])
def chat_view(request):
    if not request.session.get(SESSION_INIT_DONE, False):
        return redirect("init")

    history = _get_history(request)
    form = MessageForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        model_text, updated = send_user_message(history, form.cleaned_data["message"])
        _save_history(request, updated)
        return redirect("chat")

    return render(request, "tutor/chat.html", {"form": form, "messages": history})

def index(request):
    return redirect("chat")
