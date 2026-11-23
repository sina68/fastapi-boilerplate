from __future__ import annotations

import uuid

from helpers import (
    EMAIL,
    promote_to_admin,
    user_headers,
)

ADMIN_USERS_URL = "/api/v1/admin/users"


async def test_admin_api_requires_authentication(client):
    assert (await client.get(ADMIN_USERS_URL)).status_code == 401


async def test_admin_api_rejects_regular_user(client, headers):
    response = await client.get(ADMIN_USERS_URL, headers=headers)
    assert response.status_code == 403
    assert response.json()["code"] == "admin_required"


async def test_admin_can_list_users(client, headers, session_maker):
    await promote_to_admin(session_maker)
    response = await client.get(ADMIN_USERS_URL, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["email"] == EMAIL
    assert body["items"][0]["role"] == "admin"


async def test_admin_can_promote_another_user(client, headers, session_maker):
    other_headers = await user_headers(client, email="other@example.com")
    await promote_to_admin(session_maker)

    with_user = await client.get(ADMIN_USERS_URL, headers=headers)
    target = next(
        user for user in with_user.json()["items"] if user["email"] == "other@example.com"
    )

    promoted = await client.patch(
        f"{ADMIN_USERS_URL}/{target['id']}/role",
        json={"role": "admin"},
        headers=headers,
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"

    # Role change bumps not_before, so the promoted user's OLD token is dead...
    stale = await client.get(ADMIN_USERS_URL, headers=other_headers)
    assert stale.status_code == 401
    assert stale.json()["code"] == "token_revoked"

    # ...and a fresh login carries the new role.
    fresh_headers = await user_headers(client, email="other@example.com")
    assert (await client.get(ADMIN_USERS_URL, headers=fresh_headers)).status_code == 200


async def test_non_admin_cannot_change_roles(client, headers):
    other_headers = await user_headers(client, email="other@example.com")
    me = await client.get("/api/v1/auth/me", headers=headers)
    response = await client.patch(
        f"{ADMIN_USERS_URL}/{me.json()['id']}/role",
        json={"role": "admin"},
        headers=other_headers,
    )
    assert response.status_code == 403


async def test_role_change_validates_the_role_name(client, headers, session_maker):
    await promote_to_admin(session_maker)
    me = await client.get("/api/v1/auth/me", headers=headers)
    response = await client.patch(
        f"{ADMIN_USERS_URL}/{me.json()['id']}/role",
        json={"role": "superuser"},
        headers=headers,
    )
    assert response.status_code == 422


async def test_role_change_unknown_user_is_404(client, headers, session_maker):
    await promote_to_admin(session_maker)
    response = await client.patch(
        f"{ADMIN_USERS_URL}/{uuid.uuid4()}/role",
        json={"role": "user"},
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["code"] == "user_not_found"


async def test_demoted_admin_loses_access_immediately(client, headers, session_maker):
    await promote_to_admin(session_maker)
    me = await client.get("/api/v1/auth/me", headers=headers)
    demoted = await client.patch(
        f"{ADMIN_USERS_URL}/{me.json()['id']}/role", json={"role": "user"}, headers=headers
    )
    assert demoted.status_code == 200
    # The demoted admin's own token died with the bump; re-login to see the 403.
    after = await client.get(ADMIN_USERS_URL, headers=headers)
    assert after.status_code == 401
    fresh_headers = await user_headers(client, email="user@example.com")
    assert (await client.get(ADMIN_USERS_URL, headers=fresh_headers)).status_code == 403
