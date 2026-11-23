"""Operator CLI: promotion is a role change, so it must bump ``not_before``
exactly like the admin API does."""

from __future__ import annotations

from app.core.roles import Role
from app.repositories import user as user_repo
from helpers import EMAIL, user_headers


async def test_promote_grants_admin_and_kills_pre_promotion_tokens(
    client, session_maker, redis_client
):
    from app.cli import promote

    stale_headers = await user_headers(client)

    assert await promote(EMAIL, session_maker=session_maker, redis=redis_client) is True

    async with session_maker() as session:
        user = await user_repo.get_by_email(session, EMAIL)
        assert user is not None
        assert user.role == Role.ADMIN.value
        assert await redis_client.get(f"tokens:not_before:{user.id}") is not None

    # A token minted before the promotion must not inherit the new role.
    stale = await client.get("/api/v1/auth/me", headers=stale_headers)
    assert stale.status_code == 401
    assert stale.json()["code"] == "token_revoked"


async def test_promote_unknown_email_returns_false(session_maker, redis_client):
    from app.cli import promote

    assert (
        await promote("nobody@example.com", session_maker=session_maker, redis=redis_client)
        is False
    )
