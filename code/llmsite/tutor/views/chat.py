"""Tutoring chat: LLM bootstrap, sessions, messages, and quizzes."""

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
import json
import logging
import random
import re

from ..models import Chat as DBChat, Quiz, QuizAnswer, Session
from ..models import StudentProfile, TeacherProfile
from ..utils import calculate_student_progress, is_admin, is_teacher_or_admin, parse_csv_answers

logger = logging.getLogger(__name__)


model = None


tokenizer = None


def _adapter():
    """The LLM adapter for settings.LLM_MODULE.

    Imported lazily: languagemodel pulls in transformers and torch, which are
    optional (requirements-llm.txt) and absent when running the test suite.
    """
    from languagemodel import get_adapter

    return get_adapter(settings.LLM_MODULE)


def _derive_session_title(first_message: str) -> str:
    try:
        return _adapter().derive_session_title(model, tokenizer, first_message)
    except Exception:
        logger.exception("Could not derive a session title")
        return ""


def ensure_llm_initialized():
    """Load the model and tokenizer if they are not loaded yet.

    Safe to call multiple times. Leaves both None on failure so callers can
    return "Model unavailable" rather than raising.
    """
    global model, tokenizer
    if model is None or tokenizer is None:
        try:
            model, tokenizer = _adapter().init_model()
        except Exception:
            logger.exception("Failed to initialise the local model")
            model = tokenizer = None


def _is_bootstrap_user_message(text: str) -> bool:
    """True for the student-information turn the backend sends on start_chat.

    It is stored with role="user" so the model sees the conversation it
    actually had, but the student never typed it, so it must not be shown in
    chat history and must not count as their first message.
    """
    if not text:
        return False
    stripped = text.lstrip()
    if stripped.startswith("Here is your student information"):
        return True
    # Bare "Name:/School:/Grade:" shape, written by adapters predating the
    # consolidation in languagemodel.py. Kept so upgraded deployments do not
    # start showing the bootstrap turn in old sessions.
    if stripped.startswith("Name:") and "School:" in stripped and "Grade:" in stripped:
        return True
    return False


def _has_student_message(session) -> bool:
    """True once the student has sent a message of their own."""
    return any(
        not _is_bootstrap_user_message(m)
        for m in DBChat.objects.filter(session=session, role="user").values_list(
            "message", flat=True
        )
    )


def _student_context(user):
    """The (name, school, grade, classes) the tutor persona is built from.

    Falls back to placeholders for users without a StudentProfile — staff
    accounts and the superuser can open a session too.
    """
    name = user.get_full_name() or user.username
    try:
        profile = user.studentprofile
        return name, profile.school, profile.grade, profile.classes
    except StudentProfile.DoesNotExist:
        return (
            name,
            "George Washington High School",
            "Freshman",
            "Algebra 2, History, English",
        )


def _load_messages_from_db(request):
    """Reconstruct the LLM messages list from DB for the current session."""
    session_id = request.session.get("session_id")
    if not session_id:
        return None
    try:
        session = Session.objects.get(id=session_id, owner=request.user)
    except Session.DoesNotExist:
        return None
    chats = DBChat.objects.filter(session=session).order_by("created_at", "id")
    return [{"role": c.role, "content": c.message} for c in chats]


def _try_extract_quiz_json(text: str):
    """
    Robustly extract JSON quiz object from model text.
    Handles fenced code blocks and extraneous surrounding text.
    Returns a normalized dict like {"test": {...}} or None.
    """
    if not text or not isinstance(text, str):
        return None

    # If text contains a fenced ```json or ``` block, prefer content inside the fences
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    candidate = m.group(1) if m else text

    # Extract the largest {...} substring (in case the model included surrounding commentary)
    brace_match = re.search(r"\{[\s\S]*\}", candidate)
    if not brace_match:
        return None
    json_text = brace_match.group(0)

    try:
        obj = json.loads(json_text)
    except Exception:
        # Try a relaxed replacement of single quotes -> double quotes and remove trailing commas
        jt = json_text.replace("'", '"')
        jt = re.sub(r",\s*([}\]])", r"\1", jt)
        try:
            obj = json.loads(jt)
        except Exception:
            return None

    # Normalize: prefer object.test / quiz / questions or treat top-level q1/q2 keys as test
    test = (obj.get("test") or obj.get("quiz") or obj.get("questions"))
    if test and isinstance(test, dict):
        return {"test": test}

    keys = list(obj.keys())
    if keys and any(k.lower().startswith("q") for k in keys):
        return {"test": obj}

    return None


