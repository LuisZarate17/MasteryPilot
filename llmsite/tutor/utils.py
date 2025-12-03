from .models import TeacherProfile, AdminProfile

# Security

def is_teacher_or_admin(user):
    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    is_teacher = TeacherProfile.objects.filter(user=user).exists()
    is_admin = AdminProfile.objects.filter(user=user).exists()
    return is_teacher or is_admin

def is_admin(user):
    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    is_admin = AdminProfile.objects.filter(user=user).exists()
    return is_admin