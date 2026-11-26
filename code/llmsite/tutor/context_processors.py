from django.conf import settings


def signup_enabled(request):
    """Lets templates hide the sign-up links while /signup/ is switched off."""
    return {"allow_signup": settings.ALLOW_SIGNUP}
