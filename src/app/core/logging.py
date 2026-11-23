"""Structured logging with request ids and secret redaction.

Every log line is JSON by default so a log shipper can index it without a
parser. Anything passed via ``extra=`` is redacted before it hits the stream.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.context import current_request_id

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "new_password",
        "current_password",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "api_key",
        "apikey",
        "secret",
        "jwt_secret",
        "cookie",
        "set-cookie",
        "session",
    }
)

_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

_MAX_DEPTH = 4


def redact(value: Any, depth: int = 0) -> Any:
    """Recursively mask values under sensitive keys; cap depth and list size."""
    if depth >= _MAX_DEPTH:
        return "***"
    if isinstance(value, dict):
        return {
            key: ("***" if str(key).lower() in SENSITIVE_KEYS else redact(item, depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item, depth + 1) for item in value[:50]]
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": current_request_id(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = redact(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    if settings.LOG_JSON:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.LOG_LEVEL.upper())

    # Uvicorn installs its own plain-text handlers; drop them so we emit one
    # format. Pass log_config=None when starting uvicorn from code.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    for name in ("uvicorn.access", "sqlalchemy.engine", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
