from celery import Celery
from src.config import settings

celery_app = Celery(
    "agile-os",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["src.integrations.jira.sync"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
