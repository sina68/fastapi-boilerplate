"""Celery app. Broker/result backend reuse REDIS_URL.

Worker:  celery -A app.worker.celery_app worker --loglevel=INFO
Beat:     celery -A app.worker.celery_app beat --loglevel=INFO
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "app",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_time_limit=300,
    task_soft_time_limit=240,
    # Never let Celery swap the app's logging config out from under us.
    worker_hijack_root_logger=False,
    broker_connection_retry_on_startup=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        # Periodic hygiene: refresh tokens past their expiry are deleted daily
        # at 03:00 UTC (low-traffic hour). Add real jobs next to this one.
        "purge-expired-refresh-tokens": {
            "task": "app.purge_expired_refresh_tokens",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)
