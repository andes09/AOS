import logging
import uuid

from celery import Celery
from celery.schedules import crontab
from celery.signals import (
    setup_logging as celery_setup_logging,
    task_failure,
    task_prerun,
    task_retry,
    worker_ready,
    worker_shutdown,
)

from src.config import settings
from src.logging_config import request_id_var, setup_logging

logger = logging.getLogger(__name__)


@celery_setup_logging.connect
def _configure_celery_logging(**_kwargs) -> None:
    """Stop Celery replacing the root logger config with its own.

    Connecting to this signal disables Celery's default logging setup entirely,
    so worker output uses the same format/handler as the API — one log shape
    across both processes.
    """
    setup_logging(force=True)


@task_prerun.connect
def _bind_task_context(task_id=None, task=None, **_kwargs) -> None:
    """Give every task run a correlation id, mirroring the API's request id."""
    request_id_var.set(task_id or uuid.uuid4().hex)
    logger.info("task started", extra={"task_name": getattr(task, "name", None), "task_id": task_id})


@task_failure.connect
def _log_task_failure(task_id=None, exception=None, sender=None, einfo=None, **_kwargs) -> None:
    """Celery swallows task exceptions into the result backend by default.

    Without this the only trace of a failed background job is a `FAILURE`
    result nobody reads — the roadmap prewarm and GitHub reconciliation sweep
    would fail completely silently.
    """
    logger.error(
        "task FAILED: %s", getattr(sender, "name", "unknown"),
        exc_info=(type(exception), exception, exception.__traceback__) if exception else None,
        extra={"task_name": getattr(sender, "name", None), "task_id": task_id},
    )


@task_retry.connect
def _log_task_retry(request=None, reason=None, sender=None, **_kwargs) -> None:
    logger.warning(
        "task retrying: %s (%s)", getattr(sender, "name", "unknown"), reason,
        extra={"task_name": getattr(sender, "name", None), "reason": str(reason)},
    )


@worker_ready.connect
def _log_worker_ready(**_kwargs) -> None:
    logger.info("celery worker ready", extra={"environment": settings.environment})


@worker_shutdown.connect
def _log_worker_shutdown(**_kwargs) -> None:
    logger.info("celery worker shutting down")


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
from src.services import github_classifier as _github_classifier  # noqa: E402,F401
from src.services import roadmap_generator as _roadmap_generator  # noqa: E402,F401

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
    logger.info("beat schedule registered: github-reconciliation-sweep every 6h")
else:
    logger.info(
        "experimental.github_autocomplete disabled — no reconciliation sweep scheduled"
    )
