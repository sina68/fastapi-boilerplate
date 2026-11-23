"""Access-token revocation state in Redis.

Two mechanisms, one check (``is_token_denied``):

1. ``denylist:jti:<jti>`` — a single token (the one presented at logout),
   TTL'd to its own remaining lifetime: no point storing the entry longer.
2. ``tokens:not_before:<user_id>`` — an epoch timestamp in **milliseconds**;
   every token minted at or before it is dead. Set on role changes so a demoted
   admin loses access on their next request. TTL is the access-token lifetime
   plus slack: after that, every pre-bump token has expired naturally, so the
   key is garbage and must not linger (keys without TTL are leaks).

Every path fails open when Redis is unreachable — the API keeps serving, but
revocation is best-effort. Each failure increments ``revocation_failures_total``
so ``deploy/prometheus/alerts.yml`` can page on it. Log warnings alone are not
an alerting strategy.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.metrics import REVOCATION_FAILURES

logger = logging.getLogger(__name__)

_DENY_PREFIX = "denylist:jti:"
_NOT_BEFORE_PREFIX = "tokens:not_before:"


def _record_failure(reason: str, **extra: object) -> None:
    REVOCATION_FAILURES.labels(reason=reason).inc()
    logger.warning("revocation.unavailable", extra=extra)


async def deny_access_token(redis: Redis, *, jti: str, ttl_seconds: int) -> None:
    try:
        await redis.set(_DENY_PREFIX + jti, "1", ex=max(1, int(ttl_seconds)))
    except RedisError:
        # Logout already revoked the refresh token; the access token simply
        # lives out its (short) remaining lifetime. Never turn this into a 500:
        # the user must still be able to log out during a Redis outage.
        _record_failure("write_failed")


async def bump_not_before(redis: Redis, *, user_id: str, access_ttl_seconds: int) -> None:
    # TTL = access lifetime + 60s slack; older tokens are expired by then.
    try:
        await redis.set(
            _NOT_BEFORE_PREFIX + user_id,
            int(datetime.now(UTC).timestamp() * 1000),
            ex=access_ttl_seconds + 60,
        )
    except RedisError:
        # The role change itself is committed; authorization re-reads the role
        # from the DB on every request, so a demotion still takes effect. The
        # bump is what kills the stale session outright.
        _record_failure("write_failed")


async def is_token_denied(redis: Redis, *, jti: str, user_id: str, iat_ms: int) -> bool:
    try:
        denied, not_before = await redis.mget(_DENY_PREFIX + jti, _NOT_BEFORE_PREFIX + user_id)
    except RedisError:
        _record_failure("read_failed", user_id=user_id)
        return False

    if denied is not None:
        return True
    if not_before is not None:
        return iat_ms <= int(not_before)
    return False
