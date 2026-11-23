"""Auth business rules: hashing, token pairs, refresh rotation with a
single-use reuse grace window, and session revocation."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import denylist
from app.core.config import settings
from app.core.exceptions import Conflict, Unauthorized
from app.core.security import create_access_token, hash_password, verify_password
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories import refresh_token as refresh_repo
from app.repositories import user as user_repo
from app.schemas.user import TokenOut, UserCreate, UserLogin

_DUMMY_HASH = hash_password("timing-equalizer-not-a-real-password")


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; compare everything in UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def register(session: AsyncSession, payload: UserCreate) -> User:
    email = payload.email.lower()
    if await user_repo.get_by_email(session, email) is not None:
        raise Conflict("Email already registered", code="email_taken")
    password_hash = hash_password(payload.password)
    try:
        user = await user_repo.create(session, email=email, password_hash=password_hash)
        await session.commit()
    except IntegrityError:
        # Two concurrent registrations can both pass the check above; the unique
        # index is the real arbiter, so map its violation to the same 409
        # instead of leaking a 500.
        await session.rollback()
        raise Conflict("Email already registered", code="email_taken") from None
    return user


async def authenticate(session: AsyncSession, payload: UserLogin) -> User:
    user = await user_repo.get_by_email(session, payload.email.lower())
    # Verify against a dummy hash when the user is missing so response time does
    # not reveal which emails exist.
    password_hash = user.password_hash if user else _DUMMY_HASH
    password_ok = verify_password(payload.password, password_hash)
    if user is None or not password_ok:
        raise Unauthorized("Invalid email or password", code="invalid_credentials")
    if not user.is_active:
        raise Unauthorized("User is disabled", code="user_disabled")
    return user


def _refresh_material() -> tuple[str, str]:
    """A fresh opaque refresh token and the hash that is persisted."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


async def _persist_pair(
    session: AsyncSession,
    user: User,
    *,
    raw_refresh: str,
    refresh_hash: str,
) -> TokenOut:
    """Store an already-generated refresh token and build the response pair.

    The material is generated before the rotation claim so the successor hash
    can be written in the same atomic UPDATE that revokes the old row.
    """
    refresh_ttl = timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)
    await refresh_repo.create(
        session,
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=datetime.now(UTC) + refresh_ttl,
    )
    return TokenOut(
        access_token=create_access_token(str(user.id)),
        refresh_token=raw_refresh,
        expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
        refresh_expires_in=int(refresh_ttl.total_seconds()),
    )


async def issue_token_pair(session: AsyncSession, user: User, *, commit: bool = True) -> TokenOut:
    """Mint an access + refresh pair. ``commit=False`` lets the caller keep
    writing (rotation records the successor in the same transaction)."""
    raw_refresh, refresh_hash = _refresh_material()
    pair = await _persist_pair(session, user, raw_refresh=raw_refresh, refresh_hash=refresh_hash)
    if commit:
        await session.commit()
    return pair


def _inside_grace(token: RefreshToken, now: datetime) -> bool:
    """Rotated recently, and the one retry for this row is still unspent."""
    grace = settings.REFRESH_REUSE_GRACE_SECONDS
    revoked_at = token.revoked_at
    if grace <= 0 or revoked_at is None or token.successor_token_hash is None:
        return False
    if token.grace_used_at is not None:
        return False
    return now - _as_utc(revoked_at) <= timedelta(seconds=grace)


async def rotate_refresh_token(session: AsyncSession, raw_refresh: str) -> TokenOut:
    token = await refresh_repo.get_by_hash(session, hash_refresh_token(raw_refresh))
    if token is None:
        raise Unauthorized("Invalid refresh token", code="invalid_refresh_token")

    now = datetime.now(UTC)
    if token.revoked_at is None and _as_utc(token.expires_at) <= now:
        await refresh_repo.revoke(session, token, at=now)
        await session.commit()
        raise Unauthorized("Refresh token expired", code="refresh_token_expired")

    user = await user_repo.get_by_id(session, token.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Invalid refresh token", code="invalid_refresh_token")

    # Generate the replacement before claiming: its hash is recorded on the old
    # row by the same atomic UPDATE that revokes it.
    raw_new, hash_new = _refresh_material()

    if token.revoked_at is None:
        claimed = await refresh_repo.claim_rotation(
            session, token.id, at=now, successor_token_hash=hash_new
        )
        if claimed:
            pair = await _persist_pair(session, user, raw_refresh=raw_new, refresh_hash=hash_new)
            await session.commit()
            return pair

        # Lost the race: another request rotated this row after we read it.
        # Reload and let the grace/theft logic below decide; treating our own
        # concurrent retry as theft without looking would kill a live family.
        await session.refresh(token)

    if _inside_grace(token, now) and await refresh_repo.claim_grace(session, token.id, at=now):
        # A dropped response and a theft look identical. Honor exactly one
        # retry inside the window; claim_grace makes the second presentation
        # of this row fatal.
        pair = await _persist_pair(session, user, raw_refresh=raw_new, refresh_hash=hash_new)
        await session.commit()
        return pair

    # Outside the grace window, or the grace is already spent: this row has
    # come back to life. Kill the whole family, not just this token.
    await refresh_repo.revoke_all_for_user(session, token.user_id, at=now)
    await session.commit()
    raise Unauthorized("Refresh token already used", code="refresh_token_reused")


async def revoke_refresh_token(session: AsyncSession, raw_refresh: str) -> None:
    token = await refresh_repo.get_by_hash(session, hash_refresh_token(raw_refresh))
    if token is None or token.revoked_at is not None:
        # Idempotent: logging out twice must not fail.
        return
    await refresh_repo.revoke(session, token, at=datetime.now(UTC))
    await session.commit()


async def revoke_session(
    session: AsyncSession,
    redis: Redis,
    *,
    token_jti: str,
    token_exp: int,
    raw_refresh: str | None,
) -> None:
    """Logout: revoke the refresh token and denylist the presented access
    token for the rest of its (already short) lifetime.

    ``token_jti``/``token_exp`` come from the parsed bearer (request.state in
    the router) — decoding it again here would be a second signature check
    for nothing. Other access tokens of the same user stay valid until they
    expire; role changes bump ``not_before`` to kill all of them at once.
    """
    ttl = token_exp - int(datetime.now(UTC).timestamp())
    if ttl > 0:
        await denylist.deny_access_token(redis, jti=token_jti, ttl_seconds=ttl)
    if raw_refresh:
        await revoke_refresh_token(session, raw_refresh)
