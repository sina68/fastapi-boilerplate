"""Refresh token persistence. Tokens are looked up by hash, never by raw value."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken


async def create(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    token_hash: str,
    expires_at: datetime,
) -> RefreshToken:
    token = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    session.add(token)
    await session.flush()
    return token


async def get_by_hash(session: AsyncSession, token_hash: str) -> RefreshToken | None:
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    return result.scalar_one_or_none()


async def revoke(session: AsyncSession, token: RefreshToken, *, at: datetime) -> None:
    token.revoked_at = at
    await session.flush()


async def claim_rotation(
    session: AsyncSession,
    token_id: uuid.UUID,
    *,
    at: datetime,
    successor_token_hash: str,
) -> bool:
    """Atomically flip an unrevoked row to revoked.

    A read-then-write would let two concurrent refreshes of the same token both
    pass the check and mint two live sessions. The ``revoked_at IS NULL``
    predicate is the lock: exactly one UPDATE can win, everyone else gets 0
    rows and must treat the token as already rotated.
    """
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=at, successor_token_hash=successor_token_hash)
            .execution_options(synchronize_session=False)
        ),
    )
    return int(result.rowcount or 0) == 1


async def claim_grace(session: AsyncSession, token_id: uuid.UUID, *, at: datetime) -> bool:
    """Spend the one-time reuse grace for a rotated row, atomically.

    Two concurrent retries must not both be honored: the ``grace_used_at IS
    NULL`` predicate makes the second one lose and fall through to theft
    handling.
    """
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.id == token_id,
                RefreshToken.grace_used_at.is_(None),
                RefreshToken.revoked_at.is_not(None),
            )
            .values(grace_used_at=at)
            .execution_options(synchronize_session=False)
        ),
    )
    return int(result.rowcount or 0) == 1


async def revoke_all_for_user(session: AsyncSession, user_id: uuid.UUID, *, at: datetime) -> int:
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=at)
        ),
    )
    return int(result.rowcount or 0)


async def purge_expired(session: AsyncSession) -> int:
    result = cast(
        CursorResult[Any],
        await session.execute(
            delete(RefreshToken).where(RefreshToken.expires_at < datetime.now(UTC))
        ),
    )
    return int(result.rowcount or 0)
