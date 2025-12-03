from django.urls import path
from .views import chat_page, api_init, api_chat, api_reset, api_new_session, signup, dashboard_page, account_create, account_delete

urlpatterns = [
    path("", chat_page, name="chat_page"),
    path("chat/", chat_page, name="chat_page"),
    path("signup/", signup, name="signup"),
    path("dashboard/", dashboard_page, name="dashboard"),
    path("api/init/", api_init, name="api_init"),
    path("api/session/new/", api_new_session, name="api_new_session"),
    path("api/chat/", api_chat, name="api_chat"),
    path("api/reset/", api_reset, name="api_reset"),
    path("dashboard/create_account/", account_create, name="account_create"),
    path("dashboard/delete_account/", account_delete, name="account_delete"),
]