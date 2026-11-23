"""Streaming uploads: chunked bodies reach the route untouched (the JSON body
cap exempts this path) and the service enforces its own cap while writing."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.core.config import settings

UPLOADS_URL = "/api/v1/uploads"


@pytest_asyncio.fixture
async def uploads_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    return tmp_path


def chunks(data: bytes, chunk_size: int) -> AsyncIterator[bytes]:
    async def generate() -> AsyncIterator[bytes]:
        for start in range(0, len(data), chunk_size):
            yield data[start : start + chunk_size]

    return generate()


async def test_upload_streams_without_buffering(client: AsyncClient, headers, uploads_dir: Path):
    payload = bytes(range(256)) * 48  # 12 KB, deliberately above the JSON cap
    response = await client.post(
        UPLOADS_URL,
        content=chunks(payload, 1024),  # 12 chunks, no Content-Length
        headers={**headers, "X-Filename": "notes/../bin"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["size_bytes"] == len(payload)
    assert body["sha256"] == hashlib.sha256(payload).hexdigest()
    # The header is a display name, never a path component.
    assert body["filename"] == "notes_.._bin"

    stored = list(uploads_dir.glob("*.bin"))
    assert len(stored) == 1
    assert stored[0].read_bytes() == payload


async def test_upload_over_cap_aborts_and_cleans_up(
    client: AsyncClient, headers, uploads_dir: Path, monkeypatch
):
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 2000)
    response = await client.post(UPLOADS_URL, content=chunks(b"x" * 3000, 500), headers=headers)
    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"
    assert list(uploads_dir.glob("*.bin")) == []


async def test_upload_requires_authentication(client: AsyncClient):
    response = await client.post(UPLOADS_URL, content=b"x" * 100)
    assert response.status_code == 401


async def test_empty_upload_is_rejected(client: AsyncClient, headers, uploads_dir: Path):
    response = await client.post(UPLOADS_URL, content=b"", headers=headers)
    assert response.status_code == 400
    assert response.json()["code"] == "empty_upload"
    assert list(uploads_dir.glob("*.bin")) == []


async def test_upload_with_declared_length_above_json_cap(
    client: AsyncClient, headers, uploads_dir: Path
):
    """A declared 60KB Content-Length sails past the 2000-byte JSON cap: the
    exemption is what keeps this route streaming."""
    payload = b"a" * 60_000
    response = await client.post(UPLOADS_URL, content=payload, headers=headers)
    assert response.status_code == 201
    assert response.json()["size_bytes"] == 60_000


async def test_failed_stream_removes_the_partial_file(uploads_dir: Path):
    """A write/stream failure must not leave a half-written file behind."""
    from app.services.upload import save_stream

    async def broken() -> AsyncIterator[bytes]:
        yield b"partial"
        raise RuntimeError("storage went away")

    with pytest.raises(RuntimeError):
        await save_stream(broken(), max_bytes=10_000)

    assert list(uploads_dir.glob("*.bin")) == []
