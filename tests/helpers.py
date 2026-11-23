"""Shared test helpers. Imported by conftest and individual tests."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.roles import Role
from app.repositories import user as user_repo

EMAIL = "user@example.com"
PASSWORD = "correct-horse-battery"


async def register_and_login(
    client: AsyncClient,
    *,
    email: str = EMAIL,
    password: str = PASSWORD,
) -> dict[str, str]:
    registered = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    assert registered.status_code == 201, registered.text
    logged_in = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert logged_in.status_code == 200, logged_in.text
    return {"Authorization": f"Bearer {logged_in.json()['access_token']}"}


async def login_headers(
    client: AsyncClient,
    *,
    email: str = EMAIL,
    password: str = PASSWORD,
) -> dict[str, str]:
    """New token pair for an existing user (no registration)."""
    logged_in = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert logged_in.status_code == 200, logged_in.text
    return {"Authorization": f"Bearer {logged_in.json()['access_token']}"}


async def user_headers(
    client: AsyncClient,
    *,
    email: str = EMAIL,
    password: str = PASSWORD,
) -> dict[str, str]:
    """Register the user if missing, then return fresh auth headers."""
    registered = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    assert registered.status_code in (201, 409), registered.text
    return await login_headers(client, email=email, password=password)


async def promote_to_admin(
    session_maker: async_sessionmaker[AsyncSession], email: str = EMAIL
) -> None:
    async with session_maker() as session:
        user = await user_repo.get_by_email(session, email)
        assert user is not None
        user.role = Role.ADMIN.value
        await session.commit()
