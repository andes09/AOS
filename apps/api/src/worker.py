from celery import Celery
from celery.schedules import crontab
from src.config import settings

celery_app = Celery(
    "agile-os",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_transport_options={"socket_connect_timeout": 2, "socket_timeout": 2},
    broker_connection_retry=False,
)

# Import task modules so `celery -A src.worker worker` registers their
# @celery_app.task-decorated functions. Placed after celery_app is defined:
# events.py imports `celery_app` back from this module, and since it's
# already bound above by the time this runs, the circular import resolves
# cleanly (standard "import task modules at the bottom" Celery pattern).
from src.integrations.github import events as _github_events  # noqa: E402,F401

# Beat schedule — the reconciliation sweep is a safety net for missed GitHub
# webhook deliveries (see docs/plans/2026-07-20-github-task-autocomplete.md).
# Gated behind `experimental.github_autocomplete` the same way
# routers/github_webhooks.py gates the receiver itself: while the flag is
# off, no sweep is scheduled at all — the closest beat-schedule equivalent to
# the router's 404-while-disabled posture, since a cron entry has no
# per-request hook to gate individually.
if settings.is_feature_enabled("experimental.github_autocomplete"):
    celery_app.conf.beat_schedule = {
        "github-reconciliation-sweep": {
            "task": "src.integrations.github.events.github_reconciliation_sweep",
            "schedule": crontab(minute=0, hour="*/6"),
        },
    }
