"""Shared dependencies: DB session, authenticated user, role checks."""

from __future__ import annotations

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import denylist
from app.core.exceptions import Forbidden, Unauthorized
from app.core.roles import Role
from app.core.security import decode_access_token
from app.db.redis import get_redis
from app.db.session import get_session
from app.models.user import User
from app.repositories import user as user_repo

SessionDep = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]

_bearer = HTTPBearer(auto_error=False)
BearerDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


def _unauthorized(detail: str, code: str) -> Unauthorized:
    # RFC 6750: a bearer-protected resource must advertise the scheme.
    return Unauthorized(detail, code=code, headers={"WWW-Authenticate": "Bearer"})


async def get_current_user(
    request: Request, session: SessionDep, redis: RedisDep, credentials: BearerDep
) -> User:
    if credentials is None:
        raise _unauthorized("Authentication required", "missing_token")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(str(payload["sub"]))
        token_iat_ms = int(payload.get("iat_ms") or int(payload["iat"]) * 1000)
        token_jti = str(payload["jti"])
        token_exp = int(payload["exp"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _unauthorized("Invalid or expired token", "invalid_token") from None

    # Redis revocation check (logout denylist + per-user not-before). Fails
    # open when Redis is down; see app/core/denylist.py.
    if await denylist.is_token_denied(
        redis, jti=token_jti, user_id=str(user_id), iat_ms=token_iat_ms
    ):
        raise _unauthorized("Invalid or expired token", "token_revoked")

    user = await user_repo.get_by_id(session, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("Invalid or expired token", "invalid_token")

    # The parsed token facts (jti/exp) are needed by logout to denylist the
    # exact token being presented; reading them from state avoids a re-decode.
    request.state.user_id = str(user.id)
    request.state.token_jti = token_jti
    request.state.token_exp = token_exp
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != Role.ADMIN.value:
        raise Forbidden("Admin role required", code="admin_required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
