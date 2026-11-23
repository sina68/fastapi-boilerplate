#!/usr/bin/env bash
set -euo pipefail

# Migrations run on start here for single-host/small deployments. On Kubernetes
# prefer a separate migration Job so N replicas do not race (alembic takes an
# advisory lock, but a failed rollout is harder to read than a failed Job).
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    echo "running migrations"
    alembic upgrade head
fi

# Compose passes a command for the worker; anything given wins over uvicorn.
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-1}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"
