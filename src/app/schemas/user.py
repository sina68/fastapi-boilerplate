from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# 128 chars: argon2 cost grows with input, so cap it to keep login cheap.
Password = Annotated[str, Field(min_length=12, max_length=128)]
# Login only needs the upper bound: a password that predates a policy change
# (or was imported) must still be verifiable, and short input must fail as bad
# credentials (401), not as a schema error (422).
LoginPassword = Annotated[str, Field(min_length=1, max_length=128)]
RoleName = Literal["user", "admin"]


class UserCreate(BaseModel):
    email: EmailStr
    password: Password


class UserLogin(BaseModel):
    email: EmailStr
    password: LoginPassword


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=512)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime


class UserListOut(BaseModel):
    items: list[UserOut]
    total: int
    limit: int
    offset: int


class RoleUpdate(BaseModel):
    role: RoleName


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - header scheme, not a secret
    expires_in: int
    refresh_expires_in: int
