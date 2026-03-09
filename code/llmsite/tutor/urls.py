from django.urls import path
from . import views

from .views import (
    chat_page, api_new_session, api_init, api_chat, api_reset, api_new_session, signup, 
    dashboard_page, account_create, account_delete, student_edit, 
    upload_curriculum, curriculum_delete, curriculum_view,
    api_session_messages, api_delete_session, api_list_sessions, api_rename_session, api_export_chats,
    landing_page, progress_summary, progress_detail, chat_history
)

urlpatterns = [
    path("", landing_page, name="landing"),
    path("chat/", chat_page, name="chat"),
    path("chat/history/", chat_history, name="chat_history"),
    path("signup/", signup, name="signup"),
    path("dashboard/", dashboard_page, name="dashboard"),
    path("progress/", progress_detail, name="progress_detail"),
    path("api/init/", api_init, name="api_init"),
    path("api/session/new/", api_new_session, name="api_new_session"),
    path("api/chat/", api_chat, name="api_chat"),
    path("api/grade-quiz/", views.api_grade_quiz, name="api_grade_quiz"),
    path("api/reset/", api_reset, name="api_reset"),
    path("api/progress/summary/", progress_summary, name="progress_summary"),
    path("api/export/chats/", api_export_chats, name="api_export_chats"),
    path("dashboard/create_account/", account_create, name="account_create"),
    path("dashboard/delete_account/", account_delete, name="account_delete"),
    path("dashboard/edit_student", student_edit, name="student_edit"),
    path("dashboard/curriculum/upload", upload_curriculum, name="upload_curriculum"),
    path("dashboard/curriculum/delete", curriculum_delete, name="curriculum_delete"),
    path("api/sessions/", api_list_sessions, name="api_list_sessions"),
    path("dashboard/curriculum/view/<str:filename>", curriculum_view, name="curriculum_view"),
    path("api/session/<uuid:session_id>/messages/", api_session_messages, name="api_session_messages"),
    path('api/session/<str:session_id>/select/', views.api_select_session, name='api_select_session'),
    path('api/session/<str:session_id>/init/', views.api_session_init, name='api_session_init'),
    path("api/session/<uuid:session_id>/delete/", api_delete_session, name="api_delete_session"),
    path("api/session/<uuid:session_id>/rename/", api_rename_session, name="api_rename_session")
]
