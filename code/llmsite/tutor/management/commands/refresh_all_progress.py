"""
Management command to recalculate progress for all users.
Usage: python manage.py refresh_all_progress
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from tutor.utils import calculate_student_progress
from tutor.models import StudentProfile

User = get_user_model()


class Command(BaseCommand):
    help = 'Recalculate progress for all students (backfill job)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            help='Recalculate progress for a specific user ID',
        )
        parser.add_argument(
            '--students-only',
            action='store_true',
            help='Only process users with StudentProfile',
        )

    def handle(self, *args, **options):
        user_id = options.get('user_id')
        students_only = options.get('students_only')

        if user_id:
            # Refresh specific user
            try:
                user = User.objects.get(id=user_id)
                self.stdout.write(f"Refreshing progress for user: {user.username}...")
                metrics = calculate_student_progress(user)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ {user.username}: {metrics['overall_completion_percent']:.1f}% complete, "
                        f"{metrics['total_sessions']} sessions, {metrics['total_quizzes']} quizzes"
                    )
                )
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"User with ID {user_id} not found"))
            return

        # Refresh all users
        if students_only:
            # Only users with StudentProfile
            users = User.objects.filter(studentprofile__isnull=False)
            self.stdout.write(f"Refreshing progress for {users.count()} students...")
        else:
            users = User.objects.all()
            self.stdout.write(f"Refreshing progress for {users.count()} users...")

        success_count = 0
        error_count = 0

        for user in users:
            try:
                metrics = calculate_student_progress(user)
                self.stdout.write(
                    f"  ✓ {user.username}: {metrics['overall_completion_percent']:.1f}% complete"
                )
                success_count += 1
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"  ✗ {user.username}: {str(e)}")
                )
                error_count += 1

        # Summary
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(
            self.style.SUCCESS(f"Successfully processed: {success_count}")
        )
        if error_count > 0:
            self.stdout.write(
                self.style.ERROR(f"Failed: {error_count}")
            )
        self.stdout.write("=" * 50)
