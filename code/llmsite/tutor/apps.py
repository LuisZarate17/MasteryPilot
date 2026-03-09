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
    return ("test" in argv) or any("pytest" in a for a in argv)

class TutorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tutor'

    _llm_loaded = False

    def ready(self):
        if TutorConfig._llm_loaded:
            return

        if _should_skip_llm_init():
            TutorConfig._llm_loaded = True
            print("Skipping Gemini/LLM initialization for test run.")
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
