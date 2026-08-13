from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore

scheduler = BackgroundScheduler()
scheduler.add_jobstore(DjangoJobStore(), "default")


def clean_removed_trigger_jobs():
    """清理已删除 trigger 功能遗留的 APScheduler job；不影响其它核心 job。"""
    try:
        from django_apscheduler.models import DjangoJob

        DjangoJob.objects.filter(id__startswith="trigger:").delete()
    except Exception:
        pass


clean_removed_trigger_jobs()

try:
    scheduler.start()
except Exception as e:
    from common.utils.logger import maxkb_logger

    maxkb_logger.error(f"Failed to start scheduler: {e}")