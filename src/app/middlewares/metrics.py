"""Prometheus request metrics.

Labels use the matched route template, not the raw path, so a path parameter
per id does not explode the series count.
"""

from __future__ import annotations

import time

from prometheus_client import Counter, Histogram
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_COUNT = Counter(
    "http_requests_total",
    "HTTP requests",
    labelnames=["method", "route", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    labelnames=["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/metrics":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            route_path = getattr(route, "path", None) or "unmatched"
            method = scope["method"]
            REQUEST_COUNT.labels(method, route_path, str(status_code)).inc()
            REQUEST_LATENCY.labels(method, route_path).observe(time.perf_counter() - started)
