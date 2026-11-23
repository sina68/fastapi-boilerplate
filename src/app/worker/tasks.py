"""Background tasks.

Copy the ``purge_expired_refresh_tokens`` shape for real work: a thin sync
task that runs one async function, so the async code stays testable without a
broker. Tasks take primitives (ids, strings), never ORM objects.

Retries are configured per task (not globally): exponential backoff with
jitter, capped at 10 minutes, 3 attempts. ``task_acks_late`` means a crashed
worker re-delivers the task, so every task must be idempotent — this one
deletes rows, so a duplicate run is a no-op.
"""

from __future__ import annotations

import asyncio

from app.db.session import dispose_engine, get_session_maker
from app.repositories import refresh_token as refresh_repo
from app.worker.celery_app import celery_app


@celery_app.task(name="app.ping")
def ping() -> str:
    """Liveness check for the worker: `celery -A ... call app.ping`."""
    return "pong"


@celery_app.task(
    name="app.purge_expired_refresh_tokens",
    autoretry_for=(Exception,),
    retry_backoff=True,  # 1s, 2s, 4s... by default
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def purge_expired_refresh_tokens() -> int:
    return asyncio.run(_purge_expired_refresh_tokens())


async def _purge_expired_refresh_tokens() -> int:
    try:
        async with get_session_maker()() as session:
            deleted = await refresh_repo.purge_expired(session)
            await session.commit()
            return deleted
    finally:
        await dispose_engine()
