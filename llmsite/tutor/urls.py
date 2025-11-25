from django.urls import path
from .views import chat_page, api_init, api_chat, api_reset, api_new_session, signup

urlpatterns = [
    path("", chat_page, name="chat_page"),
    path("chat/", chat_page, name="chat_page"),
    path("signup/", signup, name="signup"),
    path("api/init/", api_init, name="api_init"),
    path("api/session/new/", api_new_session, name="api_new_session"),
    path("api/chat/", api_chat, name="api_chat"),
    path("api/reset/", api_reset, name="api_reset"),
]