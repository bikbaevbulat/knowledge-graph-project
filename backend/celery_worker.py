# celery_worker.py
from backend.tasks import celery

celery.worker_main()
