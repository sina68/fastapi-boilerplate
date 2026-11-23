"""Redis-backed fixed-window rate limiting, keyed by route scope + client IP.

The window starts on the first hit and does not move: the TTL is set once
(``SET ... NX EX``), so a steady stream of requests still expires after
``window`` seconds instead of extending the window forever. It fails open when
Redis is unreachable: losing rate limiting beats rejecting all traffic, and
the failure is logged and counted.

``hit_rate_limit`` is the primitive; the FastAPI dependency and the sqladmin
login backend both call it, so app routes and the admin form share one
implementation.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.exceptions import RateLimited
from app.core.metrics import RATE_LIMIT_FAILURES
from app.db.redis import RedisDep

logger = logging.getLogger(__name__)


def client_ip(request: Request) -> str:
    # Only the socket peer is trustworthy. X-Forwarded-For is client-controlled
    # unless a proxy you own rewrites it; if you have one, opt in explicitly.
    return request.client.host if request.client else "unknown"


async def hit_rate_limit(
    redis: Redis, *, scope: str, key_suffix: str, limit: int, window: int
) -> bool:
    """Count one hit. True = allowed, False = over the limit. Fail-open."""
    if limit <= 0:
        return True
    key = f"ratelimit:{scope}:{key_suffix}"
    try:
        async with redis.pipeline(transaction=True) as pipe:
            # NX + EX: only the first hit in the window creates the key and
            # sets its TTL. A plain EXPIRE on every hit slides the window and
            # never lets it reset while the client keeps sending.
            pipe.set(key, 0, ex=window, nx=True)
            pipe.incr(key)
            count = int((await pipe.execute())[1])
    except RedisError:
        RATE_LIMIT_FAILURES.labels(scope=scope).inc()
        logger.warning("ratelimit.unavailable", extra={"scope": scope})
        return True
    return count <= limit


def rate_limit(
    scope: str,
    limit: int,
    window_seconds: int | None = None,
) -> Callable[[Request, RedisDep], Awaitable[None]]:
    window = window_seconds or settings.RATE_LIMIT_WINDOW_SECONDS

    async def dependency(request: Request, redis: RedisDep) -> None:
        allowed = await hit_rate_limit(
            redis,
            scope=scope,
            key_suffix=client_ip(request),
            limit=limit,
            window=window,
        )
        if not allowed:
            raise RateLimited(headers={"Retry-After": str(window)})

    return dependency
