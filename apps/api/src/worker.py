from celery import Celery
from celery.schedules import crontab
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
    broker_transport_options={"socket_connect_timeout": 2, "socket_timeout": 2},
    broker_connection_retry=False,
)

celery_app.conf.beat_schedule = {
    "full-jira-sync-daily": {
        "task": "src.integrations.jira.sync.sync_all_teams",
        "schedule": crontab(hour=2, minute=0),   # 2am UTC daily
    },
    "incremental-jira-sync": {
        "task": "src.integrations.jira.sync.incremental_sync_all_teams",
        "schedule": crontab(minute="*/15"),        # every 15 minutes
    },
}
