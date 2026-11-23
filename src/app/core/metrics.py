"""Prometheus counters for the places where security checks fail open.

Both the revoker and the rate limiter prefer availability over enforcement
when Redis is unreachable. That choice must be visible: an alerting rule on
these counters is the difference between "we failed open once" and "we have
been unprotected for a day". See deploy/prometheus/alerts.yml.
"""

from __future__ import annotations

from prometheus_client import Counter

REVOCATION_FAILURES = Counter(
    "revocation_failures_total",
    "Revocation checks that failed open because Redis was unreachable",
    labelnames=["reason"],
)

RATE_LIMIT_FAILURES = Counter(
    "ratelimit_failures_total",
    "Rate-limit checks that failed open because Redis was unreachable",
    labelnames=["scope"],
)
