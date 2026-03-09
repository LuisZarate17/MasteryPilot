# code/llmsite/tutor/apps.py
from django.apps import AppConfig
import os
import sys


def _should_skip_llm_init() -> bool:
    skip_env = (os.getenv("SKIP_LLM_INIT") or "").strip().lower()
    if skip_env in {"1", "true", "yes", "on"}:
        return True

    # Covers `manage.py test ...` and common pytest runs.
    argv = [a.lower() for a in sys.argv]
    if ("test" in argv) or any("pytest" in a for a in argv):
        return True

    # Skip costly/nonessential LLM setup for maintenance commands.
    management_commands = {
        "migrate",
        "makemigrations",
        "showmigrations",
        "collectstatic",
        "check",
        "shell",
        "dbshell",
        "createsuperuser",
    }
    if len(argv) > 1 and argv[1] in management_commands:
        return True

    return False

class TutorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tutor'

    _llm_loaded = False

    def ready(self):
        if TutorConfig._llm_loaded:
            return

        if _should_skip_llm_init():
            TutorConfig._llm_loaded = True
            print("Skipping Gemini/LLM initialization for management command.")
            return

        TutorConfig._llm_loaded = True
        
        from django.conf import settings
        from . import globals  # a small module to hold the variables

        if settings.GEMINI_ENABLED:
            print("[ -- TEST MODE -- ] Initializing Gemini for testing")
        else:
            print("Initializing LLM...")
            from languagemodel_mistral import InitModel
            model, tokenizer = InitModel()
            globals.loaded_model = model
            globals.loaded_tokenizer = tokenizer
