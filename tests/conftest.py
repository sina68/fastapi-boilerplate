"""Test fixtures: in-memory SQLite, fake Redis, a fresh app per test.

Env vars are set before app modules are imported because settings is a module
level singleton (and JWT_SECRET is required on purpose).
"""

from __future__ import annotations

import os

os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-0123456789"
os.environ["ENVIRONMENT"] = "test"
os.environ["LOG_JSON"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["AUTH_RATE_LIMIT_PER_MINUTE"] = "10"
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000"
os.environ["MAX_REQUEST_BYTES"] = "2000"
os.environ["MAX_UPLOAD_BYTES"] = "1000000"
os.environ["ADMIN_LOGIN_RATE_LIMIT_PER_MINUTE"] = "5"
os.environ["REFRESH_REUSE_GRACE_SECONDS"] = "30"
os.environ["ACCESS_TOKEN_TTL_MINUTES"] = "30"
# Never initialize Sentry from a developer's shell during a test run.
os.environ["SENTRY_DSN"] = ""

from collections.abc import AsyncIterator
from types import SimpleNamespace

import fakeredis.aioredis
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.redis import get_redis
from app.db.session import get_session
from app.main import create_app
from helpers import register_and_login


@pytest_asyncio.fixture
async def db() -> AsyncIterator[SimpleNamespace]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield SimpleNamespace(engine=engine, session_maker=maker)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_maker(db: SimpleNamespace) -> async_sessionmaker[AsyncSession]:
    return db.session_maker


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def test_app(
    db: SimpleNamespace, redis_client: fakeredis.aioredis.FakeRedis
) -> AsyncIterator[FastAPI]:
    application = create_app(
        admin_engine=db.engine,
        admin_session_maker=db.session_maker,
        admin_redis_provider=lambda: redis_client,
    )

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with db.session_maker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def override_get_redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
        yield redis_client

    application.dependency_overrides[get_session] = override_get_session
    application.dependency_overrides[get_redis] = override_get_redis
    try:
        yield application
    finally:
        application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(test_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://testserver"
    ) as http_client:
        yield http_client


@pytest_asyncio.fixture
async def headers(client: AsyncClient) -> dict[str, str]:
    return await register_and_login(client)
