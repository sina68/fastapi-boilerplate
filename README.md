# FastAPI Boilerplate

Production-shaped starting point for a Python/FastAPI service: async SQLAlchemy
+ Postgres, JWT with rotating refresh tokens and instant revocation, Redis rate
limiting, Celery worker + beat, RBAC, streaming uploads, sqladmin panel, JSON
logs with redaction, Prometheus, migrations, Docker, and a test suite that needs
no external services.

## What you get

| Concern | Choice |
|---|---|
| API | FastAPI, versioned router (`/api/v1`), problem+json errors |
| DB | SQLAlchemy 2.0 async + asyncpg, Alembic migrations |
| Auth | Argon2 hashing, 30 min access JWT, rotating opaque refresh tokens (hashed at rest) |
| Revocation | logout denylists the access `jti` in Redis; role changes kill every existing token (ms-precision `not_before`) |
| Refresh retry | one retry of an already-rotated token allowed for 30s (network drops), a second replay revokes the family; rotation and grace are single-writer (`UPDATE ... WHERE`), so concurrent refreshes cannot mint two sessions |
| RBAC | `user` / `admin` roles, `AdminUser` dependency, admin-only API |
| Admin | sqladmin panel at `/admin`, session login, role re-checked per request |
| Redis | rate limiting (per IP + route scope) and Celery broker/backend |
| Jobs | Celery worker (retry/backoff per task) + beat (daily token purge) |
| Uploads | streaming to disk, per-route cap, sha256, no whole-body buffering |
| Logs | one JSON line per request, request id, secret redaction |
| Ops | liveness/readiness probes, `/metrics`, non-root Docker image |
| Safety | security headers, body cap (declared + chunked), no wildcard CORS in prod, fail-closed secrets |
| Tests | pytest + httpx, in-memory SQLite, fake Redis, authz/rotation/admin cases |

## Quickstart (local)

```bash
cp .env.example .env                     # then edit JWT_SECRET
docker compose up -d db redis            # Postgres :5432, Redis :6379
make install                             # uv venv + dependencies
make migrate                             # alembic upgrade head
make run                                 # http://127.0.0.1:8000/docs
make worker                              # Celery worker, second terminal
make beat                                # periodic scheduler, third terminal
```

No `uv`? `make install-pip` uses `python3.12 -m venv` + pip instead. Needs
Python 3.11+; 3.12 is what the Docker image and CI use.

Generate a real secret:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

First admin (the API never grants the role itself):

```bash
make promote email=you@example.com
# then open http://127.0.0.1:8000/admin
```

## Quickstart (everything in Docker)

```bash
cp .env.example .env
docker compose up --build                # api :8000, worker, postgres, redis
```

The API container runs migrations on start (`RUN_MIGRATIONS=0` to skip); the
worker reuses the same image with a different command.

