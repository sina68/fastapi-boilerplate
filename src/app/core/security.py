"""Password hashing and JWT helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher()


def hash_password(raw_password: str) -> str:
    return _hasher.hash(raw_password)


def verify_password(raw_password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, raw_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(subject: str, ttl_minutes: int | None = None) -> str:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=ttl_minutes or settings.ACCESS_TOKEN_TTL_MINUTES)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": expires,
        "type": "access",
        "jti": uuid.uuid4().hex,
        # Millisecond precision: a per-user "not before" bump must kill tokens
        # issued earlier in the same second but keep ones issued right after.
        "iat_ms": int(now.timestamp() * 1000),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a token. Raises ``jwt.PyJWTError`` when invalid."""
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["exp", "sub", "jti", "type"]},
    )
    # Pin the token kind: if refresh tokens ever become JWTs (or you add
    # invitation/reset tokens), a matching signature must not be enough.
    if payload["type"] != "access":
        raise jwt.InvalidTokenError("not an access token")
    return payload
