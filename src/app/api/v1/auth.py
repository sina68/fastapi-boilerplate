from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import CurrentUser, RedisDep, SessionDep
from app.core.config import settings
from app.core.exceptions import Unauthorized
from app.core.ratelimit import rate_limit
from app.schemas.user import RefreshIn, TokenOut, UserCreate, UserLogin, UserOut
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

login_limit = rate_limit("auth:login", settings.AUTH_RATE_LIMIT_PER_MINUTE)
register_limit = rate_limit("auth:register", settings.AUTH_RATE_LIMIT_PER_MINUTE)
refresh_limit = rate_limit("auth:refresh", settings.AUTH_RATE_LIMIT_PER_MINUTE * 3)
logout_limit = rate_limit("auth:logout", settings.AUTH_RATE_LIMIT_PER_MINUTE * 3)


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(register_limit)],
)
async def register(payload: UserCreate, session: SessionDep) -> UserOut:
    user = await auth_service.register(session, payload)
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenOut, dependencies=[Depends(login_limit)])
async def login(payload: UserLogin, session: SessionDep) -> TokenOut:
    user = await auth_service.authenticate(session, payload)
    return await auth_service.issue_token_pair(session, user)


@router.post("/refresh", response_model=TokenOut, dependencies=[Depends(refresh_limit)])
async def refresh(payload: RefreshIn, session: SessionDep) -> TokenOut:
    """Exchange a refresh token for a new pair; the old one is revoked.

    A retried request inside the reuse grace window is honored once; a second
    replay revokes the token family (see services/auth.py).
    """
    return await auth_service.rotate_refresh_token(session, payload.refresh_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(logout_limit)],
)
async def logout(
    payload: RefreshIn, request: Request, user: CurrentUser, session: SessionDep, redis: RedisDep
) -> None:
    """Revoke the refresh token and denylist the presented access token.

    The access token must be sent as the bearer: without it there is no jti to
    revoke. Logging out without a refresh token (client lost it) still kills
    the access token.
    """
    token_jti = getattr(request.state, "token_jti", None)
    token_exp = getattr(request.state, "token_exp", None)
    if token_jti is None or token_exp is None:  # pragma: no cover - state is always set
        raise Unauthorized("Invalid or expired token", code="invalid_token")
    await auth_service.revoke_session(
        session,
        redis,
        token_jti=token_jti,
        token_exp=int(token_exp),
        raw_refresh=payload.refresh_token,
    )


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
