"""sqladmin panel at /admin, gated by session login, the admin role, and a
per-IP rate limit on the login form itself.

The panel is a second auth surface: it uses its own cookie session, not JWT,
and it must not rely on the API's rate-limit middleware. Keep it behind the
VPN/ingress in production (see docs/SECURITY.md).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from redis.asyncio import Redis
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.exceptions import problem_response
from app.core.ratelimit import client_ip, hit_rate_limit
from app.core.roles import Role
from app.core.security import verify_password
from app.db.redis import get_redis_client
from app.db.session import get_engine, get_session_maker
from app.models.item import Item
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories import user as user_repo

SESSION_USER_KEY = "admin_user_id"


class AdminAuth(AuthenticationBackend):
    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        *,
        secret_key: str,
        redis_provider: Callable[[], Redis],
    ) -> None:
        super().__init__(secret_key=secret_key)
        self._session_maker = session_maker
        self._redis_provider = redis_provider

    async def login(self, request: Request) -> bool | JSONResponse:
        # The form is public and password-checking: rate limit it per IP like
        # the API does, with its own (stricter) budget.
        allowed = await hit_rate_limit(
            self._redis_provider(),
            scope="admin:login",
            key_suffix=client_ip(request),
            limit=settings.ADMIN_LOGIN_RATE_LIMIT_PER_MINUTE,
            window=settings.RATE_LIMIT_WINDOW_SECONDS,
        )
        if not allowed:
            return problem_response(
                status_code=429,
                detail="Too many admin login attempts, slow down",
                code="rate_limited",
                instance=request.url.path,
                headers={"Retry-After": str(settings.RATE_LIMIT_WINDOW_SECONDS)},
            )

        form = await request.form()
        email = str(form.get("username") or "").strip().lower()
        password = str(form.get("password") or "")
        if not email or not password:
            return False

        async with self._session_maker() as session:
            user = await user_repo.get_by_email(session, email)
        if user is None or not user.is_active or user.role != Role.ADMIN.value:
            return False
        if not verify_password(password, user.password_hash):
            return False

        request.session[SESSION_USER_KEY] = str(user.id)
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        raw_user_id = request.session.get(SESSION_USER_KEY)
        if not raw_user_id:
            return False
        try:
            user_id = uuid.UUID(str(raw_user_id))
        except ValueError:
            request.session.clear()
            return False

        # Re-read the role on every request so a demotion or deactivation takes
        # effect immediately instead of when the cookie expires.
        async with self._session_maker() as session:
            user = await user_repo.get_by_id(session, user_id)
        if user is None or not user.is_active or user.role != Role.ADMIN.value:
            request.session.clear()
            return False
        return True


class UserAdmin(ModelView, model=User):
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-user"
    column_list = [
        User.id,
        User.email,
        User.role,
        User.is_active,
        User.created_at,
    ]
    column_searchable_list = [User.email]
    column_sortable_list = [User.email, User.role, User.created_at]
    # Passwords are set through the API, never through a form here.
    can_create = False
    column_details_exclude_list = [User.password_hash]


class ItemAdmin(ModelView, model=Item):
    name = "Item"
    name_plural = "Items"
    icon = "fa-solid fa-list"
    column_list = [
        Item.id,
        Item.owner_id,
        Item.title,
        Item.created_at,
        Item.updated_at,
    ]
    column_searchable_list = [Item.title]
    column_sortable_list = [Item.created_at]


class RefreshTokenAdmin(ModelView, model=RefreshToken):
    name = "Refresh token"
    name_plural = "Refresh tokens"
    icon = "fa-solid fa-key"
    column_list = [
        RefreshToken.user_id,
        RefreshToken.created_at,
        RefreshToken.expires_at,
        RefreshToken.revoked_at,
    ]
    can_create = False
    can_edit = False
    can_delete = True


def setup_admin(
    app: FastAPI,
    *,
    engine: AsyncEngine | None = None,
    session_maker: async_sessionmaker[AsyncSession] | None = None,
    redis_provider: Callable[[], Redis] | None = None,
) -> Admin:
    """Mount the panel. Callers may inject engine/session maker/redis (tests)."""
    resolved_maker = session_maker or get_session_maker()
    admin: Admin = Admin(
        app=app,
        engine=engine or get_engine(),
        session_maker=resolved_maker,
        authentication_backend=AdminAuth(
            resolved_maker,
            secret_key=settings.admin_session_secret,
            redis_provider=redis_provider or get_redis_client,
        ),
        title=f"{settings.SERVICE_TITLE} admin",
        base_url="/admin",
    )
    admin.add_view(UserAdmin)
    admin.add_view(ItemAdmin)
    admin.add_view(RefreshTokenAdmin)
    return admin


__all__: list[Any] = ["SESSION_USER_KEY", "AdminAuth", "setup_admin"]
