"""Item persistence. Every query is scoped by owner_id, never by id alone."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item


async def list_for_owner(
    session: AsyncSession, *, owner_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[Item], int]:
    base = select(Item).where(Item.owner_id == owner_id)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    result = await session.execute(
        base.order_by(Item.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all()), int(total or 0)


async def get_for_owner(
    session: AsyncSession, *, item_id: uuid.UUID, owner_id: uuid.UUID
) -> Item | None:
    result = await session.execute(
        select(Item).where(Item.id == item_id, Item.owner_id == owner_id)
    )
    return result.scalar_one_or_none()


async def create(session: AsyncSession, *, owner_id: uuid.UUID, values: dict[str, Any]) -> Item:
    item = Item(owner_id=owner_id, **values)
    session.add(item)
    await session.flush()
    await session.refresh(item)
    return item


async def delete(session: AsyncSession, item: Item) -> None:
    await session.delete(item)
    await session.flush()
