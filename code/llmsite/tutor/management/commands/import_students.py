from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from tutor.models import StudentProfile
import csv


def _split_full_name(full_name: str) -> tuple[str, str]:
    cleaned = (full_name or "").strip()
    if not cleaned:
        return "", ""

    parts = cleaned.split(None, 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""
    return first_name, last_name


class Command(BaseCommand):
    help = "Import student accounts from a CSV file"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str)

    def handle(self, *args, **kwargs):
        csv_path = kwargs["csv_path"]

        with open(csv_path, newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                username = row["username"]
                password = row["password"]
                full_name = (row.get("full_name") or "").strip()
                first_name, last_name = _split_full_name(full_name)

                user, created = User.objects.get_or_create(username=username)
                user.first_name = first_name
                user.last_name = last_name
                user.email = (row.get("email") or "").strip()

                if created:
                    user.set_password(password)
                    action = "CREATED"
                else:
                    action = "UPDATED"
                user.save()

                profile, _ = StudentProfile.objects.get_or_create(user=user)
                profile.display_name = full_name or user.get_full_name() or user.username
                profile.school = row.get("school", "")
                profile.grade = row.get("grade", "")
                profile.classes = row.get("classes", "")
                profile.save()

                self.stdout.write(f"{action}: {username}")

        self.stdout.write(self.style.SUCCESS("Import finished!"))
