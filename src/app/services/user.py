"""User administration (admin-only, see app/api/v1/admin.py)."""

from __future__ import annotations

import uuid

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import denylist
from app.core.config import settings
from app.core.exceptions import NotFound
from app.repositories import user as user_repo
from app.schemas.user import RoleName, UserListOut, UserOut


async def list_users(session: AsyncSession, *, limit: int, offset: int) -> UserListOut:
    users, total = await user_repo.list_all(session, limit=limit, offset=offset)
    return UserListOut(
        items=[UserOut.model_validate(user) for user in users],
        total=total,
        limit=limit,
        offset=offset,
    )


async def change_role(
    session: AsyncSession,
    redis: Redis,
    *,
    user_id: uuid.UUID,
    role: RoleName,
) -> UserOut:
    user = await user_repo.get_by_id(session, user_id)
    if user is None:
        raise NotFound("User not found", code="user_not_found")
    if user.role == role:
        return UserOut.model_validate(user)

    user.role = role
    await session.commit()

    # Every token minted so far carries the old role inside its 30-minute
    # window. Bump not_before so all of them die on their next request; new
    # logins are unaffected. This is what makes demotion immediate.
    await denylist.bump_not_before(
        redis,
        user_id=str(user_id),
        access_ttl_seconds=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
    )
    return UserOut.model_validate(user)
