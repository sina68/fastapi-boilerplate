"""successor marker for refresh reuse grace

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column("successor_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column("grace_used_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("refresh_tokens", "grace_used_at")
    op.drop_column("refresh_tokens", "successor_token_hash")
