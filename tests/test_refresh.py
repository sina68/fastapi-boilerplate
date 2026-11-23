from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.repositories import refresh_token as refresh_repo
from app.repositories import user as user_repo
from app.services.auth import hash_refresh_token
from helpers import EMAIL, PASSWORD


async def _login(client, email: str = EMAIL, password: str = PASSWORD) -> dict:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


async def test_login_returns_access_and_refresh_tokens(client, headers):
    body = await _login(client)
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] > 0
    assert body["refresh_expires_in"] > 0


async def test_refresh_returns_a_new_pair(client, headers):
    body = await _login(client)
    refreshed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert refreshed.status_code == 200
    new_pair = refreshed.json()
    assert new_pair["access_token"] != body["access_token"]
    assert new_pair["refresh_token"] != body["refresh_token"]


async def test_refresh_records_the_successor_and_revokes_the_old_row(
    client, headers, session_maker
):
    body = await _login(client)
    first = await client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert first.status_code == 200

    async with session_maker() as session:
        old = await refresh_repo.get_by_hash(session, hash_refresh_token(body["refresh_token"]))
    assert old is not None
    assert old.revoked_at is not None
    # The grace retry for this row is now spent: a second presentation is fatal.
    assert old.successor_token_hash == hash_refresh_token(first.json()["refresh_token"])


async def test_network_retry_inside_grace_is_honored_once(client, headers):
    """A dropped response looks identical to theft: allow exactly one retry."""
    body = await _login(client)
    first = await client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert first.status_code == 200

    retry = await client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert retry.status_code == 200
    retry_pair = retry.json()
    assert retry_pair["refresh_token"] not in {
        body["refresh_token"],
        first.json()["refresh_token"],
    }

    # Third presentation of the same row: the grace is spent, so this is theft.
    again = await client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert again.status_code == 401
    assert again.json()["code"] == "refresh_token_reused"

    # Family revoked: neither token issued during rotation works anymore.
    for stale in (first.json()["refresh_token"], retry_pair["refresh_token"]):
        response = await client.post("/api/v1/auth/refresh", json={"refresh_token": stale})
        assert response.status_code == 401


async def test_replay_outside_grace_kills_the_family(client, headers, session_maker):
    body = await _login(client)
    first = await client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert first.status_code == 200

    async with session_maker() as session:
        old = await refresh_repo.get_by_hash(session, hash_refresh_token(body["refresh_token"]))
        old.revoked_at = datetime.now(UTC) - timedelta(seconds=60)
        await session.commit()

    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert replay.status_code == 401
    assert replay.json()["code"] == "refresh_token_reused"

    family = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first.json()["refresh_token"]}
    )
    assert family.status_code == 401


async def test_grace_can_be_disabled(client, headers, monkeypatch):
    from app.core.config import settings as app_settings

    body = await _login(client)
    first = await client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert first.status_code == 200

    monkeypatch.setattr(app_settings, "REFRESH_REUSE_GRACE_SECONDS", 0)
    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert replay.status_code == 401
    assert replay.json()["code"] == "refresh_token_reused"


async def test_refresh_rejects_unknown_token(client):
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": "x" * 64})
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_refresh_token"


async def test_refresh_rejects_expired_token(client, headers, session_maker):
    async with session_maker() as session:
        user = await user_repo.get_by_email(session, EMAIL)
        raw = "expired-token-value-0123456789"
        await refresh_repo.create(
            session,
            user_id=user.id,
            token_hash=hash_refresh_token(raw),
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        await session.commit()

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": raw})
    assert response.status_code == 401
    assert response.json()["code"] == "refresh_token_expired"


async def test_logout_kills_the_refresh_and_the_presented_access_token(client, headers):
    body = await _login(client)
    logged_out = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": body["refresh_token"]},
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert logged_out.status_code == 204

    reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert reuse.status_code == 401

    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 401
    assert me.json()["code"] == "token_revoked"


async def test_logout_without_bearer_is_rejected(client, headers):
    body = await _login(client)
    response = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": body["refresh_token"]}
    )
    assert response.status_code == 401


async def test_logout_with_unknown_refresh_still_kills_access_token(client, headers):
    body = await _login(client)
    response = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": "unknown-token-value-12345"},
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert response.status_code == 204
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 401
    assert me.json()["code"] == "token_revoked"


async def test_purge_expired_tokens_only_deletes_expired(client, headers, session_maker):
    async with session_maker() as session:
        user = await user_repo.get_by_email(session, EMAIL)
        await refresh_repo.create(
            session,
            user_id=user.id,
            token_hash="a" * 64,
            expires_at=datetime.now(UTC) - timedelta(days=2),
        )
        await refresh_repo.create(
            session,
            user_id=user.id,
            token_hash="b" * 64,
            expires_at=datetime.now(UTC) + timedelta(days=2),
        )
        await session.commit()

        deleted = await refresh_repo.purge_expired(session)
        await session.commit()

    assert deleted >= 1
    async with session_maker() as session:
        assert await refresh_repo.get_by_hash(session, "b" * 64) is not None
        assert await refresh_repo.get_by_hash(session, "a" * 64) is None


async def test_new_user_starts_with_the_user_role(client):
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": "fresh@example.com", "password": PASSWORD},
    )
    assert registered.status_code == 201
    assert registered.json()["role"] == "user"


async def test_rotation_claim_can_only_be_won_once(client, headers, session_maker):
    """The revoked_at IS NULL predicate is the concurrency lock: a second
    UPDATE (a racing refresh) must see 0 rows, not rotate again."""
    body = await _login(client)
    digest = hash_refresh_token(body["refresh_token"])

    async with session_maker() as session:
        token = await refresh_repo.get_by_hash(session, digest)
        assert token is not None
        won = await refresh_repo.claim_rotation(
            session, token.id, at=datetime.now(UTC), successor_token_hash="a" * 64
        )
        assert won is True
        await session.commit()

    async with session_maker() as session:
        token = await refresh_repo.get_by_hash(session, digest)
        assert token is not None
        lost = await refresh_repo.claim_rotation(
            session, token.id, at=datetime.now(UTC), successor_token_hash="b" * 64
        )
        assert lost is False


async def test_grace_claim_can_only_be_spent_once(client, headers, session_maker):
    body = await _login(client)
    first = await client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert first.status_code == 200

    digest = hash_refresh_token(body["refresh_token"])
    async with session_maker() as session:
        token = await refresh_repo.get_by_hash(session, digest)
        assert token is not None
        assert await refresh_repo.claim_grace(session, token.id, at=datetime.now(UTC)) is True
        await session.commit()

    async with session_maker() as session:
        token = await refresh_repo.get_by_hash(session, digest)
        assert token is not None
        assert await refresh_repo.claim_grace(session, token.id, at=datetime.now(UTC)) is False
