"""Views for the tutor app.

Split across four modules by concern. Everything public is re-exported here,
so `from tutor import views` and `from .views import <name>` keep working and
urls.py needs no knowledge of the layout.
"""

from .chat import (
    api_chat,
    api_delete_session,
    api_grade_quiz,
    api_list_sessions,
    api_new_session,
    api_rename_session,
    api_reset,
    api_select_session,
    api_session_init,
    api_session_messages,
    chat_page,
    ensure_llm_initialized,
)
from .accounts import (
    account_create,
    account_delete,
    account_password_edit,
    chat_history,
    dashboard_page,
    signup,
    student_edit,
)
from .curriculum import (
    ALLOWED_UPLOAD_TYPES,
    MAX_UPLOAD_SIZE,
    api_export_chats,
    curriculum_delete,
    curriculum_view,
    upload_curriculum,
)
from .progress import (
    landing_page,
    progress_detail,
    progress_summary,
)

__all__ = [
    "ALLOWED_UPLOAD_TYPES",
    "MAX_UPLOAD_SIZE",
    "account_create",
    "account_delete",
    "account_password_edit",
    "api_chat",
    "api_delete_session",
    "api_export_chats",
    "api_grade_quiz",
    "api_list_sessions",
    "api_new_session",
    "api_rename_session",
    "api_reset",
    "api_select_session",
    "api_session_init",
    "api_session_messages",
    "chat_history",
    "chat_page",
    "curriculum_delete",
    "curriculum_view",
    "dashboard_page",
    "ensure_llm_initialized",
    "landing_page",
    "progress_detail",
    "progress_summary",
    "signup",
    "student_edit",
    "upload_curriculum",
]
