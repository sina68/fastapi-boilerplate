"""Application errors and RFC 9457 (problem+json) handlers."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from http import HTTPStatus

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for errors that are safe to show to the client."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    detail: str = "Something went wrong"

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.detail = detail or self.detail
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.headers = dict(headers or {})
        super().__init__(self.detail)


class BadRequest(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"
    detail = "Bad request"


class Unauthorized(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"
    detail = "Authentication required"


class Forbidden(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"
    detail = "Not allowed"


class NotFound(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    detail = "Not found"


class Conflict(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    detail = "Conflict"


class RateLimited(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    detail = "Too many requests, slow down"


def problem_response(
    *,
    status_code: int,
    detail: str,
    code: str,
    instance: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    try:
        title = HTTPStatus(status_code).phrase
    except ValueError:
        title = "Error"
    body: dict[str, object] = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "detail": detail,
        "code": code,
    }
    if instance:
        body["instance"] = instance
    return JSONResponse(
        status_code=status_code,
        content=body,
        media_type="application/problem+json",
        headers=dict(headers or {}),
    )


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # pragma: no cover - registration guarantees this
        return await unhandled_error_handler(request, exc)
    if exc.status_code >= 500:
        logger.error("app.error", extra={"code": exc.code}, exc_info=exc)
    return problem_response(
        status_code=exc.status_code,
        detail=exc.detail,
        code=exc.code,
        instance=request.url.path,
        headers=exc.headers,
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # pragma: no cover
        return await unhandled_error_handler(request, exc)
    # Echo locations and messages only: echoing the submitted value can leak
    # whatever the client typed (passwords included) into logs and responses.
    errors = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "type": "about:blank",
            "title": HTTPStatus(422).phrase,
            "status": 422,
            "detail": "Request validation failed",
            "code": "validation_error",
            "instance": request.url.path,
            "errors": errors,
        },
        media_type="application/problem+json",
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("app.unhandled_error", extra={"path": request.url.path})
    return problem_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Internal server error",
        code="internal_error",
        instance=request.url.path,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
