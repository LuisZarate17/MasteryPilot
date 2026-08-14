"""Shared base class and fixture helpers for the tutor test suite.

Two settings are pinned on the base class rather than left to the environment:

* ``SECURE_SSL_REDIRECT`` — a developer with ``DJANGO_SECURE_SSL_REDIRECT=1`` in
  their .env turns every single test into a 301. That regression already
  happened once (commit 710e960); pinning it here means it cannot happen again.
* ``PASSWORD_HASHERS`` — PBKDF2 at full iterations dominates the runtime of a
  suite that creates this many users. The auth password *validators* still
  apply, so signup/account_create tests keep exercising the real rules.

Note on isolation: the repo-root .env sets ADMIN_PASS, so migration 0002 seeds
an ``admin`` superuser into the local test database that CI will not have.
Assert on explicit usernames, never on absolute counts.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from ..models import AdminProfile, Chat, Quiz, Session, StudentProfile, TeacherProfile

PASSWORD = "ComplexPass123!"

# Whether requirements-llm.txt is installed in the interpreter running this
# suite. Both answers are legitimate and both are exercised in CI: tests.yml
# installs requirements.txt alone, rag-verify installs the stack on top.
#
# A test that reads this to *skip* itself is almost always wrong — a skipped
# test proves nothing, and the eight tests that once depended on the stack
# being absent now establish the condition they need instead. Use it to pick
# which assertion is meaningful, not whether to run.
try:
    import faiss  # noqa: F401
    import sentence_transformers  # noqa: F401

    HAS_RAG_STACK = True
except ImportError:
    HAS_RAG_STACK = False

SKIP_REASON = "requirements-llm.txt is not installed (run the rag-verify workflow)"


@override_settings(
    SECURE_SSL_REDIRECT=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class MasteryPilotTestCase(TestCase):
    """Base class for every test in this suite."""

    # ── User / role fixtures ─────────────────────────────────────────────────
    # Roles are profile rows, not Django Groups — see tutor/utils.py.

    @staticmethod
    def make_user(username, **kwargs):
        User = get_user_model()
        kwargs.setdefault("password", PASSWORD)
        kwargs.setdefault("email", f"{username}@example.com")
        return User.objects.create_user(username=username, **kwargs)

    @classmethod
    def make_student(cls, username="student", teacher=None, **profile_kwargs):
        user = cls.make_user(username)
        profile_kwargs.setdefault("display_name", username.title())
        StudentProfile.objects.create(user=user, teacher=teacher, **profile_kwargs)
        return user

    @classmethod
    def make_teacher(cls, username="teacher", **profile_kwargs):
        user = cls.make_user(username)
        profile_kwargs.setdefault("display_name", username.title())
        TeacherProfile.objects.create(user=user, **profile_kwargs)
        return user

    @classmethod
    def make_admin(cls, username="admin_user", **profile_kwargs):
        user = cls.make_user(username)
        profile_kwargs.setdefault("display_name", username.title())
        AdminProfile.objects.create(user=user, **profile_kwargs)
        return user

    @classmethod
    def make_superuser(cls, username="superuser"):
        """A superuser with *no* AdminProfile.

        utils.is_admin short-circuits on is_superuser, so this user is an admin
        despite having no profile row. Worth exercising separately.
        """
        User = get_user_model()
        return User.objects.create_superuser(
            username=username, email=f"{username}@example.com", password=PASSWORD
        )

    # ── Content fixtures ─────────────────────────────────────────────────────

    @staticmethod
    def make_session(owner, title="Test session"):
        return Session.objects.create(owner=owner, title=title)

    @staticmethod
    def make_chat(session, role, message):
        return Chat.objects.create(session=session, role=role, message=message)

    @staticmethod
    def make_quiz(session, test, status="active"):
        """Create a Quiz. *test* is the inner dict, i.e. {"q1": {...}}."""
        return Quiz.objects.create(
            session=session, status=status, quiz_json={"test": test}
        )

    @staticmethod
    def mc_question(question="What is 2 + 2?", answers=None, correct="0", **extra):
        """A multiple-choice question dict in the shape the model emits.

        ``correct`` is a *string, 0-based* index — the convention the tutor
        system prompt asks for and that api_grade_quiz reconciles against the
        1-based value the radio inputs submit.
        """
        return {
            "question": question,
            "type": "multiple-choice",
            "answers": answers if answers is not None else ["4", "5", "6", "7"],
            "correct": correct,
            **extra,
        }

    # ── Session helper ───────────────────────────────────────────────────────

    def set_active_session(self, session):
        """Put *session* in the Django session, as the chat UI does."""
        s = self.client.session
        s["session_id"] = str(session.id)
        s.save()


class FakeAdapter:
    """Stand-in for languagemodel.Adapter.

    Patch it in with ``patch("tutor.views.chat._adapter", return_value=...)``.
    Note that ``tutor.views.chat.get_adapter`` does not exist as a name — the
    real import happens inside ``_adapter()`` on every call — so ``_adapter``
    is the only view-layer seam.
    """

    def __init__(self, reply="Assistant reply", greeting="Hello!", title="Derived title"):
        self._reply = reply
        self._greeting = greeting
        self._title = title
        self.start_chat_calls = []
        self.send_message_calls = []
        self.derive_title_calls = []
        self.ledgers_seen = []

    def init_model(self):
        return object(), object()

    def start_chat(self, model, tokenizer, student_name, student_school, student_grade, student_classes):
        self.start_chat_calls.append(
            {
                "name": student_name,
                "school": student_school,
                "grade": student_grade,
                "classes": student_classes,
            }
        )
        messages = [
            {"role": "system", "content": "SYSTEM PROMPT"},
            {"role": "user", "content": "Here is your student information ..."},
            {"role": "assistant", "content": self._greeting},
        ]
        return self._greeting, messages

    def send_message(self, model, tokenizer, messages, new_message, ledger=None):
        self.send_message_calls.append(new_message)
        # What the view handed over as already-taught steps. Recorded rather
        # than ignored so a test can assert the ledger reaches the adapter.
        self.ledgers_seen.append(list(ledger or []))
        updated = list(messages) + [
            {"role": "user", "content": new_message},
            {"role": "assistant", "content": self._reply},
        ]
        return self._reply, updated

    def derive_session_title(self, model, tokenizer, first_message):
        self.derive_title_calls.append(first_message)
        return self._title
