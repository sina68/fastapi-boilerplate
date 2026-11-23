"""Streaming upload route.

The body is never buffered whole: the middleware exemption (main.py) hands
this route the raw receive stream and the service writes chunk-by-chunk to
disk with its own cap. See services/upload.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, status

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.ratelimit import rate_limit
from app.schemas.upload import UploadOut
from app.services import upload as upload_service

router = APIRouter(prefix="/uploads", tags=["uploads"])

# Uploads are exempt from the JSON body cap, so they get an explicit budget:
# an authenticated client must not be able to fill the disk unthrottled.
upload_limit = rate_limit("uploads", settings.RATE_LIMIT_PER_MINUTE)


@router.post(
    "",
    response_model=UploadOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(upload_limit)],
)
async def upload(
    request: Request,
    user: CurrentUser,
    x_filename: str | None = Header(default=None),
) -> UploadOut:
    file_id, size, sha256, _ = await upload_service.save_stream(
        request.stream(), max_bytes=settings.MAX_UPLOAD_BYTES
    )
    return UploadOut(
        id=file_id,
        filename=upload_service.safe_filename(x_filename),
        size_bytes=size,
        sha256=sha256,
    )
