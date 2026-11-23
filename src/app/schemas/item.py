from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5_000)


class ItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5_000)

    @model_validator(mode="after")
    def _title_cannot_be_null(self) -> ItemUpdate:
        # Omitted = leave unchanged; explicit null would hit a NOT NULL column
        # and surface as a 500. Reject it at the trust boundary (422) instead.
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")
        return self


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class ItemListOut(BaseModel):
    items: list[ItemOut]
    total: int
    limit: int
    offset: int
