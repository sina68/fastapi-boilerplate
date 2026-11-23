from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.exceptions import NotFound
from app.core.ratelimit import rate_limit
from app.schemas.item import ItemCreate, ItemListOut, ItemOut, ItemUpdate
from app.services import item as item_service

router = APIRouter(prefix="/items", tags=["items"])

list_limit = rate_limit("items:list", settings.RATE_LIMIT_PER_MINUTE)


@router.get("", response_model=ItemListOut, dependencies=[Depends(list_limit)])
async def list_items(
    session: SessionDep,
    user: CurrentUser,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ItemListOut:
    return await item_service.list_items(session, owner_id=user.id, limit=limit, offset=offset)


@router.post("", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(payload: ItemCreate, session: SessionDep, user: CurrentUser) -> ItemOut:
    return await item_service.create_item(session, owner_id=user.id, payload=payload)


@router.get("/{item_id}", response_model=ItemOut)
async def get_item(item_id: str, session: SessionDep, user: CurrentUser) -> ItemOut:
    item_uuid = _parse_uuid(item_id)
    return await item_service.get_item(session, item_id=item_uuid, owner_id=user.id)


@router.patch("/{item_id}", response_model=ItemOut)
async def update_item(
    item_id: str, payload: ItemUpdate, session: SessionDep, user: CurrentUser
) -> ItemOut:
    item_uuid = _parse_uuid(item_id)
    return await item_service.update_item(
        session, item_id=item_uuid, owner_id=user.id, payload=payload
    )


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: str, session: SessionDep, user: CurrentUser) -> None:
    item_uuid = _parse_uuid(item_id)
    await item_service.delete_item(session, item_id=item_uuid, owner_id=user.id)


def _parse_uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise NotFound("Item not found", code="item_not_found") from None
