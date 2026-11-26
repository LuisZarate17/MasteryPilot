"""
Create ready-made accounts for local testing.

Usage: python manage.py create_demo_accounts [--password PW] [--reset-passwords]

The accounts share one password, so this refuses to run unless DEBUG is on. A
real deployment runs with DEBUG off and can never have them created.
"""
import os
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tutor.models import AdminProfile, StudentProfile, TeacherProfile

User = get_user_model()

TEACHER_USERNAME = "demo_teacher"

# username, role, display name, first name, last name, grade, classes, teacher.
# demo_student3 has no teacher, to test that teachers cannot see unassigned
# students.
DEMO_ACCOUNTS = [
    ("demo_admin", "admin", "Demo Admin", "Demo", "Admin", "", "", False),
    (TEACHER_USERNAME, "teacher", "Demo Teacher", "Demo", "Teacher", "", "", False),
    ("demo_student", "student", "Demo Student", "Demo", "Student", "9",
     "Algebra I; Biology", True),
    ("demo_student2", "student", "Demo Student Two", "Demo", "Student Two", "10",
     "Geometry; Chemistry", True),
    ("demo_student3", "student", "Demo Student Three", "Demo", "Student Three", "",
     "", False),
]

PROFILE_MODELS = {
    "admin": AdminProfile,
    "teacher": TeacherProfile,
    "student": StudentProfile,
}


def _role_of(user):
    """The role a user's profile rows give them, or None if they have none."""
    for role, profile_model in PROFILE_MODELS.items():
        if profile_model.objects.filter(user=user).exists():
            return role
    return None


class Command(BaseCommand):
    help = "Create demo admin, teacher and student accounts (local testing only; needs DEBUG)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            help="Password for the demo accounts. Falls back to DEMO_PASSWORD, "
                 "then to a random one that is printed once.",
        )
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Also set the password on demo accounts that already exist",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "create_demo_accounts only runs with DJANGO_DEBUG=1. Demo accounts "
                "share one password and are for local testing only; they must never "
                "exist on a deployed site."
            )

        password = options.get("password") or os.getenv("DEMO_PASSWORD") or ""
        generated = not password
        if generated:
            password = secrets.token_urlsafe(12)

        for username, _role, _display, first, last, *_rest in DEMO_ACCOUNTS:
            candidate = User(username=username, first_name=first, last_name=last)
            try:
                validate_password(password, user=candidate)
            except ValidationError as exc:
                raise CommandError(
                    "The demo password is not acceptable: " + " ".join(exc.messages)
                )

        reset = options["reset_passwords"]
        rows = []
        with transaction.atomic():
            # Check every username before changing anything, so a conflict on
            # the last account does not leave the first four half-made.
            for username, role, *_rest in DEMO_ACCOUNTS:
                existing = User.objects.filter(username=username).first()
                if existing is None:
                    continue
                if existing.is_superuser:
                    raise CommandError(
                        f"{username} exists and is a superuser. Nothing was changed."
                    )
                actual = _role_of(existing)
                if actual != role:
                    raise CommandError(
                        f"{username} exists with role {actual or 'none'}, expected "
                        f"{role}. Nothing was changed."
                    )

            teacher_profile = None
            for username, role, display, first, last, grade, classes, assigned in DEMO_ACCOUNTS:
                user = User.objects.filter(username=username).first()
                if user is not None:
                    status = "exists"
                    if reset:
                        user.set_password(password)
                        user.save(update_fields=["password"])
                        status = "exists, password reset"
                else:
                    user = User.objects.create_user(
                        username=username,
                        email=f"{username}@example.com",
                        password=password,
                        first_name=first,
                        last_name=last,
                    )
                    status = "created"
                    if role == "admin":
                        AdminProfile.objects.create(user=user, display_name=display)
                    elif role == "teacher":
                        TeacherProfile.objects.create(user=user, display_name=display)
                    else:
                        StudentProfile.objects.create(
                            user=user,
                            display_name=display,
                            grade=grade,
                            classes=classes,
                            teacher=teacher_profile if assigned else None,
                        )

                if role == "teacher":
                    teacher_profile = TeacherProfile.objects.get(user=user)

                teacher_name = "-"
                if role == "student":
                    profile = StudentProfile.objects.select_related("teacher__user").get(user=user)
                    if profile.teacher_id:
                        teacher_name = profile.teacher.user.username
                rows.append((username, role, teacher_name, status))

        self.stdout.write("")
        header = ("username", "role", "teacher", "status")
        widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
        for row in [header, *rows]:
            self.stdout.write("  ".join(str(c).ljust(w) for c, w in zip(row, widths)).rstrip())

        if generated and any(r[3] != "exists" for r in rows):
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                f"Generated password: {password}\n"
                "Save it now; it is not shown again. Run with --reset-passwords "
                "to set a new one."
            ))
