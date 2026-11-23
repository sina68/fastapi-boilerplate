from __future__ import annotations

import uuid

from app.core.security import create_access_token
from helpers import EMAIL, PASSWORD


async def test_register_returns_user_without_secrets(client):
    response = await client.post(
        "/api/v1/auth/register", json={"email": EMAIL, "password": PASSWORD}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == EMAIL
    assert body["is_active"] is True
    assert "password" not in body
    assert "password_hash" not in body


async def test_register_rejects_duplicate_email(client):
    payload = {"email": EMAIL, "password": PASSWORD}
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    duplicate = await client.post("/api/v1/auth/register", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "email_taken"


async def test_register_rejects_short_password(client):
    response = await client.post(
        "/api/v1/auth/register", json={"email": "x@example.com", "password": "short"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_register_normalizes_email_case(client):
    await client.post(
        "/api/v1/auth/register", json={"email": "MiXeD@Example.com", "password": PASSWORD}
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": "mixed@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200


async def test_login_returns_bearer_token(client, headers):
    response = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] > 0


async def test_login_rejects_wrong_password(client, headers):
    response = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "wrong-password-123"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


async def test_login_does_not_reveal_unknown_email(client):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": PASSWORD},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


async def test_me_requires_token(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["code"] == "missing_token"


async def test_me_rejects_garbage_token(client):
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_token"


async def test_me_rejects_expired_token(client, headers):
    me = await client.get("/api/v1/auth/me", headers=headers)
    user_id = me.json()["id"]
    expired = create_access_token(user_id, ttl_minutes=-1)
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


async def test_me_rejects_token_for_missing_user(client):
    token = create_access_token(str(uuid.uuid4()))
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_me_returns_current_user(client, headers):
    response = await client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["email"] == EMAIL


async def test_login_is_rate_limited(client, headers, redis_client):
    from app.core.config import settings as app_settings

    limit = app_settings.AUTH_RATE_LIMIT_PER_MINUTE
    await redis_client.flushdb()  # start from an empty budget
    for _ in range(limit):
        allowed = await client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": "wrong-password-1"}
        )
        assert allowed.status_code == 401
    blocked = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "wrong-password-1"}
    )
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "rate_limited"
    assert "Retry-After" in blocked.headers


async def test_missing_token_advertises_the_bearer_scheme(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_me_rejects_a_token_that_is_not_an_access_token(client, headers):
    from datetime import UTC, datetime, timedelta

    import jwt

    from app.core.config import settings

    me = await client.get("/api/v1/auth/me", headers=headers)
    now = datetime.now(UTC)
    foreign = jwt.encode(
        {
            "sub": me.json()["id"],
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "jti": "some-jti",
            "type": "refresh",
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {foreign}"})
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_token"


async def test_login_accepts_a_password_shorter_than_the_register_policy(client, session_maker):
    """A pre-existing (or imported) short password must fail as bad
    credentials, not be rejected by the login schema with 422."""
    from app.core.security import hash_password
    from app.repositories import user as user_repo

    async with session_maker() as session:
        await user_repo.create(
            session, email="legacy@example.com", password_hash=hash_password("old-short")
        )
        await session.commit()

    right = await client.post(
        "/api/v1/auth/login", json={"email": "legacy@example.com", "password": "old-short"}
    )
    assert right.status_code == 200

    wrong = await client.post(
        "/api/v1/auth/login", json={"email": "legacy@example.com", "password": "nope-short"}
    )
    assert wrong.status_code == 401
    assert wrong.json()["code"] == "invalid_credentials"


async def test_register_maps_a_unique_violation_to_409(client, monkeypatch):
    """Two concurrent registrations can both pass the lookup; the unique index
    is the real arbiter and must produce 409, not a 500."""
    from app.repositories import user as user_repo

    async def always_missing(*args, **kwargs):
        return None

    monkeypatch.setattr(user_repo, "get_by_email", always_missing)
    payload = {"email": "race@example.com", "password": PASSWORD}
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201

    duplicate = await client.post("/api/v1/auth/register", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "email_taken"
