"""Application settings. Everything configurable lives here, sourced from env."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_SECRETS = {
    "change-me",
    "changeme",
    "secret",
    "your-secret-key",
    "dev-secret-key-change-me-please-32chars",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    SERVICE_NAME: str = "app"
    SERVICE_TITLE: str = "FastAPI Boilerplate"
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"

    # --- database -----------------------------------------------------------
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/app"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    DB_ECHO: bool = False

    # --- auth ---------------------------------------------------------------
    # No default on purpose: the app must fail closed instead of shipping a
    # known secret. Put a real one in .env (see .env.example).
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MINUTES: int = 30
    # Password length bounds live in app/schemas/user.py (single source).

    REFRESH_TOKEN_TTL_DAYS: int = 30
    # Grace window in which a client may RETRY a refresh it already used (a
    # dropped response looks identical to a replay). One retry only: a second
    # presentation inside the window revokes the whole family. 0 disables.
    REFRESH_REUSE_GRACE_SECONDS: int = 30

    # --- http ---------------------------------------------------------------
    CORS_ORIGINS: list[str] = Field(default_factory=list)
    MAX_REQUEST_BYTES: int = 1_000_000
    # Uploads stream to disk instead of RAM, so they get their own (larger) cap
    # enforced chunk-by-chunk while writing. See api/v1/uploads.py.
    MAX_UPLOAD_BYTES: int = 52_428_800  # 50 MB
    UPLOAD_DIR: str = "uploads"
    RATE_LIMIT_PER_MINUTE: int = 120
    AUTH_RATE_LIMIT_PER_MINUTE: int = 10
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    ADMIN_LOGIN_RATE_LIMIT_PER_MINUTE: int = 10

    # --- redis --------------------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_SOCKET_TIMEOUT: float = 2.0

    # --- admin panel --------------------------------------------------------
    # Falls back to JWT_SECRET; set a separate value so rotating one does not
    # invalidate the other.
    ADMIN_SESSION_SECRET: str | None = None
    # Panel sessions are a second auth surface; keep their lifetime short. A
    # demotion still takes effect on the next request (role is re-read).
    ADMIN_SESSION_MAX_AGE_SECONDS: int = 8 * 60 * 60

    # --- observability ------------------------------------------------------
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True
    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    @property
    def admin_session_secret(self) -> str:
        return self.ADMIN_SESSION_SECRET or self.JWT_SECRET

    @field_validator("JWT_SECRET")
    @classmethod
    def _check_secret(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        if any(value.strip().lower().startswith(word) for word in _PLACEHOLDER_SECRETS):
            raise ValueError("JWT_SECRET is a placeholder, generate a real one")
        return value

    @model_validator(mode="after")
    def _check_production_hardening(self) -> Settings:
        if self.ENVIRONMENT != "production":
            return self
        if self.DEBUG:
            raise ValueError("DEBUG must be off in production")
        if self.JWT_SECRET.startswith("dev-only"):
            raise ValueError("JWT_SECRET still holds the .env.example value")
        if "*" in self.CORS_ORIGINS:
            raise ValueError("wildcard CORS is not allowed in production")
        if not self.CORS_ORIGINS:
            raise ValueError("CORS_ORIGINS must be set in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
