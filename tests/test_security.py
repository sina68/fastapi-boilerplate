from __future__ import annotations

import asyncio

import pytest
from prometheus_client import REGISTRY
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import redact
from app.core.security import hash_password, verify_password

LONG_SECRET = "a" * 40


def _metric(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_security_headers_are_set(client):
    response = await client.get("/health/liveness")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


async def test_api_responses_are_not_cached(client):
    response = await client.get("/api/v1/items", headers={"Authorization": "Bearer x"})
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


async def test_request_id_is_echoed(client):
    response = await client.get("/health/liveness", headers={"X-Request-ID": "abc123"})
    assert response.headers["x-request-id"] == "abc123"


async def test_request_id_is_generated_when_missing(client):
    response = await client.get("/health/liveness")
    assert len(response.headers["x-request-id"]) == 32


async def test_oversized_body_is_rejected_before_parsing(client):
    response = await client.post(
        "/api/v1/auth/login",
        content=b'{"email":"a@b.c","password":"' + b"x" * 3000 + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"


async def test_chunked_body_is_rejected_without_content_length(client):
    async def chunks():
        for _ in range(10):
            yield b'{"email":"a@b.c","padding":"' + b"x" * 400 + b'"}'

    response = await client.post(
        "/api/v1/auth/login", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"


async def test_body_cap_exemption_matches_path_segments_only(client):
    """The upload exemption must not leak to a sibling path that merely shares
    the prefix, or a future route could silently lose its body cap."""
    response = await client.post(
        "/api/v1/uploads-internal",
        content=b"x" * 3000,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"


async def test_rate_limit_counters_live_in_redis(client, redis_client):
    await client.get("/api/v1/items", headers={"Authorization": "Bearer nope"})
    assert await redis_client.keys("ratelimit:items:*")
    await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "x" * 12}
    )
    assert await redis_client.keys("ratelimit:auth:login:*")


async def test_metrics_endpoint_exposes_request_counters(client):
    await client.get("/health/liveness")
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text
    assert 'route="/metrics"' not in response.text


async def test_oversized_body_still_gets_security_headers_and_request_id(client):
    """The 413 is produced in a middleware, so it must pass through the
    security-header and request-id layers like any other response."""
    response = await client.post(
        "/api/v1/auth/login",
        content=b'{"email":"a@b.c","password":"' + b"x" * 3000 + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert len(response.headers["x-request-id"]) == 32


async def test_rejected_bodies_are_counted_in_metrics(client):
    # The body cap rejects before routing, so the metric carries the
    # "unmatched" route label; what matters is that the 413 is counted at all.
    labels = {"method": "POST", "route": "unmatched", "status": "413"}
    before = _metric("http_requests_total", **labels)
    await client.post(
        "/api/v1/auth/login",
        content=b'{"email":"a@b.c","password":"' + b"x" * 3000 + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert _metric("http_requests_total", **labels) == before + 1


async def test_rate_limit_window_does_not_slide(redis_client):
    """A steady trickle must not extend the window: the TTL is set on the first
    hit only, so the budget resets after `window` seconds regardless."""
    from app.core.ratelimit import hit_rate_limit

    async def hit() -> bool:
        return await hit_rate_limit(
            redis_client, scope="test:window", key_suffix="ip", limit=2, window=2
        )

    assert await hit() is True
    await asyncio.sleep(1.0)
    assert await hit() is True
    await asyncio.sleep(1.5)  # 2.5s after the first hit, 1.5s after the second
    # Fixed window: expired at 2.0s. A sliding TTL refreshed on the second hit
    # would keep the key alive until 3.0s and reject this as the third hit.
    assert await hit() is True


def test_redact_masks_nested_sensitive_keys():
    payload = {
        "email": "a@b.c",
        "password": "plain-text",
        "nested": {"access_token": "jwt-value", "ok": 1},
        "list": [{"secret": "nope"}],
    }
    cleaned = redact(payload)
    assert cleaned["email"] == "a@b.c"
    assert cleaned["password"] == "***"
    assert cleaned["nested"]["access_token"] == "***"
    assert cleaned["nested"]["ok"] == 1
    assert cleaned["list"][0]["secret"] == "***"


def test_password_hashing_roundtrip():
    hashed = hash_password("s3cret-password-value")
    assert hashed != "s3cret-password-value"
    assert verify_password("s3cret-password-value", hashed)
    assert not verify_password("wrong-password-value", hashed)
    assert not verify_password("anything", "not-a-hash")


def test_jwt_secret_must_be_long_enough():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, JWT_SECRET="too-short")


def test_jwt_secret_must_not_be_a_placeholder():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, JWT_SECRET="changeme" * 5)


def test_production_forbids_debug():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            DEBUG=True,
            JWT_SECRET=LONG_SECRET,
            CORS_ORIGINS=["https://app.example.com"],
        )


def test_production_forbids_wildcard_cors():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            JWT_SECRET=LONG_SECRET,
            CORS_ORIGINS=["*"],
        )


def test_production_requires_cors_origins():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ENVIRONMENT="production", JWT_SECRET=LONG_SECRET)
