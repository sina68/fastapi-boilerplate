"""Instant revocation: logout denylist and per-user not_before bumps."""

from __future__ import annotations

from helpers import (
    EMAIL,
    PASSWORD,
    promote_to_admin,
    user_headers,
)

ACCESS_TOKEN_TTL = 30 * 60


async def test_logout_denylist_entry_expires_with_the_token(client, headers, redis_client):
    from app.core.security import decode_access_token

    body = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    access = body.json()["access_token"]
    jti = str(decode_access_token(access)["jti"])

    assert await redis_client.get(f"denylist:jti:{jti}") is None

    # Log out the token we are inspecting (the fresh login above is its pair).
    logged_out = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": body.json()["refresh_token"]},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert logged_out.status_code == 204

    ttl = await redis_client.ttl(f"denylist:jti:{jti}")
    assert 0 < ttl <= ACCESS_TOKEN_TTL
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 401
    assert me.json()["code"] == "token_revoked"


async def test_fresh_login_after_logout_works(client, headers):
    body = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": body.json()["refresh_token"]},
        headers={"Authorization": f"Bearer {body.json()['access_token']}"},
    )
    again = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert again.status_code == 200
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {again.json()['access_token']}"},
    )
    assert me.status_code == 200


async def test_role_change_kills_existing_tokens_immediately(client, headers, session_maker):
    """Demote: the target's tokens must die on their next request."""
    await promote_to_admin(session_maker)
    await user_headers(client, email="target@example.com")
    await promote_to_admin(session_maker, email="target@example.com")
    target_headers = await user_headers(client, email="target@example.com")
    me = await client.get("/api/v1/auth/me", headers=target_headers)
    assert me.status_code == 200
    target_id = me.json()["id"]

    demoted = await client.patch(
        f"/api/v1/admin/users/{target_id}/role",
        json={"role": "user"},
        headers=headers,
    )
    assert demoted.status_code == 200

    after = await client.get("/api/v1/auth/me", headers=target_headers)
    assert after.status_code == 401
    assert after.json()["code"] == "token_revoked"

    # A fresh login is unaffected: not_before only kills pre-bump tokens.
    relogin = await user_headers(client, email="target@example.com")
    me_again = await client.get("/api/v1/auth/me", headers=relogin)
    assert me_again.status_code == 200


async def test_not_before_keys_expire_with_access_ttl(client, headers, session_maker, redis_client):
    """Revocation keys are TTL'd to the access-token lifetime: no leaks."""
    await promote_to_admin(session_maker)
    await user_headers(client, email="target@example.com")
    await promote_to_admin(session_maker, email="target@example.com")
    target_headers = await user_headers(client, email="target@example.com")
    me = await client.get("/api/v1/auth/me", headers=target_headers)
    target_id = me.json()["id"]

    await client.patch(
        f"/api/v1/admin/users/{target_id}/role",
        json={"role": "user"},
        headers=headers,
    )

    ttl = await redis_client.ttl(f"tokens:not_before:{target_id}")
    assert 0 < ttl <= ACCESS_TOKEN_TTL + 60


async def test_role_change_to_same_role_does_not_bump(client, headers, session_maker, redis_client):
    await promote_to_admin(session_maker)
    me = await client.get("/api/v1/auth/me", headers=headers)
    target_id = me.json()["id"]
    assert await redis_client.get(f"tokens:not_before:{target_id}") is None

    response = await client.patch(
        f"/api/v1/admin/users/{target_id}/role",
        json={"role": "admin"},
        headers=headers,
    )
    assert response.status_code == 200
    # No bump: nothing actually changed, and keys without cause are noise.
    assert await redis_client.get(f"tokens:not_before:{target_id}") is None
