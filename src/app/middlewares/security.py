"""Security headers and request body cap."""

from __future__ import annotations

from collections.abc import Sequence

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.exceptions import problem_response

_BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

# DELETE is not here: it may carry a body, so it goes through the cap too.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_https = scope.get("scheme") == "https"

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _BASE_HEADERS.items():
                    headers.setdefault(name, value)
                if is_https:
                    headers.setdefault(
                        "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
                    )
                if scope["path"].startswith("/api/"):
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    """Cap request bodies: declared length first, then actual bytes.

    When a request declares Content-Length within the limit it streams through
    untouched. Bodies with no declared length (chunked uploads) are buffered up
    to the cap and replayed, because a body read cannot be aborted reliably from
    inside ``receive`` (FastAPI turns that into a 400). Memory is bounded by
    ``max_bytes``.
    """

    def __init__(self, app: ASGIApp, max_bytes: int, exempt_paths: Sequence[str] = ()) -> None:
        self.app = app
        self.max_bytes = max_bytes
        # Streaming endpoints enforce their own (larger) cap while writing, so
        # they skip both the length check and the chunk buffering.
        self.exempt_paths = tuple(prefix.rstrip("/") for prefix in exempt_paths)

    def _is_exempt(self, path: str) -> bool:
        # Match the path or a child segment, never a sibling with the same
        # prefix ("/uploads" must not exempt "/uploads-internal").
        return any(path == prefix or path.startswith(prefix + "/") for prefix in self.exempt_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] in _SAFE_METHODS
            or self._is_exempt(scope["path"])
        ):
            await self.app(scope, receive, send)
            return

        raw_length = Headers(scope=scope).get("content-length")
        if raw_length is not None:
            try:
                declared = int(raw_length)
            except ValueError:
                declared = self.max_bytes + 1
            if declared > self.max_bytes:
                await self._reject(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            body.extend(chunk)
            if len(body) > self.max_bytes:
                await self._reject(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {
                    "type": "http.request",
                    "body": bytes(body),
                    "more_body": False,
                }
            return await receive()

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response: Response = problem_response(
            status_code=413,
            detail="Request body too large",
            code="payload_too_large",
            instance=scope["path"],
        )
        await response(scope, receive, send)
