
from django.db import models
from django.contrib.auth import get_user_model
import uuid

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

class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    school = models.CharField(max_length=200, blank=True)
    grade = models.CharField(max_length=50, blank=True)
    classes = models.TextField(blank=True)  # comma-separated list

    def __str__(self):
        return self.user.username
