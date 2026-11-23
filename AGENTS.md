# AGENTS.md

Rules for AI coding agents (and humans) working in this repo. Read this before
editing. `CLAUDE.md` points here; keep one source of truth.

## Project

Python >= 3.11, FastAPI, async SQLAlchemy 2.0 + Postgres (asyncpg), Alembic,
Redis (rate limits + Celery broker), Celery worker, Argon2 + JWT with rotating
refresh tokens, RBAC, sqladmin panel, Prometheus, pytest.

## Commands

```bash
make install                 # .venv + deps
make run                     # uvicorn --reload on :8000
make worker                  # celery worker
make beat                    # celery beat (exactly one instance)
make test                    # pytest (no external services needed)
make lint                    # ruff check + format --check + mypy
make fmt
make migrate                 # alembic upgrade head
make migration m="message"   # autogenerate, then READ the diff
make promote email=a@b.c     # first admin, via DB access
docker compose up -d db redis
docker compose up --build    # api + worker + db + redis
```

Always run `make test` and `make lint` before saying you are done. Both are
fast; a red lint is as broken as a red test.

## Layering (do not blur it)

```
router  ->  service  ->  repository  ->  model
  |            |             |
schemas     rules + tx     SQL only
```

- **router**: parse/validate via pydantic, call one service function, return a
  schema. No SQL, no business rules, no `try/except` for domain errors.
- **service**: ownership/role checks, invariants, `session.commit()`, raises
  `AppError` subclasses. One commit per request at most.
- **repository**: queries only. Every user-data query is filtered by the owner
  id — never by primary key alone.
- **schemas**: the trust boundary. Anything from outside the process is
  validated here; never pass raw dicts deeper.

Add a resource by copying the `items` slice: schema → model + migration →
repository → service → router → tests. Do not invent a new pattern.

## Security invariants (never break these)

- Secrets come from env only. Never hardcode, never log, never return them.
  `settings.JWT_SECRET` has no default on purpose.
- Passwords: Argon2 via `app.core.security`. Never compare with `==`, never
  store plaintext, never log the raw value. Do not lower `min_length` below 12.
- Auth: every non-public route depends on `CurrentUser`; admin routes depend on
  `AdminUser`. Public routes are the auth endpoints, health, `/metrics`, the
  `/admin` login page, the `/` root, and `/docs` + `/openapi.json` outside
  production.
- Authorization: filter by owner in the repository; return **404** (not 403) for
  another user's row so ids are not probeable. Missing *role* is 403.
- Refresh tokens: opaque random values, stored as SHA-256 hashes only. Rotate on
  every refresh, revoke the old row, revoke the whole family on replay. Never
  log or return a token you did not just mint.
- Rotation is claimed with one conditional write
  (`UPDATE ... WHERE revoked_at IS NULL`), and the reuse grace with another
  (`... WHERE grace_used_at IS NULL`). Do not replace either with
  read-then-write: two concurrent refreshes would then both mint a live session.
- Reuse grace: a revoked row that still has an unspent `grace_used_at` inside
  `REFRESH_REUSE_GRACE_SECONDS` may be re-rotated **once** (network retry).
  Anything else — spent grace, expired window, no successor — is theft: revoke
  the family. Never widen this silently; it is the whole security property.
- Revocation: logout denylists the presented access `jti` (TTL = remaining
  lifetime); role changes bump `tokens:not_before:<user_id>` (ms precision) so
  every existing token dies on its next request. Both live in Redis and are
  checked in `get_current_user` on every authenticated request. Failing open is
  deliberate and **counted**: `revocation_failures_total{reason}`. Never add a
  fail-open path without incrementing a counter that an alert fires on — a log
  line nobody reads is not a control.
- Admin role changes must go through `require_admin` + a service; never accept a
  role from a client body on a normal route, never let users promote themselves.
- Validation: cap every free-text length and every list size; cap password
  length (Argon2 cost grows with input).
- Errors: raise `AppError` subclasses. Client sees `detail` + `code`; stack
  traces and driver messages never leave the process.
- Logs: `extra={...}` goes through `redact()`. Never log tokens, headers with
  credentials, full request bodies, or PII beyond what ops needs.
- CORS: no `*` in production. Keep the allowlists narrow.
- SQL: parameterized through SQLAlchemy; no f-string SQL, ever.
- New dependency: pin a range in `pyproject.toml`, run `pip-audit` if available,
  and prefer the standard library or an existing dependency.
- Uploads: stream through `services/upload.save_stream` (chunk-by-chunk), never
  `await request.body()` for big files. Enforce the cap while writing and delete
  the partial file on overflow. Filenames from clients are display-only.
- Do not trust `X-Forwarded-For` unless a proxy you own sets it. The limiter
  uses the socket peer on purpose.

## Upload rules

- The route is exempt from the JSON body cap (`exempt_paths` in main.py) and must
  enforce its own larger cap while streaming; do not remove that exemption, or
  413s will fire before the route sees a byte.
- One chunk in memory at a time; never accumulate.
- On any failure (cap, empty, write error) remove the partial file.
- Swap the sink for S3/MinIO multipart when running more than one host.

## Redis rules

- One client (`app.db.redis.get_redis_client`), created lazily, closed on
  shutdown. Do not build clients per request.
- Keys are namespaced and always have a TTL: `ratelimit:<scope>:<ip>`,
  `cache:<name>:<id>`. A key without TTL is a leak.
- Rate limiting fails open when Redis is down (logged warning). Never make the
  API depend on a cache hit for correctness.
- Values are strings/JSON kept small; no unbounded lists or hashes.

## Alerting rules

