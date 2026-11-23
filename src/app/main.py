from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from app.admin import setup_admin
from app.api.router import api_router
from app.api.v1.health import router as health_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.db.redis import close_redis
from app.db.session import dispose_engine
from app.middlewares.context import RequestContextMiddleware
from app.middlewares.metrics import MetricsMiddleware
from app.middlewares.security import BodySizeLimitMiddleware, SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if settings.SENTRY_DSN:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.ENVIRONMENT,
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            send_default_pii=False,
        )
    yield
    await close_redis()
    await dispose_engine()


def create_app(
    *,
    admin_engine: AsyncEngine | None = None,
    admin_session_maker: async_sessionmaker[AsyncSession] | None = None,
    admin_redis_provider: Callable[[], Redis] | None = None,
) -> FastAPI:
    setup_logging()
    app = FastAPI(
        title=settings.SERVICE_TITLE,
        version="0.1.0",
        debug=settings.DEBUG,
        lifespan=lifespan,
        # In production keep docs off or behind auth; they describe the API to
        # attackers as much as to your team.
        docs_url=None if settings.ENVIRONMENT == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.ENVIRONMENT == "production" else "/openapi.json",
    )

    # add_middleware prepends, so the last one added runs first. This order
    # puts RequestContext outermost (every response, including CORS preflights
    # and 413s, carries X-Request-ID) with Metrics just inside it, so rejected
    # and preflight responses are counted too.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.admin_session_secret,
        same_site="lax",
        https_only=settings.ENVIRONMENT == "production",
        max_age=settings.ADMIN_SESSION_MAX_AGE_SECONDS,
    )
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=settings.MAX_REQUEST_BYTES,
        # Streaming uploads carry their own, larger cap enforced while
        # writing to disk (services/upload.py); don't 413 them here.
        exempt_paths=(f"{settings.API_PREFIX}/uploads",),
    )
    if settings.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            allow_credentials=True,
        )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    setup_admin(
        app,
        engine=admin_engine,
        session_maker=admin_session_maker,
        redis_provider=admin_redis_provider,
    )

    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.API_PREFIX)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"service": settings.SERVICE_NAME, "status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # noqa: S104 - container bind
        port=8000,
        reload=settings.ENVIRONMENT == "development",
        log_config=None,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )
