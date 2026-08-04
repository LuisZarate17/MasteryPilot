from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from tutor.models import StudentProfile
import csv

REQUIRED_COLUMNS = {"username", "password"}


def _split_full_name(full_name: str) -> tuple[str, str]:
    cleaned = (full_name or "").strip()
    if not cleaned:
        return "", ""

    parts = cleaned.split(None, 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""
    return first_name, last_name


class Command(BaseCommand):
    help = (
        "Import student accounts from a CSV file. "
        "See sample_data/students.sample.csv for the expected columns."
    )

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str)
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help=(
                "Also set the password on accounts that already exist. "
                "Off by default so an import never silently rotates a "
                "credential a student has already changed."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        csv_path = options["csv_path"]
        reset_passwords = options["reset_passwords"]

        try:
            # utf-8-sig strips the byte-order mark Excel writes when it saves
            # as CSV. Plain utf-8 would fold it into the first header name and
            # report the "username" column as missing.
            handle_ = open(csv_path, newline="", encoding="utf-8-sig")
        except OSError as exc:
            raise CommandError(f"Could not open {csv_path}: {exc}") from exc

        errors = []

        with handle_ as f:
            reader = csv.DictReader(f)

            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise CommandError(
                    f"{csv_path} is missing required column(s): "
                    f"{', '.join(sorted(missing))}. "
                    "See sample_data/students.sample.csv."
                )

            for line_number, row in enumerate(reader, start=2):
                username = (row.get("username") or "").strip()
                password = row.get("password") or ""

                if not username:
                    errors.append(f"line {line_number}: blank username")
                    continue

                full_name = (row.get("full_name") or "").strip()
                first_name, last_name = _split_full_name(full_name)

                user, created = User.objects.get_or_create(username=username)
                set_password = created or reset_passwords

                if set_password:
                    try:
                        validate_password(password, user=user)
                    except ValidationError as exc:
                        errors.append(
                            f"line {line_number} ({username}): "
                            f"{' '.join(exc.messages)}"
                        )
                        continue
                    user.set_password(password)

                user.first_name = first_name
                user.last_name = last_name
                user.email = (row.get("email") or "").strip()
                user.save()

                profile, _ = StudentProfile.objects.get_or_create(user=user)
                profile.display_name = (
                    full_name or user.get_full_name() or user.username
                )
                profile.school = row.get("school", "")
                profile.grade = row.get("grade", "")
                profile.classes = row.get("classes", "")
                profile.save()

                if created:
                    action = "CREATED"
                elif reset_passwords:
                    action = "UPDATED (password reset)"
                else:
                    action = "UPDATED (password unchanged)"
                self.stdout.write(f"{action}: {username}")

        if errors:
            # Inside @transaction.atomic, so raising here rolls the whole import
            # back rather than leaving a half-populated roster behind.
            raise CommandError(
                "Import aborted; no accounts were changed.\n  "
                + "\n  ".join(errors)
            )

        self.stdout.write(self.style.SUCCESS("Import finished!"))
