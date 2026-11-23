"""Fail-open must be measurable: the counters behind the alerts, and the rules
file that turns them into pages."""

from __future__ import annotations

from pathlib import Path

import pytest
from prometheus_client import REGISTRY
from redis.exceptions import RedisError

from app.core import denylist, ratelimit

ALERTS = Path(__file__).resolve().parent.parent / "deploy" / "prometheus" / "alerts.yml"
REVOCATION = "revocation_failures_total"
RATE_LIMIT = "ratelimit_failures_total"


class BrokenRedis:
    """Every operation fails the way an unreachable Redis does."""

    async def mget(self, *keys: str) -> list[None]:
        raise RedisError("connection refused")

    async def set(self, *args: object, **kwargs: object) -> None:
        raise RedisError("connection refused")

    def pipeline(self, transaction: bool = True) -> object:
        raise RedisError("connection refused")


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_revocation_read_fails_open_and_counts():
    before = sample(REVOCATION, reason="read_failed")
    denied = await denylist.is_token_denied(
        BrokenRedis(),
        jti="j",
        user_id="u",
        iat_ms=1,  # type: ignore[arg-type]
    )
    assert denied is False
    assert sample(REVOCATION, reason="read_failed") == before + 1


async def test_deny_write_fails_open_and_counts():
    before = sample(REVOCATION, reason="write_failed")
    # Must not raise: a Redis outage cannot block logout.
    await denylist.deny_access_token(BrokenRedis(), jti="j", ttl_seconds=60)  # type: ignore[arg-type]
    assert sample(REVOCATION, reason="write_failed") == before + 1


async def test_bump_write_fails_open_and_counts():
    before = sample(REVOCATION, reason="write_failed")
    # Must not raise: the role change is already committed.
    await denylist.bump_not_before(BrokenRedis(), user_id="u", access_ttl_seconds=60)  # type: ignore[arg-type]
    assert sample(REVOCATION, reason="write_failed") == before + 1


async def test_rate_limit_fails_open_and_counts():
    before = sample(RATE_LIMIT, scope="test:fail_open")
    allowed = await ratelimit.hit_rate_limit(
        BrokenRedis(),  # type: ignore[arg-type]
        scope="test:fail_open",
        key_suffix="127.0.0.1",
        limit=1,
        window=60,
    )
    assert allowed is True
    assert sample(RATE_LIMIT, scope="test:fail_open") == before + 1


async def test_logout_survives_redis_outage(client, headers, test_app):
    """A Redis outage must not stop users from ending their session."""
    from app.db.redis import get_redis

    body = await client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "correct-horse-battery"},
    )
    assert body.status_code == 200
    pair = body.json()

    working = test_app.dependency_overrides[get_redis]
    test_app.dependency_overrides[get_redis] = lambda: BrokenRedis()
    try:
        logged_out = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": pair["refresh_token"]},
            headers={"Authorization": f"Bearer {pair['access_token']}"},
        )
        assert logged_out.status_code == 204
        # The DB side of logout still worked even though Redis did not.
        reuse = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]}
        )
        assert reuse.status_code == 401
    finally:
        test_app.dependency_overrides[get_redis] = working


def test_alerts_reference_the_counters():
    text = ALERTS.read_text(encoding="utf-8")
    assert "revocation_failures_total" in text
    assert "ratelimit_failures_total" in text
    assert "RevocationCheckFailing" in text
    assert "RateLimitUnavailable" in text
    # Minimal structural sanity without pulling a YAML parser into deps.
    assert "groups:" in text
    assert text.count("alert:") >= 3
    assert "for: 5m" in text


@pytest.mark.parametrize("path", ["deploy/prometheus/alerts.yml"])
def test_alert_file_exists(path: str) -> None:
    assert (Path(__file__).resolve().parent.parent / path).is_file()
