from celery import Celery

from app.core.config import settings

celery_app = Celery("agentkb", broker=settings.redis_url, backend=settings.redis_url, include=["app.tasks.parse_document", "app.tasks.parse_resume"])
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.set_default()