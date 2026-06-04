worker: cd apps/api && celery -A src.worker:celery_app worker --loglevel=info -Q celery
beat: cd apps/api && celery -A src.worker:celery_app beat --loglevel=info
