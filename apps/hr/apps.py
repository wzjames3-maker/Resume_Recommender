from django.apps import AppConfig
from django.db.utils import DatabaseError


class HrConfig(AppConfig):
    name = "hr"
    verbose_name = "人事部"

    def ready(self):
        from django_celery_beat.models import CrontabSchedule, PeriodicTask

        try:
            crontab, _ = CrontabSchedule.objects.get_or_create(
                minute="0", hour="3", day_of_week="*", day_of_month="*", month_of_year="*"
            )
            PeriodicTask.objects.get_or_create(
                name="hr-cleanup-orphan-resumes",
                defaults={"task": "hr.task.resume.cleanup_orphan_resumes", "crontab": crontab},
            )
        except DatabaseError:
            pass