# Phrasings that mean "give me a quiz". Used only to decide whether an
# unparseable reply is worth regenerating, so over-matching costs one extra
# generation and under-matching costs nothing that was not already broken.
_QUIZ_REQUEST = re.compile(
    r"\b(quiz|test me|test my|practice (question|problem)s?|assessment"
    r"|check my (understanding|knowledge))\b",
    re.IGNORECASE,
)


def _looks_like_quiz_request(text: str) -> bool:
    return bool(text and _QUIZ_REQUEST.search(text))


# The student abandoning the current problem for a different one. The ledger
# tells the tutor to continue from the last completed step, and asking it in
# the same breath to ignore that list when the topic changes does not work:
# with the ledger in place, the abandon-and-switch scenario went from 2 clean
# runs in 3 to 1 in 5, stalling on the old problem while the student asked
# about a new one. Clearing the ledger enforces server-side what the prompt
# could only request.
_TOPIC_CHANGE = re.compile(
    r"\b(forget (that|it|this)|never ?mind|instead|different (problem|question)"
    r"|new (problem|question|topic)|change (the )?(topic|subject)"
    r"|something else|move on|let's do)\b",
    re.IGNORECASE,
)


def _looks_like_topic_change(text: str) -> bool:
    return bool(text and _TOPIC_CHANGE.search(text))


# Two replies this similar are the same reply. The measured failure is literal:
# the tutor re-sent its previous turn word for word when the student asked
# "what do I do first?" instead of answering.
STALL_RATIO = 0.95

# Appended to the student's message on the one retry. Written as a note to the
# assistant rather than as words the student said; the same fold the curriculum
# context and the ledger use, and it never reaches the database - api_chat
# persists the student's own message, and the retry runs on a copy of history.
STALL_NUDGE = (
    "[Note to the assistant: your previous reply did not help the student move "
    "forward, and repeating it will not either. Do not repeat it. Name the "
    "specific next operation to perform, or give a worked example of the same "
    "kind of step, then ask one short question.]"
)


def _last_assistant_message(messages):
    for message in reversed(messages or ()):
        if message.get("role") == "assistant":
            return message.get("content") or ""
    return ""


def _is_stalled(reply, previous, ratio=STALL_RATIO):
    """True when this reply repeats the previous one.

    Uses difflib rather than equality because the model paraphrases itself:
    "What is the next step in solving 7 + 2 * 3?" against the identical
    question with one word moved is the same failure.
    """
    if not reply or not previous:
        return False
    from difflib import SequenceMatcher

    return SequenceMatcher(None, reply.strip(), previous.strip()).ratio() >= ratio


