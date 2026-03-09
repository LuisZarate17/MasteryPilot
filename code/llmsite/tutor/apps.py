# code/llmsite/tutor/apps.py
from django.apps import AppConfig
from languagemodel_mistral import InitModel

class TutorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tutor'

    _llm_loaded = False

    def ready(self):
        if TutorConfig._llm_loaded:
            return

        TutorConfig._llm_loaded = True
        
        from django.conf import settings
        from . import globals  # a small module to hold the variables

        if settings.GEMINI_ENABLED:
            print("[ -- TEST MODE -- ] Initializing Gemini for testing")
        else:
            print("Initializing LLM...")
            model, tokenizer = InitModel()
            globals.loaded_model = model
            globals.loaded_tokenizer = tokenizer
