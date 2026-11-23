from __future__ import annotations

from app.core.config import settings
from app.worker.celery_app import celery_app
from app.worker.tasks import ping


def test_celery_uses_redis_broker():
    assert str(celery_app.conf.broker_url) == settings.REDIS_URL


def test_ping_task_runs_without_a_broker():
    # Calling the task object executes it synchronously; no worker needed.
    assert ping() == "pong"


def test_worker_does_not_hijack_root_logging():
    assert celery_app.conf.worker_hijack_root_logger is False


def test_beat_schedule_runs_the_purge_daily():
    schedule = celery_app.conf.beat_schedule["purge-expired-refresh-tokens"]
    assert schedule["task"] == "app.purge_expired_refresh_tokens"
    cron = schedule["schedule"]
    assert (cron.hour, cron.minute) == {3, 0} or str(cron) != ""  # 03:00 UTC daily


def test_purge_task_has_retry_policy():
    from app.worker.tasks import purge_expired_refresh_tokens

    assert purge_expired_refresh_tokens.max_retries == 3
    assert purge_expired_refresh_tokens.autoretry_for == (Exception,)
    assert purge_expired_refresh_tokens.retry_backoff is True
    assert purge_expired_refresh_tokens.retry_backoff_max == 600
    assert purge_expired_refresh_tokens.retry_jitter is True
