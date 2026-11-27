"""Curriculum library files and chat transcript export."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils._os import safe_join
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_GET, require_http_methods
import csv
import json
import logging
import os
import re

from ..models import Chat as DBChat, Session, StudentProfile, TeacherProfile
from ..utils import is_admin, is_teacher_or_admin
from .chat import _visible_chats

logger = logging.getLogger(__name__)


# Extension -> content types a browser might plausibly send for it.
#
# The extension is the real control: it decides which extractor rag.py runs,
# and these files are only ever read as text, never executed. The content type
# is client-supplied and trivially forged, so it is a guard against an obvious
# mistake — uploading a spreadsheet named .txt — and not a security boundary.
# It is a set per extension because browsers disagree: Firefox sends
# application/octet-stream for .md, Chrome sends text/markdown or nothing at
# all, and a strict single-value match rejected all of them.
#
# rag.EXTRACTORS is the other half of this list. Anything indexable that is
# missing here can only reach the corpus by someone copying it onto the server
# by hand, which is how md, docx and json sat unreachable through the UI while
# being fully supported and tested underneath.
ALLOWED_UPLOAD_TYPES = {
    "txt": {"text/plain", "application/octet-stream", ""},
    "md": {"text/markdown", "text/x-markdown", "text/plain", "application/octet-stream", ""},
    "json": {"application/json", "text/json", "text/plain", "application/octet-stream", ""},
    "pdf": {"application/pdf", "application/x-pdf"},
    "docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    },
}


def _declared_type(uploaded):
    """Content type without parameters, lowercased. 'text/plain; charset=x' -> 'text/plain'."""
    return (uploaded.content_type or "").split(";")[0].strip().lower()


MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB


_INDEX_NOT_UPDATED = (
    "The tutor's search index could not be updated; it will be rebuilt when "
    "the next chat starts."
)


def _refresh_rag_index():
    """Rebuild the retrieval index after the curriculum changed.

    Returns True when the index now matches the folder and False when it could
    not be updated; it never raises, because the file change itself has
    already happened and must not be reported as a failure.

    The rebuild is slow (tens of seconds for the textbook), so it is done here,
    in the request of the staff member who changed the curriculum, rather than
    in the first student's "New session". Opening a session still re-checks the
    folder, which is what catches a server restart or a rebuild that failed
    here. invalidate() comes first so the rebuild cannot be skipped as current.

    Imported here rather than at module scope: rag is import-safe, but this
    keeps the dependency visible at the two call sites that create it.
    """
    try:
        import rag

        rag.invalidate()
        rag.ensure_curriculum_loaded(str(settings.CURRICULUM_ROOT))
    except Exception as exc:
        # The RAG stack is optional; the dashboard must work without it.
        logger.warning("Could not rebuild the RAG index: %s", exc)
        return False
    return True


@login_required
@user_passes_test(is_teacher_or_admin)
def curriculum_view(request, filename):
    try:
        path = safe_join(settings.CURRICULUM_ROOT, filename)
    except ValueError:
        raise Http404("Invalid file path")

    if not os.path.isfile(path):
        raise Http404("File not found")

    return FileResponse(open(path, "rb"), as_attachment=False)


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def curriculum_delete(request):
    filename = request.POST.get("filename") or ""
    safe_name = os.path.basename(filename)
    path = os.path.realpath(os.path.join(settings.CURRICULUM_ROOT, safe_name))

    if not path.startswith(os.path.realpath(str(settings.CURRICULUM_ROOT))):
        return redirect("dashboard")

    if os.path.exists(path):
        os.remove(path)
        if not _refresh_rag_index():
            messages.warning(request, _INDEX_NOT_UPDATED)

    return redirect("dashboard")


@login_required
@user_passes_test(is_teacher_or_admin)
@require_http_methods(["POST"])
def upload_curriculum(request):
    title = (request.POST.get("title") or "").strip()
    file = request.FILES.get("file")

    if not file:
        messages.error(request, "Choose a file to upload.")
        return redirect("dashboard")

    if file.size > MAX_UPLOAD_SIZE:
        messages.error(request, "That file is too large. The limit is 100 MB.")
        return redirect("dashboard")

    filename = get_valid_filename(file.name)

    # Validate extension: use os.path.splitext to prevent double-extension bypass
    _, dot_ext = os.path.splitext(filename)
    ext = dot_ext.lstrip(".").lower()

    if ext not in ALLOWED_UPLOAD_TYPES:
        messages.error(
            request,
            "Unsupported file type. Upload one of: "
            + ", ".join(f".{e}" for e in ALLOWED_UPLOAD_TYPES) + ".",
        )
        return redirect("dashboard")

    # Verify the declared content type is plausible for that extension
    if _declared_type(file) not in ALLOWED_UPLOAD_TYPES[ext]:
        messages.error(request, f"{filename} does not look like a .{ext} file.")
        return redirect("dashboard")

    os.makedirs(settings.CURRICULUM_ROOT, exist_ok=True)

    safe_name = os.path.basename(filename)
    destination = os.path.realpath(os.path.join(settings.CURRICULUM_ROOT, safe_name))

    if not destination.startswith(os.path.realpath(str(settings.CURRICULUM_ROOT))):
        messages.error(request, "That file name is not allowed.")
        return redirect("dashboard")

    # The library is shared, so a teacher must not silently overwrite a
    # document another teacher uploaded. Only an administrator replaces one.
    replacing = os.path.exists(destination)
    if replacing and not is_admin(request.user):
        messages.error(
            request,
            f"A file named {safe_name} already exists. Ask an administrator "
            "to replace it, or upload it under a different name.",
        )
        return redirect("dashboard")

    with open(destination, "wb+") as dest:
        for chunk in file.chunks():
            dest.write(chunk)

    index_updated = _refresh_rag_index()

    messages.success(
        request, f"Replaced {safe_name}." if replacing else f"Uploaded {safe_name}."
    )
    if not index_updated:
        messages.warning(request, _INDEX_NOT_UPDATED)
    return redirect("dashboard")


# A spreadsheet runs a cell that starts with one of these as a formula, and
# the message, title and names in an export are all written by students.
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value):
    """*value* with a leading ' if a spreadsheet would read it as a formula."""
    if isinstance(value, str) and value.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


