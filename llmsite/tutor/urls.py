from django.urls import path
from .views import chat_page, api_init, api_chat, api_reset

from .views import chat_page, api_init, api_chat, api_reset

urlpatterns = [
    path("", chat_page, name="chat_page"),
    path("chat/", chat_page, name="chat_page"),
    path("api/init/", api_init, name="api_init"),
    path("api/chat/", api_chat, name="api_chat"),
    path("api/reset/", api_reset, name="api_reset"),
]