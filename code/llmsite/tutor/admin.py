from django.contrib import admin
from .models import StudentProfile, StudentProgress, Session, Chat, Quiz, QuizAnswer

admin.site.register(StudentProfile)
admin.site.register(StudentProgress)
admin.site.register(Session)
admin.site.register(Chat)
admin.site.register(Quiz)
admin.site.register(QuizAnswer)
