from django.db import models
from django.contrib.auth.models import User

class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    school = models.CharField(max_length=200, blank=True)
    grade = models.CharField(max_length=50, blank=True)
    classes = models.TextField(blank=True)  # comma-separated list

    def __str__(self):
        return self.user.username
