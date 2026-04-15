from django.apps import AppConfig


class UserConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "user"
    verbose_name = "Пользователи"

    def ready(self):
        from . import signals  # noqa: F401
