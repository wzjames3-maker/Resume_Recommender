from django.apps import AppConfig


class HrConfig(AppConfig):
    name = "hr"
    verbose_name = "人事部"

    def ready(self):
        from hr import signals  # noqa: F401