- `deploy/prometheus/alerts.yml` is part of the contract, not an ops afterthought.
  The `RevocationCheckFailing` / `RateLimitUnavailable` rules must keep matching
  the counter names in `app/core/metrics.py`; `tests/test_alerting.py` guards the
  wiring, so rename both sides together.
- Any new fail-open branch increments a counter there and gets a rule. Alert on
  the metric, never on log text.
- Rules files are deployment artifacts: they are not baked into the image.

## Revocation rules

- `jti` denylist = one token; `not_before` = every token of a user. Choose by
  blast radius, never by convenience.
- Both keys must carry a TTL (remaining access lifetime / lifetime + 60s). A
  revocation key without TTL is a leak and the repo's Redis rule forbids it.
- `not_before` compares the token's `iat_ms` (millisecond claim) — plain `iat`
  seconds cannot distinguish "issued just before the bump" from "just after",
  which is why the claim exists. Do not drop it from `create_access_token`.

## Celery rules

- Tasks are thin sync wrappers around an async function
  (`asyncio.run(...)`), like `tasks.purge_expired_refresh_tokens`. That keeps the
  logic testable without a broker.
- Pass primitives (ids, strings) as arguments — never ORM objects or sessions.
- `task_acks_late` is on: tasks must be idempotent and safe to retry.
- Dispose the engine inside the task (`dispose_engine`) or use a fresh session
  maker; workers live long and their event loops are per-task.
- Do not import `app.main` in tasks; that builds the whole API.
- Periodic work goes in `celery_app.conf.beat_schedule` and needs a `beat`
  process. Run exactly one: a second beat duplicates every task.

## RBAC rules

- Roles live in `app/core/roles.py`; stored on `users.role`.
- Guard with the dependency, not with `if user.role == ...` in routers.
- A role change bumps the target's `not_before`: their live tokens die, the
  acting admin's do not. Never skip the bump because "the role will expire".
- The admin panel login checks the same password hash and rate limit; keep the
  two auth surfaces' budgets separate.
- Promotion happens through `app/cli.py` (DB access) or an admin endpoint that
  itself requires `AdminUser`. Never via registration.
- Every new admin route gets a test: 401 anonymous, 403 regular user, 200 admin.

## Admin panel rules

- Separate auth surface: cookie session (`SessionMiddleware`), role re-checked on
  every request so demotion is immediate.
- Read-mostly by design: `can_create = False` where a form would corrupt data
  (users, tokens). Writes that matter belong in the API, so they get tests.
- Never expose it publicly in production; it belongs behind the VPN/ingress.

## Database rules

- UUID primary keys, timezone-aware timestamps, `Base` naming convention (do
  not remove it — Alembic compares constraint names).
- One Alembic head. If a migration branches, merge before merging the MR.
- Autogenerated migrations are a draft: check types, defaults, indexes, and
  that `downgrade()` actually reverses `upgrade()`.
- Never lazy-load relationships in async code (it raises). Select explicitly
  or use `selectinload`.
- Commit in the service, not in the repository.
- SQLite returns naive datetimes: normalize with `_as_utc` before comparing
  (see `services/auth.py`).

## Testing rules

- Fixtures: `db` (engine + maker), `session_maker`, `redis_client` (fakeredis),
  `test_app`, `client`, `headers` (a logged-in user). Each test gets a fresh app,
  in-memory SQLite schema, and empty Redis.
- One behaviour per test, named `test_<what>_<condition>`. Assert status code,
  error `code`, and the thing that would silently break.
- Must-have coverage for any new resource: happy path, unauthenticated (401),
  other user's row (404), validation failure (422). Admin resources also 403.
- Never call the network or a real broker. Call task functions directly.
- If you add an env var, set a test default in `tests/conftest.py` before app
  import — `settings` is a module-level singleton built at import time.

## Gotchas

- `settings` is created at import. Change env in conftest, not mid-test.
- Middleware order in `app/main.py`: last added runs first. RequestContext is
  outermost (added last) so every response — including CORS preflights and the
  body-cap 413 — gets `X-Request-ID`; `MetricsMiddleware` sits just inside it so
  those responses are counted too. `SecurityHeadersMiddleware` is outside the
  body cap so a 413 still carries the security headers.
- The body cap buffers bodies with no `Content-Length` (chunked) up to the limit,
  then replays them. Raising from inside `receive` is swallowed by FastAPI as a
  400, which is why it works this way. Streaming upload routes are exempt.
- Middleware order matters for the admin panel too: `SessionMiddleware` is the
  innermost middleware, inside CORS/context, and present before the panel routes
  resolve.
- `/metrics` is excluded from metrics collection; keep it that way.
- `docs_url`/`openapi_url` are disabled in production by design.
- Adding a route under a new prefix? Add it in `app/api/router.py`, not in
  `main.py`.
- Access tokens carry a `jti`, so two tokens minted in the same second differ.
  Do not remove it if you plan token denylists.

## Known ceilings (deliberate, not bugs)

- Revocation fails open on Redis errors (availability over instant kill). This is
  counted and alerted (`RevocationCheckFailing`); move to fail-closed only after
  you accept the outage mode.
- Uploads go to local disk; multi-host deployments need object storage.
- Upload content is not scanned for malware and the content type is the client's
  word. Add scanning at ingest before exposing files to other users.
- Admin panel is read-mostly and re-queries the user on every request (one extra
  query; fine at panel traffic levels). Its login form is rate limited per IP but
  the rest of the panel relies on the ingress.
- No multi-tenancy, one database.

## Definition of done

1. `make test` green, `make lint` green.
2. New behaviour has a test that fails if the behaviour is removed.
3. New env var documented in `.env.example` and `Settings`.
4. Migration included and reversible.
5. No secret, token, or user PII in code, logs, or fixtures.
