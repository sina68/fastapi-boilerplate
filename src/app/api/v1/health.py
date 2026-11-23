"""Liveness and readiness probes. Keep these dependency-light and unauthenticated."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import SessionDep
from app.core.exceptions import problem_response

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/liveness")
async def liveness() -> dict[str, str]:
    """Process is up. No DB, no cache: a broken dependency must not restart the pod."""
    return {"status": "ok"}


@router.get("/readiness", response_model=None)
async def readiness(session: SessionDep) -> Response:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return problem_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
            code="database_unavailable",
            instance="/health/readiness",
        )
    return JSONResponse({"status": "ok"})