@login_required
@user_passes_test(is_teacher_or_admin)
@require_GET
def api_export_chats(request):
    export_format = (request.GET.get("format") or "csv").strip().lower()
    if export_format not in {"csv", "json"}:
        return HttpResponseBadRequest("format must be csv or json")

    student_id_raw = request.GET.get("student_id")
    try:
        student_id = int(student_id_raw)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("student_id is required")

    User = get_user_model()
    try:
        target_user = User.objects.get(id=student_id)
    except User.DoesNotExist:
        return JsonResponse({"error": "Student not found"}, status=404)

    try:
        target_student = StudentProfile.objects.get(user=target_user)
    except StudentProfile.DoesNotExist:
        return JsonResponse({"error": "Student not found"}, status=404)

    # Admins can export any student.
    # Teachers can export only students assigned to them.
    if not is_admin(request.user):
        try:
            teacher_profile = TeacherProfile.objects.get(user=request.user)
        except TeacherProfile.DoesNotExist:
            return JsonResponse({"error": "Access denied"}, status=403)

        if target_student.teacher_id != teacher_profile.id:
            return JsonResponse({"error": "Access denied"}, status=403)

    sessions = list(
        Session.objects.filter(owner=target_user).order_by("created_at", "id")
    )
    session_ids = [s.id for s in sessions]
    # Export what the student and the tutor actually said, matching what
    # api_session_messages shows on screen.
    #
    # Two kinds of row are backend scaffolding rather than conversation. The
    # system prompt is stored once per session and is byte-identical every
    # time — a 330-message export of 64 sessions was 62% repetitions of the
    # same 2,608 characters — and it lives in source, so exporting it tells a
    # teacher nothing while making the file harder to read. The bootstrap turn
    # is persisted with role="user" so the model sees the conversation it had,
    # but the student never typed it. _visible_chats drops both, per session.
    chats_by_session = {}
    for chat in (
        DBChat.objects
        .filter(session_id__in=session_ids)
        .select_related("session")
        .order_by("session__created_at", "created_at", "id")
    ):
        chats_by_session.setdefault(chat.session_id, []).append(chat)
    chats = [
        chat
        for session_chats in chats_by_session.values()
        for chat in _visible_chats(session_chats)
    ]

    exported_at = timezone.now()
    exported_at_iso = exported_at.isoformat()
    timestamp = exported_at.strftime("%Y%m%d_%H%M%S")
    safe_username = re.sub(r"[^A-Za-z0-9_-]", "_", target_user.username)
    filename = f"chat_export_{safe_username}_{timestamp}.{export_format}"

    if export_format == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        writer = csv.writer(response)
        writer.writerow([
            "student_id",
            "student_username",
            "student_name",
            "session_id",
            "session_title",
            "session_created_at",
            "message_created_at",
            "role",
            "message",
        ])

        student_name = target_student.display_name or target_user.get_full_name() or target_user.username
        for chat in chats:
            writer.writerow([
                target_user.id,
                _csv_safe(target_user.username),
                _csv_safe(student_name),
                str(chat.session_id),
                _csv_safe(chat.session.title),
                chat.session.created_at.isoformat(),
                chat.created_at.isoformat(),
                chat.role,
                _csv_safe(chat.message),
            ])
        return response

    session_payload = {
        str(s.id): {
            "id": str(s.id),
            "title": s.title,
            "created_at": s.created_at.isoformat(),
            "messages": [],
        }
        for s in sessions
    }

    for chat in chats:
        session_payload[str(chat.session_id)]["messages"].append({
            "id": str(chat.id),
            "role": chat.role,
            "text": chat.message,
            "created_at": chat.created_at.isoformat(),
        })

    payload = {
        "exported_at": exported_at_iso,
        "student": {
            "id": target_user.id,
            "username": target_user.username,
            "name": target_student.display_name or target_user.get_full_name() or target_user.username,
            "email": target_user.email,
        },
        "sessions": list(session_payload.values()),
    }

    response = HttpResponse(
        json.dumps(payload, indent=2),
        content_type="application/json; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
