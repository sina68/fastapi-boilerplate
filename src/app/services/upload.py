"""Streaming uploads: bytes go to disk chunk-by-chunk, never whole in RAM.

This is the pattern to copy for real file intake. The global body-cap
middleware exempts this route (see main.py) because the route enforces its own
larger cap while writing: memory use is one chunk at a time, regardless of
the declared Content-Length (which chunked uploads do not even send).

Swap ``_save_stream`` for S3/MinIO multipart when you outgrow local disk; the
route and its invariants stay the same.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import AppError

_FORBIDDEN_FILENAME = re.compile(r"[\x00-\x1f/\\]")


def safe_filename(raw: str | None) -> str:
    """Keep it a display name, not a path component."""
    name = _FORBIDDEN_FILENAME.sub("_", (raw or "upload.bin").strip())[:200]
    return name or "upload.bin"


def upload_dir() -> Path:
    path = Path(settings.UPLOAD_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def save_stream(
    stream: AsyncIterator[bytes], *, max_bytes: int
) -> tuple[uuid.UUID, int, str, Path]:
    """Write the stream to disk, aborting cleanly at the cap.

    Returns (id, size, sha256, path). Any failure — cap exceeded, empty body, a
    write error, or a client that disappears mid-stream — removes the partial
    file: a half-written upload is garbage, not data.
    """
    file_id = uuid.uuid4()
    path = upload_dir() / f"{file_id}.bin"
    digest = hashlib.sha256()
    size = 0

    try:
        with path.open("wb") as target:
            async for chunk in stream:
                size += len(chunk)
                if size > max_bytes:
                    raise AppError(
                        "Upload exceeds the maximum allowed size",
                        code="payload_too_large",
                        status_code=413,
                    )
                digest.update(chunk)
                target.write(chunk)
        if size == 0:
            raise AppError("Empty upload", code="empty_upload", status_code=400)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return file_id, size, digest.hexdigest(), path
