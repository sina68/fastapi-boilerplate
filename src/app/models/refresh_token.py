"""Opaque refresh tokens, stored as SHA-256 hashes.

Only the hash is persisted: a database leak must not hand out live sessions.
Rotation revokes the old row and records its successor, so a retry inside the
reuse grace window can be honored exactly once — a second presentation of the
same row is treated as theft and the whole family is revoked.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Set when this token was rotated: the hash of the token issued in its place.
    successor_token_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    # Set when the one-time reuse grace retry was served. Non-null means the next
    # presentation of this row is theft, not a retry.
    grace_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