def shuffle_quiz(quiz_json, rng=None):
    """Randomise answer order and move `correct` to follow it.

    Measured 2026-08-13: the model put the correct answer first in 9 of 13
    quizzes (11 of 12 on Qwen3-8B), so a student who always picked the first
    option scored about 70% without reading the question. Instructing the model
    to vary the position is a request a 4B model is free to ignore, and it
    ignored several others. This does not ask.

    Only well-formed multiple-choice questions are touched: a numeric `correct`
    that indexes the `answers` list. Anything else — a short-answer question, a
    correct value that is answer text rather than an index, an index out of
    range — is passed through untouched, because grading falls back to string
    comparison for those and reordering would break it.
    """
    rng = rng or random
    test = (quiz_json or {}).get("test") or {}
    if not isinstance(test, dict):
        return quiz_json

    shuffled = {}
    for qid, qdata in test.items():
        qdata = dict(qdata or {})
        answers = qdata.get("answers")
        correct = str(qdata.get("correct", "")).strip()

        if (isinstance(answers, list) and len(answers) > 1
                and re.fullmatch(r"\d+", correct) and 0 <= int(correct) < len(answers)):
            was = int(correct)
            order = list(range(len(answers)))
            rng.shuffle(order)
            qdata["answers"] = [answers[i] for i in order]
            # order[j] is the old index now sitting at position j, so the new
            # home of the correct answer is wherever `was` ended up.
            qdata["correct"] = str(order.index(was))

        shuffled[qid] = qdata

    return {"test": shuffled}


def _maybe_persist_quiz(session, assistant_reply_text):
    """
    If the assistant reply parses as a quiz JSON, supersede any existing
    active quiz on this session and create a new active Quiz row so the
    grading endpoint has something to score.

    Returns the canonical JSON text of the stored quiz, or None. Callers should
    send that text on to the student and persist it as the assistant's message:
    the options are shuffled here, so the raw reply and the stored quiz no
    longer agree about which index is correct, and the client grades against
    what it was shown.
    """
    quiz_json = _try_extract_quiz_json(assistant_reply_text)
    if not quiz_json:
        return None
    quiz_json = shuffle_quiz(quiz_json)
    Quiz.objects.filter(session=session, status="active").update(
        status="submitted",
        ended_at=timezone.now(),
    )
    Quiz.objects.create(
        session=session,
        status="active",
        quiz_json=quiz_json,
    )
    return json.dumps(quiz_json, ensure_ascii=False)


@login_required(login_url="login")
def chat_page(request):
    if is_teacher_or_admin(request.user):
        return redirect("dashboard")
    ensure_llm_initialized()
    return render(request, "chat.html")


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

    name, school, grade, classes = _student_context(request.user)

    ensure_llm_initialized()

    messages = []
    if model is None or tokenizer is None:
        assistant_msg = "Model unavailable. Please try again later."
    else:
        try:
            assistant_msg, messages = _adapter().start_chat(
                model, tokenizer, name, school, grade, classes
            )
        except Exception:
            logger.exception("start_chat failed")
            messages = []
            assistant_msg = "Model error. Please try again later."

    # persist messages to DB
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if content:
            DBChat.objects.create(session=session, role=role, message=content)

    # Return assistant_msg (whether real or generic fallback)
    try:
        calculate_student_progress(request.user)
    except Exception:
        logger.exception("Progress calculation failed")

    return JsonResponse({
        "ok": True,
        "id": str(session.id),
        "title": session.title,
        "createdAt": session.created_at.isoformat(),
        "model_text": assistant_msg
    })


