"""Async Redis client used for rate limiting (and anything else you add later)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis

from app.core.config import settings

_client: Redis | None = None


def get_redis_client() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=settings.REDIS_SOCKET_TIMEOUT,
            health_check_interval=30,
        )
    return _client


async def get_redis() -> AsyncIterator[Redis]:
    yield get_redis_client()


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


RedisDep = Annotated[Redis, Depends(get_redis)]
