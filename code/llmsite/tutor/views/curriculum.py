"""Curriculum library files and chat transcript export."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils._os import safe_join
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_GET, require_http_methods
import csv
import json
import os
import re

from ..models import Chat as DBChat, Session, StudentProfile, TeacherProfile
from ..utils import is_admin, is_teacher_or_admin


ALLOWED_UPLOAD_TYPES = {
    "txt": "text/plain",
    "pdf": "application/pdf",
}


MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB


def _invalidate_rag_index():
    """Tell the retrieval index the curriculum changed.

    Imported here rather than at module scope: rag is import-safe, but this
    keeps the dependency visible at the two call sites that create it.

    Without this, a document deleted through the dashboard went on being
    retrieved and quoted to students. The index re-checks the corpus when a
    chat session opens, so this is not the only thing standing between a
    deletion and its taking effect — but it is what makes the two explicitly
    connected rather than accidentally so.
    """
    try:
        import rag

        rag.invalidate()
    except Exception as exc:  # pragma: no cover - never block the upload
        # The RAG stack is optional; the dashboard must work without it.
        print(f"[curriculum] could not invalidate the RAG index: {exc}")


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
        _invalidate_rag_index()

    return redirect("dashboard")


@login_required
@user_passes_test(is_teacher_or_admin)
@require_http_methods(["POST"])
def upload_curriculum(request):
    title = (request.POST.get("title") or "").strip()
    file = request.FILES.get("file")

    if not file:
        return redirect("dashboard")

    if file.size > MAX_UPLOAD_SIZE:
        return redirect("dashboard")

    filename = get_valid_filename(file.name)

    # Validate extension: use os.path.splitext to prevent double-extension bypass
    _, dot_ext = os.path.splitext(filename)
    ext = dot_ext.lstrip(".").lower()

    if ext not in ALLOWED_UPLOAD_TYPES:
        return redirect("dashboard")

    # Verify MIME type matches expected content type
    if file.content_type != ALLOWED_UPLOAD_TYPES[ext]:
        return redirect("dashboard")

    os.makedirs(settings.CURRICULUM_ROOT, exist_ok=True)

    safe_name = os.path.basename(filename)
    destination = os.path.realpath(os.path.join(settings.CURRICULUM_ROOT, safe_name))

    if not destination.startswith(os.path.realpath(str(settings.CURRICULUM_ROOT))):
        return redirect("dashboard")

    with open(destination, "wb+") as dest:
        for chunk in file.chunks():
            dest.write(chunk)

    _invalidate_rag_index()

    return redirect("dashboard")


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
    chats = (
        DBChat.objects
        .filter(session_id__in=session_ids)
        .select_related("session")
        .order_by("session__created_at", "created_at", "id")
    )

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
                target_user.username,
                student_name,
                str(chat.session_id),
                chat.session.title,
                chat.session.created_at.isoformat(),
                chat.created_at.isoformat(),
                chat.role,
                chat.message,
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