@require_http_methods(["POST"])
@login_required
def api_chat(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    msg = (data.get("message") or "").strip()
    if not msg:
        return HttpResponseBadRequest("message is required")

    chat = _load_messages_from_db(request)
    if chat is None:
        return HttpResponseBadRequest("No active chat, initialize first")

    # The steps already taught, so the tutor is told where it is rather than
    # having to infer it from the transcript. Read before generation, written
    # back after it, and absent for a session that has none yet.
    active_session = None
    ledger = []
    session_id = request.session.get("session_id")
    if session_id:
        active_session = Session.objects.filter(
            id=session_id, owner=request.user
        ).first()
        if active_session:
            ledger = active_session.progress_ledger or []
            if ledger and _looks_like_topic_change(msg):
                logger.info("Student changed problem - clearing the progress ledger")
                ledger = []
                active_session.progress_ledger = []
                active_session.save(update_fields=["progress_ledger"])

    ensure_llm_initialized()

    assistant_reply_text = None
    error_occurred = False

    if model is None or tokenizer is None:
        assistant_reply_text = "Model unavailable. Please try again later."
        error_occurred = True
    else:
        # send_message appends to the list it is given, so a retry needs the
        # history as it was rather than the history plus a discarded turn.
        history = list(chat)
        # The question the tutor last asked and has not had answered. Tracked
        # apart from the ledger: a pending question is not a taught step, but
        # it is the state of the conversation, and leaving it out entirely left
        # the tutor with nothing to go on when a student asked for direction.
        previous = _last_assistant_message(history)
        waiting_on = ""
        if not _looks_like_topic_change(msg):
            from languagemodel import pending_question

            waiting_on = pending_question(previous)
        try:
            assistant_reply_text, messages = _adapter().send_message(
                model, tokenizer, chat, msg, ledger=ledger, waiting_on=waiting_on
            )

            # The tutor's commonest failure is repeating its previous reply
            # word for word when the student asks for direction instead of
            # answering. The prompt now forbids it, but the prompt forbade
            # several things it went on to do, so this checks. One regeneration
            # on the failure path only.
            #
            # Skipped for quiz requests, and not only to bound the work at two
            # generations. A repeated prose reply to "quiz me" is already an
            # unparseable quiz, so the retry below catches it — and STALL_NUDGE
            # asks for "the specific next operation to perform, then one short
            # question", which steers the model away from emitting JSON. The
            # two retries would fight each other.
            if not _looks_like_quiz_request(msg) and _is_stalled(
                    assistant_reply_text, previous):
                logger.info("Reply repeated the previous one - regenerating once")
                nudged, _ = _adapter().send_message(
                    model, tokenizer, list(history), f"{msg}\n\n{STALL_NUDGE}",
                    ledger=ledger, waiting_on=waiting_on,
                )
                if nudged and not _is_stalled(nudged, previous):
                    assistant_reply_text = nudged
                else:
                    logger.warning("Regenerated reply repeated it too - sending as is")

            # A quiz that does not parse fails silently: no Quiz row is written,
            # the client renders it as an ordinary chat bubble, and the student
            # is left with a question they cannot submit. Measured at 3 in 16.
            # One more attempt costs a couple of seconds on the failure path
            # only, and nothing at all on the 13 that already worked.
            if (_looks_like_quiz_request(msg)
                    and _try_extract_quiz_json(assistant_reply_text) is None):
                logger.info("Quiz request did not produce JSON - regenerating once")
                retry_text, _ = _adapter().send_message(
                    model, tokenizer, list(history), msg, ledger=ledger
                )
                if _try_extract_quiz_json(retry_text) is not None:
                    assistant_reply_text = retry_text
                else:
                    logger.warning("Regenerated quiz did not produce JSON either "
                                   "- sending the prose reply")
        except Exception:
            logger.exception("send_message failed")
            assistant_reply_text = "Model error, please try again later."
            error_occurred = True

    # Persist to DB: only persist user + assistant when there was no model error.
    new_session_title = None
    try:
        session_id = request.session.get("session_id")
        if session_id:
            session = Session.objects.get(id=session_id, owner=request.user)

            # Auto-title from the first user message if title is still the
            # default. Ask the LLM for a 1-3 word topic; if it returns empty
            # (gibberish / no clear topic) leave the title alone.
            #
            # "First" means the first message the student actually typed. The
            # bootstrap turn start_chat persists is also role="user", so a bare
            # .exists() check here was true on every request and auto-titling
            # never ran.
            if session.title in ("", "New session") and not _has_student_message(session):
                try:
                    derived = _derive_session_title(msg)
                except Exception:
                    logger.exception("Auto-titling failed")
                    derived = ""
                if derived:
                    session.title = derived
                    session.save(update_fields=["title"])
                    new_session_title = session.title

            DBChat.objects.create(session=session, role="user", message=msg)
            if not error_occurred and assistant_reply_text:
                # Persist the quiz first: it shuffles the options, so the text
                # stored as the assistant's message has to be the stored quiz
                # rather than the raw reply. Otherwise the student is shown one
                # ordering and graded against another, and the history view
                # disagrees with both.
                try:
                    canonical = _maybe_persist_quiz(session, assistant_reply_text)
                    if canonical:
                        assistant_reply_text = canonical
                except Exception:
                    logger.exception("Quiz persistence failed")
                DBChat.objects.create(session=session, role="assistant", message=assistant_reply_text)

                # Record the step just taught, unless the reply was a quiz —
                # a quiz is not a step in a problem, and its JSON would fill
                # the ledger with noise the next turn has to read past.
                if not canonical:
                    try:
                        from languagemodel import extend_ledger

                        session.progress_ledger = extend_ledger(
                            session.progress_ledger, assistant_reply_text
                        )
                        session.save(update_fields=["progress_ledger"])
                    except Exception:
                        logger.exception("Ledger update failed")

            user_message_count = DBChat.objects.filter(session=session, role="user").count()
            if user_message_count % 5 == 0:
                calculate_student_progress(request.user)
    except Exception:
        logger.exception("Chat persistence or progress calculation failed")

    payload = {"ok": True, "model_text": assistant_reply_text}
    if new_session_title:
        payload["session_title"] = new_session_title
    if error_occurred:
        payload["error"] = True
    return JsonResponse(payload)


@require_http_methods(["POST"])
@login_required
def api_reset(request):
    request.session.pop("session_id", None)
    return JsonResponse({"ok": True})


@login_required
def api_list_sessions(request):
    """Return all sessions for the current user, or for a student if teacher/admin."""
    if not is_teacher_or_admin(request.user):
        sessions = Session.objects.filter(owner=request.user).order_by("-created_at")
    else:
        student_id_raw = request.GET.get("student_id")
        try:
            student_id = int(student_id_raw)
        except (TypeError, ValueError):
            return JsonResponse({"sessions": []})

        # Non-admin teachers may only list sessions for students assigned to
        # them, matching api_session_messages, api_export_chats and
        # progress_detail. Without this any teacher could enumerate any user's
        # sessions by id — including other teachers' and admins'.
        if not is_admin(request.user):
            try:
                teacher_profile = TeacherProfile.objects.get(user=request.user)
                student_profile = StudentProfile.objects.get(user_id=student_id)
            except (TeacherProfile.DoesNotExist, StudentProfile.DoesNotExist):
                return JsonResponse({"error": "Access denied"}, status=403)

            if student_profile.teacher_id != teacher_profile.id:
                return JsonResponse({"error": "Access denied"}, status=403)

        sessions = Session.objects.filter(owner_id=student_id).order_by("-created_at")

    data = [{"id": str(s.id), "title": s.title, "created_at": s.created_at.isoformat()} for s in sessions]
    return JsonResponse({"sessions": data})


@login_required
@require_GET
def api_session_messages(request, session_id):
    try:
        session = Session.objects.select_related("owner").get(id=session_id)
    except Session.DoesNotExist:
        return HttpResponseBadRequest("Session not found or not owned by user")
    
    allowed = False

    if session.owner_id == request.user.id:
        allowed = True
    elif is_teacher_or_admin(request.user):
        allowed = True
        # Non-admin teachers must be assigned to that student
        if not is_admin(request.user):
            try:
                teacher_profile = TeacherProfile.objects.get(user=request.user)
                student_profile = StudentProfile.objects.get(user=session.owner)
            except (TeacherProfile.DoesNotExist, StudentProfile.DoesNotExist):
                return JsonResponse({"error": "Access denied"}, status=403)

            if student_profile.teacher_id != teacher_profile.id:
                return JsonResponse({"error": "Access denied"}, status=403)

    if not allowed:
        return JsonResponse({"error": "Access denied"}, status=403)

    chats = DBChat.objects.filter(session=session).order_by("created_at", "id")  # keep chronological order
    # Hide bootstrap messages from the UI. They are persisted so the LLM can
    # reconstruct context in _load_messages_from_db, but they must never be
    # shown to the student when viewing chat history (issue #35).
    # Two things to hide:
    #   1. role="system" rows (the tutor instructions block)
    #   2. The auto-generated "Here is your student information..." user
    #      message the backend sends on start_chat — the student never typed it.
    messages = [
        {"role": c.role, "text": c.message}
        for c in chats
        if c.role != "system"
        and not (c.role == "user" and _is_bootstrap_user_message(c.message))
    ]

    quiz_attempts = []
    quizzes = Quiz.objects.filter(session=session).order_by("started_at", "id")
    for quiz in quizzes:
        quiz_answer = quiz.answers.order_by("-submitted_at").first()
        test = (quiz.quiz_json or {}).get("test") or {}
        items = []
        if isinstance(test, dict):
            for qid, qdata in test.items():
                qdata = qdata or {}
                answers_list = qdata.get("answers") or []
                correct_raw = str(qdata.get("correct", "")).strip()

                correct_display = correct_raw
                if re.match(r'^\d+$', correct_raw):
                    ci = int(correct_raw)
                    if 0 <= ci < len(answers_list):
                        correct_display = str(answers_list[ci])

                user_raw = ""
                user_display = ""
                is_correct = None

                if quiz_answer:
                    answers_json = quiz_answer.answers_json or {}
                    graded_json = quiz_answer.graded_json or {}
                    user_raw = str(answers_json.get(qid, "")).strip()
                    user_display = user_raw
                    if re.match(r'^\d+$', user_raw):
                        ui = int(user_raw) - 1
                        if 0 <= ui < len(answers_list):
                            user_display = str(answers_list[ui])

                    grade_item = graded_json.get(qid)
                    if isinstance(grade_item, dict) and "isCorrect" in grade_item:
                        is_correct = bool(grade_item.get("isCorrect"))

                items.append({
                    "qid": qid,
                    "student_answer": user_display,
                    "correct_answer": correct_display,
                    "is_correct": is_correct,
                })

        quiz_attempts.append({
            "quiz_id": str(quiz.id),
            "status": quiz.status,
            "has_submission": quiz_answer is not None,
            "items": items,
        })

    # set the active session for subsequent api_chat persistence
    if not is_teacher_or_admin(request.user):
        request.session['session_id'] = str(session.id)

    return JsonResponse({"ok": True, "messages": messages, "quiz_attempts": quiz_attempts})


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

    # Same persona source as api_new_session. This used to hard-code a school,
    # grade and class list, so a session bootstrapped through this path told the
    # tutor things about the student that were simply untrue.
    name, school, grade, classes = _student_context(request.user)

    ensure_llm_initialized()
    if model is None or tokenizer is None:
        return JsonResponse({"ok": False, "error": "Model unavailable"}, status=503)

    try:
        assistant_msg, messages = _adapter().start_chat(
            model, tokenizer, name, school, grade, classes
        )
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"LLM init error: {e}"}, status=500)

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if content:
            DBChat.objects.create(session=session, role=role, message=content)

    request.session['session_id'] = str(session.id)

    return JsonResponse({"ok": True, "model_text": assistant_msg or "Hello!"})


