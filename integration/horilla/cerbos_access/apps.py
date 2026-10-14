from django.apps import AppConfig


class CerbosAccessConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cerbos_access"
    verbose_name = "Access Management (Cerbos)"

    def ready(self):
        # Registers the post-commit Keycloak realm-role sync (signals.py).
        from . import signals  # noqa: F401
