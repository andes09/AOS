from celery import Celery
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