@require_http_methods(["DELETE"])
@login_required
def api_delete_session(request, session_id):
    session = get_object_or_404(Session, id=session_id, owner=request.user)
    session.delete()
    return JsonResponse({"ok": True, "status": "deleted"})


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


@require_http_methods(["POST"])
@login_required
def api_select_session(request, session_id):
    """
    Select an existing DB session. Sets request.session['session_id'] so
    subsequent api_chat calls persist messages to the correct session.
    """
    try:
        session = Session.objects.get(id=session_id, owner=request.user)
    except Session.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Session not found"}, status=404)

    request.session['session_id'] = str(session.id)

    return JsonResponse({"ok": True})


@require_http_methods(["POST"])
@login_required
def api_grade_quiz(request):
    session_id = request.session.get("session_id")
    if not session_id:
        return HttpResponseBadRequest("No active session")

    try:
        session = Session.objects.get(id=session_id, owner=request.user)
    except Session.DoesNotExist:
        return HttpResponseBadRequest("Session not found")
    
    quiz = Quiz.objects.filter(session=session, status="active").order_by("-started_at").first()
    if quiz is None:
        return JsonResponse({
            "ok": True,
            "model_text": "No active quiz",
            "error": True
        })
    
    quiz_obj = quiz.quiz_json
    test = (quiz_obj or {}).get("test") or {}
    q_items = list(test.items())

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    csv_string = (data.get("answers") or "").strip()
    if not csv_string:
        return HttpResponseBadRequest("answers is required")
    
    answers = parse_csv_answers(csv_string)
    
    total_points = 0.0
    earned_points = 0.0
    graded_feedback = {}  # qid -> message (for frontend modal)
    graded_json = {}      # qid -> structured grading (for persistence/analytics)
    answers_json = {}     # qid -> raw submitted answer token

    for idx, (qid, qdata) in enumerate(q_items):
        correct = qdata.get("correct")
        answers_list = qdata.get("answers") or []

        try:
            possible = float(qdata.get("points", 1))
        except Exception:
            possible = 1.0

        total_points += possible
        user_ans = answers[idx] if idx < len(answers) else ""

        # Normalize strings
        user_ans_str = str(user_ans).strip()
        correct_str = str(correct).strip()

        is_correct = False
        # If both look numeric, compare user's 1-based to model's 0-based index
        if re.match(r'^\d+$', user_ans_str) and re.match(r'^\d+$', correct_str):
            try:
                is_correct = (int(user_ans_str) - 1) == int(correct_str)
            except Exception:
                is_correct = False
        else:
            # fallback string comparison
            is_correct = user_ans_str.lower() == correct_str.lower()

        # Prepare human-friendly correct answer display
        correct_display = correct_str
        if re.match(r'^\d+$', correct_str):
            try:
                ci = int(correct_str)
                if 0 <= ci < len(answers_list):
                    correct_display = answers_list[ci]
                else:
                    correct_display = correct_str
            except Exception:
                correct_display = correct_str

        # Also show what the user selected (if numeric convert to answer text)
        user_display = user_ans_str
        if re.match(r'^\d+$', user_ans_str):
            try:
                ui = int(user_ans_str) - 1
                if 0 <= ui < len(answers_list):
                    user_display = answers_list[ui]
            except Exception:
                pass

        if is_correct:
            feedback = "correct"
        else:
            if user_display:
                feedback = f"incorrect: Your answer: {user_display}. Correct: {correct_display}"
            else:
                feedback = f"incorrect: Answer was {correct_display}"

        earned_points += possible if is_correct else 0
        graded_feedback[qid] = feedback
        graded_json[qid] = {
            "isCorrect": is_correct,
            "studentAnswer": user_display,
            "correctAnswer": correct_display,
        }
        answers_json[qid] = user_ans_str
        
    quiz.possible_pts = total_points
    quiz.earned_pts = earned_points
    quiz.status = "graded"
    quiz.ended_at = timezone.now()
    quiz.save(update_fields=["status", "possible_pts", "earned_pts", "ended_at"])

    QuizAnswer.objects.create(
        quiz=quiz,
        answers_json=answers_json,
        graded_json=graded_json,
    )

    # Refresh cached StudentProgress so the dashboard quiz_average reflects
    # this attempt immediately. A recompute failure must not fail grading.
    try:
        calculate_student_progress(request.user)
    except Exception:
        logger.exception("Progress recompute after grading failed")

    # Return structured JSON (frontend will parse and display it)
    feedback_json = json.dumps(graded_feedback)
    return JsonResponse({"ok": True, "model_text": feedback_json})
