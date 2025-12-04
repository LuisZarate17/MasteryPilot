from django.apps import AppConfig
from languagemodel import InitModel

class TutorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tutor'

    def ready(self):
        from django.conf import settings
        from . import globals  # a small module to hold the variables

        print("Initializing LLM in Django startup…")
        model, tokenizer = InitModel()
        globals.loaded_model = model
        globals.loaded_tokenizer = tokenizer