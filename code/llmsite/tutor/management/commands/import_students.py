from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from tutor.models import StudentProfile
import csv

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

                user, created = User.objects.get_or_create(username=username)

                if created:
                    user.set_password(password)
                    user.save()
                    action = "CREATED"
                else:
                    action = "UPDATED"

                profile, _ = StudentProfile.objects.get_or_create(user=user)
                profile.school = row.get("school", "")
                profile.grade = row.get("grade", "")
                profile.classes = row.get("classes", "")
                profile.save()

                self.stdout.write(f"{action}: {username}")

        self.stdout.write(self.style.SUCCESS("Import finished!"))