## Endpoints

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/health/liveness` | no | process alive, no DB |
| GET | `/health/readiness` | no | DB `SELECT 1`, 503 on failure |
| GET | `/metrics` | no | Prometheus text format |
| POST | `/api/v1/auth/register` | no | 201, rate limited |
| POST | `/api/v1/auth/login` | no | access + refresh token, rate limited |
| POST | `/api/v1/auth/refresh` | refresh token | rotates; replay revokes the family |
| POST | `/api/v1/auth/logout` | bearer + refresh token | revokes refresh, denylists the access jti |
| GET | `/api/v1/auth/me` | bearer | current user |
| GET | `/api/v1/items` | bearer | own items, `limit`/`offset`, rate limited |
| POST | `/api/v1/items` | bearer | create |
| GET/PATCH/DELETE | `/api/v1/items/{id}` | bearer | own items only, 404 otherwise |
| GET | `/api/v1/admin/users` | admin | paginated user list |
| PATCH | `/api/v1/admin/users/{id}/role` | admin | promote/demote; kills the target's live tokens |
| POST | `/api/v1/uploads` | bearer | streaming upload, `X-Filename` header, sha256 in response, rate limited |
| GET | `/admin` | admin session | sqladmin panel |
| GET | `/docs` | no | interactive docs; off in production |

## Alerting

Two checks fail open when Redis is down (revocation and rate limiting). Both are
counted, and `deploy/prometheus/alerts.yml` turns the counters into pages:

| Alert | Expression | Severity |
|---|---|---|
| `RevocationCheckFailing` | `rate(revocation_failures_total[5m]) > 0` for 5m | critical |
| `RevocationFailuresSpike` | `increase(revocation_failures_total[10m]) > 50` | warning |
| `RateLimitUnavailable` | `rate(ratelimit_failures_total[5m]) > 0` for 10m | warning |

Load the file with `rule_files:` in Prometheus, or convert the same expressions
to a `PrometheusRule` for the operator. The rules are deployment artifacts and
are not copied into the image; `tests/test_alerting.py` keeps them wired to the
counters.

## Layout

```
src/app/
  api/           routers + dependencies only (thin)
  services/      business rules, transactions, ownership and role checks
  repositories/  SQL, always scoped by owner/user
  models/        SQLAlchemy tables (User, Item, RefreshToken)
  schemas/       pydantic request/response models (the trust boundary)
  core/          config, security, logging, errors, rate limit, roles
  db/            engine/session and Redis client wiring
  middlewares/   request id + access log, security headers, body cap, metrics
  admin/         sqladmin views + admin session auth
  worker/        Celery app and tasks
  cli.py         operator commands (promote)
alembic/         env.py + versions
tests/           fixtures in conftest.py, shared helpers in helpers.py
docs/SECURITY.md pre-deploy checklist
AGENTS.md        rules for AI coding agents (read this before editing)
```

## Commands

```bash
make test        # pytest (no services needed)
make lint        # ruff + mypy
make fmt         # ruff format + autofix
make worker      # celery worker
make beat        # celery beat (one instance only)
make migration m="add field"
make migration-check   # fail if models and migrations disagree (needs DB)
make up          # full docker compose stack
```

## Production notes

- Set `ENVIRONMENT=production`, a real `JWT_SECRET`, a separate
  `ADMIN_SESSION_SECRET`, and explicit `CORS_ORIGINS`. The app refuses to boot
  with debug on, wildcard CORS, or the example secret.
- API docs and the OpenAPI schema are disabled automatically in production.
- Put `/admin` and `/metrics` behind the VPN/ingress. The panel is a second auth
  surface (cookie session) and `/metrics` is unauthenticated.
- Redis holds rate-limit counters and Celery queues: enable `requirepass`/TLS,
  never expose it publicly, and give the worker its own credentials if you can.
- Run one API worker per container (`WEB_CONCURRENCY=1`) and scale with
  replicas; Prometheus counters are per process. Rate limits now live in Redis,
  so they are shared across replicas.
- Prefer a separate migration Job over start-up migrations when several
  replicas roll at once.
- Celery: `task_acks_late` is on, so tasks must be idempotent. Run exactly one
  `beat`; two schedulers duplicate every periodic task.
- Revocation fails open when Redis is down (logged warning): a Redis outage
  must not take the API down, but it is counted: alert on
  `revocation_failures_total` (`RevocationCheckFailing`).
- Uploads land in `UPLOAD_DIR` (local disk) up to `MAX_UPLOAD_BYTES`. Swap
  `services/upload.py` for S3/MinIO multipart before running multiple hosts.

## Deliberately not included

Add these when the requirement is real, not before:

- Multi-tenancy / per-tenant schemas
- Second database or read replicas
- Email/SMS providers (wire them as Celery tasks)
- Object storage for uploads (the route and cap stay; only the sink changes)
- WebSockets / SSE streaming
- Feature flags

See `AGENTS.md` for the exact place each one plugs in.
