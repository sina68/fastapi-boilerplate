"""Item business rules. Ownership is enforced here, not in the router."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound
from app.models.item import Item
from app.repositories import item as item_repo
from app.schemas.item import ItemCreate, ItemListOut, ItemOut, ItemUpdate


def _to_out(item: Item) -> ItemOut:
    return ItemOut.model_validate(item)


async def list_items(
    session: AsyncSession, *, owner_id: uuid.UUID, limit: int, offset: int
) -> ItemListOut:
    items, total = await item_repo.list_for_owner(
        session, owner_id=owner_id, limit=limit, offset=offset
    )
    return ItemListOut(
        items=[_to_out(item) for item in items], total=total, limit=limit, offset=offset
    )


async def get_item(session: AsyncSession, *, item_id: uuid.UUID, owner_id: uuid.UUID) -> ItemOut:
    item = await item_repo.get_for_owner(session, item_id=item_id, owner_id=owner_id)
    if item is None:
        # 404 (not 403) so clients cannot probe which ids exist.
        raise NotFound("Item not found", code="item_not_found")
    return _to_out(item)


async def create_item(
    session: AsyncSession, *, owner_id: uuid.UUID, payload: ItemCreate
) -> ItemOut:
    item = await item_repo.create(
        session, owner_id=owner_id, values=payload.model_dump(exclude_unset=True)
    )
    await session.commit()
    return _to_out(item)


async def update_item(
    session: AsyncSession, *, item_id: uuid.UUID, owner_id: uuid.UUID, payload: ItemUpdate
) -> ItemOut:
    item = await item_repo.get_for_owner(session, item_id=item_id, owner_id=owner_id)
    if item is None:
        raise NotFound("Item not found", code="item_not_found")
    values: dict[str, Any] = payload.model_dump(exclude_unset=True)
    for field, value in values.items():
        setattr(item, field, value)
    await session.commit()
    await session.refresh(item)
    return _to_out(item)


async def delete_item(session: AsyncSession, *, item_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    item = await item_repo.get_for_owner(session, item_id=item_id, owner_id=owner_id)
    if item is None:
        raise NotFound("Item not found", code="item_not_found")
    await item_repo.delete(session, item)
    await session.commit()
