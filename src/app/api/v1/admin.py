"""Admin-only API. Every route depends on AdminUser, not just CurrentUser."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, RedisDep, SessionDep
from app.schemas.user import RoleUpdate, UserListOut, UserOut
from app.services import user as user_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=UserListOut)
async def list_users(
    session: SessionDep,
    _: AdminUser,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> UserListOut:
    return await user_service.list_users(session, limit=limit, offset=offset)


@router.patch("/users/{user_id}/role", response_model=UserOut)
async def change_user_role(
    user_id: uuid.UUID, payload: RoleUpdate, session: SessionDep, redis: RedisDep, _: AdminUser
) -> UserOut:
    """Promote or demote. A demoted admin's existing tokens stop working on
    their next request (not_before bump), not when they expire."""
    return await user_service.change_role(session, redis, user_id=user_id, role=payload.role)
