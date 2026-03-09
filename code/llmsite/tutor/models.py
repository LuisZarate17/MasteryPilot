
from django.db import models
from django.contrib.auth import get_user_model
import uuid
from django.conf import settings

User = get_user_model()

class Session(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="sessions")
    title = models.CharField(max_length=200, default="New session")
    created_at = models.DateTimeField(auto_now_add=True)


class Chat(models.Model):
    ROLE = (("user","User"),("assistant","Assistant"),("system","System"))
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='chats')
    role = models.CharField(max_length=10, choices=ROLE, default="user", db_index=True)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["session","created_at"])]

class Quiz(models.Model):
    STATUS = (("active","Active"),("submitted","Submitted"),("graded","Graded"))
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='quizzes')
    status = models.CharField(max_length=10, choices=STATUS, default="active", db_index=True)
    possible_pts = models.FloatField(default=0.0)
    earned_pts = models.FloatField(default=0.0)
    quiz_json = models.JSONField()            # items, keys, etc.
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session"],
                condition=models.Q(status="active"),
                name="one_active_quiz_per_session",
            )
        ]


class QuizAnswer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='answers')
    # map item_id/index -> user answer object
    answers_json = models.JSONField()          # {"1":{"choiceId":"B"},"2":{"choiceIds":["A","D"]},...}
    graded_json = models.JSONField(null=True, blank=True)  # per-item isCorrect, correctAnswer, rationale
    submitted_at = models.DateTimeField(auto_now_add=True)

from django.contrib.auth.models import User



class TeacherProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    display_name = models.CharField(max_length=200, blank=True)
    
    def __str__(self):
        return self.display_name or self.user.get_full_name() or self.user.username
    
class StudentProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    display_name = models.CharField(max_length=200, blank=True)
    school = models.CharField(max_length=200, blank=True)
    grade = models.CharField(max_length=50, blank=True)
    classes = models.TextField(blank=True)  # comma-separated list
    teacher = models.ForeignKey(
        TeacherProfile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="students",
    )

    def __str__(self):
        return self.display_name or self.user.get_full_name() or self.user.username

class AdminProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    display_name = models.CharField(max_length=200, blank=True)

class StudentProgress(models.Model):
    """
    Caches computed progress metrics for students.
    Updated on quiz submissions, session completions, and via backfill jobs.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="progress",
        db_index=True
    )
    overall_completion_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text="Weighted completion based on quiz scores and session activity"
    )
    current_module = models.CharField(
        max_length=200,
        blank=True,
        help_text="Current topic/module - inferred from most recent session title"
    )
    quiz_average = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Average quiz score across all graded quizzes"
    )
    activity_streak = models.IntegerField(
        default=0,
        help_text="Consecutive days with at least one activity"
    )
    last_activity = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of most recent chat or quiz activity"
    )
    total_sessions = models.IntegerField(
        default=0,
        help_text="Total number of chat sessions created"
    )
    total_quizzes = models.IntegerField(
        default=0,
        help_text="Total number of quizzes completed"
    )
    total_messages = models.IntegerField(
        default=0,
        help_text="Total number of user messages sent"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'updated_at']),
        ]
        verbose_name_plural = "Student Progress"

    def __str__(self):
        return f"Progress for {self.user.username}: {self.overall_completion_percent}%"
