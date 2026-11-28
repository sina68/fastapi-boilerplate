# AGENTS.md

Rules for AI coding agents (Claude Code and others) and humans working in this
repo. Read this file fully before editing anything. `CLAUDE.md` imports it; keep
one source of truth and do not copy rules into other files.

This repo is the base for **MCI Intelligence** (phase 1: collect posts/news from
Telegram, RSS and web sources, store them with source/topic labels, serve a feed
with Persian search). It must look and behave like the team's existing services
(`notification-python`, `translation`) so anyone on the team can move between
repos without relearning layout, tooling or workflow. Where this repo and those
services disagree, the team standard below wins; the known gaps are listed in
[docs/STRUCTURE_GAP.md](docs/STRUCTURE_GAP.md).

Topic rules that load when you touch matching files live in `.claude/rules/`
(helm, migrations, CI/Docker, tests, connectors). Read the matching one before
editing those paths even if your tool does not load it automatically.

## 0. Sources of truth (read before designing anything)

1. Product spec (phase 1, Persian): Google Doc "MCI Intelligence — سند فاز ۱".
   Body = product scope (features, roles, sources, acceptance criteria);
   appendix «پیوست الف — متمم فنی» = first technical draft.
2. Technical architecture (Persian): [docs/architecture.md](docs/architecture.md)
   («سند معماری فنی پلتفرم جمع‌آوری و پایش منابع»). Its section ۲۳ lists
   principles that must never be broken.
3. This file and `.claude/rules/*.md`.
4. Reference services for shape: `notification-python` (slice layout,
   DatabaseManager, metrics per slice, offline docs, entrypoint) and
   `translation` (provider registry pattern, `scripts/` as CronJobs).

The two specs disagree on several points. The list and the decisions are in
[docs/STRUCTURE_GAP.md §۳](docs/STRUCTURE_GAP.md). Already decided: topics and
cross-source duplicate linking are in phase 1 (Google Doc), queues are split by
network path `domestic`/`egress` (Google Doc), and the folder layout is the
team layout with `uv` (section 2). Rules:

- A point marked **⚖ pending** in this file is one of those conflicts. Do not
  implement it until the decision is written in STRUCTURE_GAP.md §۳ (column
  «تصمیم»); ask in the MR instead.
- Where only one spec covers a point, follow it.
- architecture.md §18 (folder layout) is overridden by the team layout in
  section 2 below; its *ideas* (separate `connectors/` and `processing/`
  packages) are kept inside that layout.
- If a spec and the code disagree, stop and ask in the MR; do not silently pick
  one. Items marked ⚠️ in the Google Doc are unverified: do not hard-code
  assumptions from them.

## 1. Workflow (every change)

### Branches

- Branch from `dev`. Never commit to `dev`, `stage`, `main`/`master` or `prod`
  directly, never push to them, never force-push them.
- Name must start with a type prefix: `<type>/<anything>`, where type is one of
  the commit types below (`feat/`, `fix/`, `refactor/`, `docs/`, `chore/`, ...).
  The rest is free, e.g. `feat/telegram-connector`,
  `fix/BW3-11402-rss-etag`. The push hook rejects other names.
- One task = one branch = one MR. Do not mix unrelated changes (formatting
  sweeps, drive-by refactors, dependency bumps) into a feature MR.

### Commits (Conventional Commits)

- Format: `type(scope): subject` — lowercase type, optional scope, colon, space,
  imperative subject, no trailing period, first line <= 72 chars.
- Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`,
  `ci`, `chore`, `revert`.
- Scope = the slice or area touched: `source`, `topic`, `item`, `crawler`,
  `telegram`, `rss`, `web`, `search`, `auth`, `helm`, `ci`, `deps`, ...
- An emoji prefix (gitmoji, as in the other services) is optional.
- Body (optional, after a blank line): *why*, not *what*. Wrap at 72.
- Small, focused commits. Each commit should pass lint and tests on its own.
- Never use `--no-verify`, never skip or disable a hook that is installed. If a
  hook fails, fix the cause.

Examples:

```
feat(telegram): paginate t.me/s with ?before= until cursor
fix(rss): send If-None-Match so unchanged feeds return 304
test(item): cover dedupe by canonical_url across sources
```

### Before every push (mandatory, also enforced by hooks)

```bash
make lint    # ruff check + ruff format --check + mypy
make test    # pytest, no external services
```

Both green or you do not push. A red lint is as broken as a red test. If you
changed models, also run `make migration-check` against a local Postgres
(`docker compose up -d db`). If you changed the chart, run `helm lint` and
`helm template` on it (see `.claude/rules/helm.md`).

Then run the self-review in section 7 (`/pre-push-review` in Claude Code) and
fix what it finds before pushing.

### Merge requests

- Target `dev`. Use the template in `.gitlab/merge_request_templates/`
  (`feature.md`, `bugfix.md`, `improvement.md`); fill every section, delete
  optional sections you do not use, keep the Jira link.
- MR title = the main commit subject in Conventional Commits form.
- Never merge your own MR. A reviewer approves; the reviewer merges or tells you
  to.
- Answer every review comment with a fix commit or a reason. Do not resolve
  threads you did not fix.
- Keep the MR reviewable: aim for < 400 changed lines excluding fixtures and
  migrations. Split bigger work into stacked MRs.

### Releases

`dev` → (MR) → `stage` → tag `vX.Y.Z` for production, same as the other
services. Agents never create tags or push to `stage`/`prod`.

## 2. Target layout (team standard)

All application code lives directly under `src/` as top-level packages and is
imported flat (`from core.config import settings`, `from api.source.service
import SourceService`). The Docker image sets `PYTHONPATH=/home/app/src`;
tests add `src` to `sys.path` in `tests/conftest.py`.

```
src/
  main.py                 app = create_app()   (uvicorn main:app --app-dir src)
  utils/app.py            create_app(): lifespan, middlewares, routers, offline docs, handlers
  core/
    config.py             Settings (pydantic-settings) + module-level `settings`
    exceptions.py         domain errors (problem-details), messages catalogue
    healthcheck.py        /healthcheck/liveness, /readiness, /postgres
    logging.py            JSON logs + redact()
    security.py, roles.py, ratelimit.py, metrics.py ...
  adapters/               infrastructure clients, one module each
    database.py           DatabaseManager (engine + session lifecycle)
    redis.py, http.py (httpx + proxy + per-domain limits), search.py (OpenSearch)
  middlewares/            trace_id.py, prometheus.py, security.py, ...
  models/__init__.py      BaseModel (DeclarativeBase) + DB naming convention
  api/
    <slice>/              one business slice per folder
      router.py           HTTP only
      schemas.py          pydantic request/response models (trust boundary)
      models.py           SQLAlchemy tables of this slice
      repository.py       class XRepository(session) — queries only
      service.py          class XService(repository, ...) — rules
      dependencies.py     FastAPI DI factories: session -> repository -> service
      metrics.py          create_api_metrics_set(...) for this slice
      enums.py            optional
      <sub-pkg>/          optional, e.g. clients/
  connectors/             source connectors (no FastAPI, no DB)
  processing/             normalization, validation, dedupe, hashing
  worker/                 Celery app, beat schedule, scheduler claim, thin tasks
  scripts/                one-off / CronJob entry points: python -m scripts.<name>
  static/docs/            vendored Swagger UI / ReDoc assets (offline /docs)
  alembic.ini
  alembic/                env.py + versions/
tests/
  conftest.py
  <slice>/test_*.py       mirrors src/api/<slice>
deploy/
  helm/<service>/         self-contained chart (no parent/library chart)
  prometheus/alerts.yml
grafana/<service>-dashboard.json
.gitlab/merge_request_templates/
```

Expected slices for phase 1: `source`, `topic`, `item`, `source_run` (Google
Doc calls it `crawl_run`; ⚖ pending name), `search`, `dashboard`,
`auth`/`user`. Topics are **in phase 1** (decided): sources have one or more
topics, items inherit them (`item_topic.origin = source`), manual correction
(`origin = manual`), `ai` reserved for phase 2; topic is a feed filter.

Pipeline code that is not HTTP lives in shared packages next to `api/`, so it
runs and is tested without FastAPI (architecture.md §3):

```
src/
  connectors/             base.py, registry.py, telegram/, rss/, website/ (+ playwright)
  processing/             normalization.py, validation.py, deduplication.py, content_hash.py
  worker/                 celery_app.py, tasks.py, scheduler.py (claim + enqueue)
```

Workers and the scheduler call slice services/repositories for persistence;
connectors and processing never touch the DB.

The current code still uses the older layered layout under `src/app/`
(`api/v1`, `services/`, `repositories/`, `schemas/`, `models/`). Rules:

- New code goes into the target layout only. Do not add new files under
  `src/app/`.
- Moving existing code to the target layout happens in a dedicated
  `refactor(structure): ...` MR with no behaviour change and all tests green,
  not inside a feature MR.
- Paths in this file use the target layout. Until the move lands, the same
  module lives at `src/app/<same path>` (e.g. `core/security.py` =
  `src/app/core/security.py`, `adapters/database.py` = `src/app/db/session.py`).

## 3. Code rules

### Layering (do not blur it)

```
router -> service -> repository -> model
  |          |            |
schemas   rules + tx    SQL only
```

- **router**: declare the route, validate input via schemas/`Query(...)`, call
  **one** service method, return a schema. No SQL, no business rules, no
  `try/except` for domain errors, no direct `session` use.
- **service**: a class whose collaborators come in through `__init__`
  (repository, adapters, other services). Holds invariants, ownership/role
  checks, orchestration. Raises domain exceptions from `core/exceptions.py`.
- **repository**: a class taking `AsyncSession` in `__init__`. Queries only;
  SQLAlchemy expressions or `text()` with bound params. No HTTP, no business
  rules, no commit.
- **dependencies.py**: the only place that wires session → repository →
  service, so tests can override one link with `app.dependency_overrides`.
- **schemas**: everything from outside the process is validated here; never pass
  raw dicts deeper. Cap every free-text length and every list size. API field
  names follow the existing services (camelCase aliases where clients expect
  them, snake_case in Python).
- Cross-slice calls go service → service, never repository of another slice.

### Transactions

- The request session comes from `DatabaseManager.yield_session`: one session
  per request, commit once on success, rollback on any exception, unique
  violations mapped to a 409 domain error (same as `notification-python`).
- Services do not call `commit()` unless an intermediate commit is required
  (e.g. claiming a crawl run before doing network I/O). When they do, add a
  one-line comment saying why.
- Security-critical writes that must be single-writer stay conditional
  `UPDATE ... WHERE <state>` statements (see section 6), never read-then-write.

### Async and I/O

- Everything on the request path is async: `httpx.AsyncClient`, `asyncpg`,
  `redis.asyncio`. No `requests`, no `time.sleep`, no blocking file or CPU-heavy
  work in a route (offload to a worker).
- Never lazy-load relationships in async code. Select explicitly or use
  `selectinload`.
- Every outbound HTTP call has a timeout, goes through `adapters/http.py`
  (proxy, User-Agent, per-domain concurrency/rate limit, retry policy), and is
  mocked in tests.

### Config and secrets

- All config in `core/config.py` `Settings`, read from env only. A new env var
  is added to `Settings`, `.env.example`, `tests/conftest.py` (test default) and
  the Helm values in the same MR.
- Secrets (DB password, JWT secret, proxy credentials, Sentry DSN, API keys)
  have no default, are never logged, never returned, never committed, and in
  Kubernetes come from `secretKeyRef`.
- Never read or edit `.env`; edit `.env.example`.

### Errors

- Raise domain exceptions (subclasses in `core/exceptions.py`); one global
  handler renders RFC 7807 problem details (`type`, `title`, `status`,
  `detail`, `instance`, plus our stable machine `code`).
- `detail` shown to panel users is Persian; `code` is a stable English
  snake_case identifier clients can switch on.
- Stack traces, SQL and driver messages never leave the process.
- 404 (not 403) for another user's row; 403 for a missing role; 422 for
  validation; 409 for conflicts; 503 when a dependency the route needs is down.

### Logging, tracing, metrics

- Structured JSON logs only, through the `logging` module. No `print`.
- Event-style messages (`"source.run.finished"`) with context in `extra={...}`;
  `extra` always goes through `redact()`. Pipeline logs always carry
  `source_id`, `run_id`, `task_id`, `connector_type`, and on finish/failure
  `error_code` and `duration_ms` (architecture.md §17.1).
- Never log tokens, passwords, credential headers, full request bodies, full
  crawled HTML, or PII beyond what ops needs.
- Trace id header is `x-trace-id` (read or generate, echo on response), same as
  the other services.
- HTTP metrics per slice via the slice's `metrics.py` + route class; pipeline
  metrics (runs/errors per source and type, new items/hour, queue length,
  publish-to-store latency) in `core/metrics.py`. Label values are bounded
  (source **type**, not source URL). `/metrics` itself is not instrumented.
- Run one uvicorn worker per pod and scale with replicas: Prometheus counters
  are per process.

### Style

- Python 3.14 (`.python-version`). Type hints everywhere; `mypy` must pass.
- `ruff` is the linter and formatter; config in `pyproject.toml`. Do not add
  per-line `noqa`/`type: ignore` without a reason in the same comment.
- Comments explain *why* (constraints, incidents, spec references), not what
  the next line does. Reference the spec section when implementing it
  (`# spec الف.۱۰: 4xx is not retried`).
- No commented-out code, no TODO without a Jira key.
- New dependency: justify it in the MR, pin a lower bound in `pyproject.toml`,
  update `uv.lock` with `uv lock`, prefer the standard library or an existing
  dependency.

## 4. Pipeline rules (architecture.md §6–§13, §23; Google Doc الف.۲, الف.۱۰)

Non-negotiable (architecture.md §23): PostgreSQL is the only source of truth;
Redis and Celery state are never the record of a run or an item. One source's
failure never stops others. Re-running a job never creates duplicates. The
checkpoint moves only after the data is committed. Raw and normalized data stay
separable. URL fetching is SSRF-safe.

- **Collection never runs in an HTTP request.** The API validates, records and
  enqueues; workers fetch, parse and process. `POST /sources/test` (preview) is
  the only exception and still goes through the same SSRF-safe fetcher with
  tight limits.
- **Scheduler**: one Celery beat process (single replica, `Recreate`). Every
  minute it claims due sources (`enabled AND next_run_at <= now()`) atomically
  in PostgreSQL with `SELECT ... FOR UPDATE SKIP LOCKED`, writes a
  `source_runs` row (`queued`), sets `next_run_at`, commits, then enqueues
  `run_source(source_id, run_id)`. The claim must be recoverable: a run stuck
  in `queued`/`running` past its lease is released by the next tick, never
  locked forever. Do not replace the DB claim with a Redis lock.
- **Run statuses** (architecture.md §6.4): `queued`, `running`, `succeeded`,
  `partial`, `failed`, `cancelled`. A successful run with zero new items is
  `succeeded`, never an error. Counters: `items_seen`, `items_created`,
  `items_updated`, `attempt_count`; errors as sanitized `error_code` +
  `error_message`.
- **Queues by network path** (decided, mandatory): Telegram is filtered in
  Iran and some Iranian sites block foreign IPs, so every connector declares a
  `network_group` and work is routed to its queue: `domestic` (Iranian sites,
  RSS/web) and `egress` (Telegram and other filtered sources, through the egress
  proxy from settings). Each group has its own worker Deployment. If Playwright
  is needed, browser work gets its own queue per group (e.g.
  `domestic_browser`) with strict resource limits. Never route by guesswork,
  never send a domestic source through the egress proxy or the reverse.
- **Tasks** take primitives (ids, strings), are idempotent, safe under
  `task_acks_late`, and are thin sync wrappers around an async function that is
  unit-tested without a broker.
- **Retry** (architecture.md §6.3): timeout, network errors, HTTP 429 and 5xx
  are transient → exponential backoff + jitter, bounded attempts, attempts
  recorded on the run. Invalid URL/config, other 4xx and parse failures are
  permanent → no retry until the config changes. Respect `Retry-After` on 429.
- **Health** (⚖ pending thresholds): health is computed from real
  `source_runs` history. `consecutive_failures` increments on failure and
  resets on success; past a configurable threshold the source becomes
  `needs_review`. Auto-disable is a per-deployment policy flag, off by default
  (architecture.md §17.4; the Google Doc's "10 failures → stopped" is the
  pending alternative).
- **Processing order**: raw → parse → normalize → validate → dedupe → persist.
  An invalid item is recorded and skipped; it never fails the whole run.
- **Dedupe within a source** is enforced by PostgreSQL unique constraints, not
  only in code: `(source_id, external_id)`, and where applicable
  `(source_id, canonical_url)` / `(source_id, content_hash)`.
  **Across sources** (decided: in phase 1, Google Doc behaviour): both items
  are kept, the later one is linked to the first with `duplicate_of` when the
  normalized `canonical_url` matches or the `content_hash` of normalized text
  matches. Exact-match only (no SimHash/MinHash/embeddings in phase 1). The feed
  shows the original with its linked duplicates, not two unrelated items. The
  link is set in the same transaction as the insert and must be race-safe
  (re-check under the DB, not only in code).
- **`(source_id, content_hash)` uniqueness** is ⚖ pending: a source can
  legitimately publish identical text twice (e.g. a repeated announcement).
  Until the behaviour is specified, `content_hash` is indexed, **not** unique;
  within-source identity is `(source_id, external_id)`.
- **Content changes**: SHA-256 of normalized content; update the item only when
  the hash changes; store a version row only for real changes, never on every
  fetch.
- **Checkpoint** (`source_checkpoints`, or `source.cursor` ⚖ pending): updated
  in the same transaction as, or after, the items it covers. Never before.
- **Raw vs normalized**: keep `raw_data` (what the connector extracted) next to
  normalized fields so processing can be re-run without refetching. No object
  storage and no media download in the MVP.
- Persian normalization (ی/ي، ک/ك، Unicode NFC/NFKC rules, ZWNJ, digits,
  diacritics, control chars, whitespace), URL canonicalization (tracking params,
  scheme, trailing slash) and Jalali → UTC live in `processing/` and are reused
  everywhere, including search queries; never re-implement them inline. Keep the
  original text when normalization could lose information.
- **Search**: PostgreSQL full-text search + GIN, B-tree for filters, `pg_trgm`
  if needed, behind a `search` service interface (architecture.md §14). A
  separate engine (OpenSearch etc., which the Google Doc proposes) only after a
  benchmark on real data. Facet counts are computed on the same filtered set as
  the results.
- Deleting a source never deletes its historical items.
- Store links and summaries for display; do not republish full third-party
  content (Google Doc الف.۱۳).

See `.claude/rules/connectors.md` before writing or changing a connector.

## 5. Infrastructure rules

- Docker, entrypoint and CI: `.claude/rules/ci-docker.md`.
- Helm: `.claude/rules/helm.md`. The chart is self-contained (no dependency on
  the shared `zarebin` chart or any other remote chart) but keeps the same
  values shape as the charts in `bw3-ops`, so ops can read both the same way.
- No dependency on services or packages only reachable inside the MCI network
  (`repo.mci.dev`, `docker.mci.dev`, `zarebin-common`, `zarebin-public/cicd-template`,
  `bw3-ops`) unless the target environment is confirmed to reach them. Where the
  other services use `zarebin-common` (trace id middleware, JSON logger,
  problem-details handler, API metrics route class), keep an in-repo module
  with the same names and behaviour under `core/` / `middlewares/`.
- `/docs` and `/redoc` serve vendored assets from `src/static/docs` (the
  deployment network may have no internet), like the other services.

## 6. Security invariants (never break these)

- Secrets come from env only. Never hardcode, never log, never return them.
  `settings.JWT_SECRET` has no default on purpose.
- Passwords: Argon2 via `core/security.py`. Never compare with `==`, never
  store plaintext, never log the raw value. Do not lower `min_length` below 12;
  cap the maximum length (Argon2 cost grows with input).
- Auth: every non-public route depends on `CurrentUser`; admin routes depend on
  `AdminUser`. Public routes: auth endpoints, health checks, `/metrics`, the
  `/admin` login page, `/`, and `/docs` + `/openapi.json` outside production.
- Authorization: filter by owner in the repository; return **404** (not 403)
  for another user's row so ids are not probeable. Missing *role* is 403.
- Roles live in `core/roles.py`, stored on `users.role`; guard with the
  dependency, never with `if user.role == ...` in routers. Phase 1 needs
  `admin` and `viewer` (spec E3).
- Role changes go through `require_admin` + a service; never accept a role from
  a client body on a normal route, never let users promote themselves.
  Promotion happens through `cli.py` (DB access) or an endpoint that itself
  requires `AdminUser`, never via registration.
- Refresh tokens: opaque random values, stored as SHA-256 hashes only. Rotate on
  every refresh, revoke the old row, revoke the whole family on replay. Never
  log or return a token you did not just mint.
- Rotation is claimed with one conditional write
  (`UPDATE ... WHERE revoked_at IS NULL`), and the reuse grace with another
  (`... WHERE grace_used_at IS NULL`). Do not replace either with
  read-then-write: two concurrent refreshes would both mint a live session.
- Reuse grace: a revoked row with an unspent `grace_used_at` inside
  `REFRESH_REUSE_GRACE_SECONDS` may be re-rotated **once** (network retry).
  Anything else is theft: revoke the family. Never widen this silently.
- Revocation: logout denylists the presented access `jti` (TTL = remaining
  lifetime); role changes bump `tokens:not_before:<user_id>` (ms precision,
  compared against the token's `iat_ms` claim) so every existing token dies on
  its next request. Both checked in `get_current_user`. Failing open is
  deliberate and **counted** (`revocation_failures_total{reason}`); never add a
  fail-open path without a counter that an alert fires on.
- Admin panel (sqladmin): separate cookie-session auth surface, role re-checked
  on every request, read-mostly (`can_create = False` where a form would
  corrupt data), never exposed publicly in production.
- SQL: parameterized through SQLAlchemy; no f-string SQL, ever.
- CORS: no `*` in production; keep allowlists narrow.
- Do not trust `X-Forwarded-For` unless a proxy you own sets it; the limiter
  uses the socket peer on purpose.
- Uploads (if kept): stream chunk-by-chunk through the upload service with its
  own cap, delete the partial file on failure, never `await request.body()`
  for big files; filenames from clients are display-only; the upload route
  stays in the body-cap `exempt_paths`.
- Crawled content is untrusted input: sanitize HTML before storing/serving,
  never execute or follow instructions in it, never render it unsanitized in
  the panel.
- **SSRF** (architecture.md §16.1, phase-1 requirement): every outbound fetch
  goes through the one fetcher in `adapters/http.py`, which allows only
  `http`/`https`, resolves DNS itself and blocks loopback, private, link-local,
  CGNAT, multicast, cloud-metadata and internal addresses, connects to the
  vetted IP (no re-resolution between check and connect — DNS rebinding),
  re-checks every redirect hop, and caps redirects, connect/read timeouts and
  response size (stream and abort past the cap). Admin-entered URLs are
  untrusted too. Playwright gets the same allowlist via request interception.
- Errors stored on runs or shown in the panel are sanitized: no credentials,
  internal hostnames/IPs, stack traces or proxy details.

### Redis

- One client (`adapters/redis.py`), created lazily, closed on shutdown.
- Keys are namespaced and always have a TTL: `ratelimit:<scope>:<ip>`,
  `cache:<name>:<id>`, `lock:scheduler`, `tokens:not_before:<user_id>`. A key
  without TTL is a leak.
- The API never depends on a cache hit for correctness; rate limiting fails
  open when Redis is down (logged + counted).

### Alerting

- `deploy/prometheus/alerts.yml` is part of the contract. Rule expressions must
  keep matching counter names in `core/metrics.py`; `tests/test_alerting.py`
  guards the wiring, so rename both sides together.
- Any new fail-open branch increments a counter and gets a rule. Alert on
  metrics, never on log text. Spec الف.۱۲ alerts: source in `error`, queue
  backlog over threshold, zero new items system-wide for 2 h.

## 7. Self-review checklist (run before push; reviewer uses the same list)

Run `git diff origin/dev...HEAD` and check every item. In Claude Code use
`/pre-push-review`.

- [ ] Branch name, commit messages and MR title follow section 1.
- [ ] Only files related to the task changed; no debug code, no stray prints,
      no commented-out code, no `.env`, no IDE files.
- [ ] Layering respected; no SQL outside repositories; no new code in
      `src/app/`.
- [ ] Every new behaviour has a test that fails if the behaviour is removed;
      new routes have 401/404/422 tests (admin routes also 403).
- [ ] New env var in `Settings`, `.env.example`, `tests/conftest.py`, Helm
      values.
- [ ] Model change has an Alembic migration that is reversible; one head.
- [ ] Outbound HTTP goes through the SSRF-safe fetcher (timeouts, redirect
      and size caps, per-domain limit, robots), retries per section 4, mocked
      in unit tests.
- [ ] Branch starts with a type prefix (`feat/`, `fix/`, ...).
- [ ] Nothing marked ⚖ pending was implemented without a recorded decision;
      no tool or service added only because a spec mentions it
      (architecture.md §23.12).
- [ ] Logs: no secrets/PII/full bodies; `extra` redacted; pipeline logs carry
      `source_id`/`run_id`.
- [ ] Metrics labels bounded; new fail-open path has counter + alert.
- [ ] Error responses use domain exceptions; correct status codes.
- [ ] Helm/Docker/CI changes follow their rule files and `helm lint` passes.
- [ ] `make lint` and `make test` green on the final commit.
- [ ] MR description filled from the right template, Jira link present.

## 8. Testing rules

Details in `.claude/rules/tests.md`. Summary:

- `make test` needs no external services: SQLite in memory, fakeredis, mocked
  HTTP, task functions called directly. Never hit the network or a real broker.
- One behaviour per test, named `test_<what>_<condition>`. Assert status code,
  error `code`, and the thing that would silently break.
- Connectors: saved real HTML/feeds/Telegram pages as fixtures + snapshot of
  the normalized output; a parser change shows as a fixture diff
  (architecture.md §20.2–20.3).
- Integration suite (`make test-integration`, separate CI job, real Postgres
  and Redis, marked `@pytest.mark.integration`, skipped by `make test`):
  unique constraints, upsert, concurrent claim with `SKIP LOCKED`, checkpoint
  after commit, run history, crash recovery, job re-run without duplicates,
  Celery retry against a real broker, Postgres FTS (architecture.md §20.4).
- Security tests are mandatory for the fetcher: SSRF to private/metadata IPs,
  redirect to an internal IP, DNS rebinding, response size cap, timeout,
  invalid URL, unauthorized admin actions (architecture.md §20.5).

## 9. Commands

```bash
make install                 # uv sync (app + dev deps)
make run                     # uvicorn --reload
make worker                  # celery worker
make beat                    # celery beat (exactly one instance)
make test                    # pytest (no external services needed)
make test-integration        # pytest -m integration (real Postgres + Redis)
make lint                    # ruff check + format --check + mypy
make fmt
make migrate                 # alembic upgrade head
make migration m="message"   # autogenerate, then READ and fix the diff
make migration-check         # models vs migrations drift (needs Postgres)
make promote email=a@b.c     # first admin, via DB access
docker compose up -d db redis
```

If a command here does not exist yet in the Makefile, that is a known gap
(docs/STRUCTURE_GAP.md); use the closest existing target and say so in the MR.

## 10. Gotchas

- `settings` is built at import. Set env defaults in `tests/conftest.py` before
  the app is imported, never mid-test.
- Middleware order: last added runs first. Trace/request-context middleware is
  outermost so every response (CORS preflight, 413) carries the trace id;
  metrics just inside it; security headers outside the body cap.
- The body cap buffers chunked bodies up to the limit then replays them;
  raising inside `receive` is swallowed by FastAPI as a 400, which is why it
  works this way. Streaming upload routes are exempt.
- `/metrics` is excluded from metrics collection; keep it that way.
- `docs_url`/`openapi_url` are disabled in production by design.
- New route prefix: register the router in `utils/app.py` `add_api_routers`,
  nowhere else.
- Access tokens carry a `jti`, so two tokens minted in the same second differ.
- SQLite returns naive datetimes: normalize to UTC before comparing.
- Celery: do not import `main`/`utils.app` in tasks (that builds the whole API);
  dispose the engine inside the task; run exactly one beat.

## 11. Definition of done

1. `make lint` green, `make test` green, on the last commit you push.
2. New behaviour has a test that fails if the behaviour is removed.
3. New env var documented in `.env.example`, `Settings` and Helm values.
4. Migration included, reversible, single head; migrations never run
   concurrently (advisory lock in `alembic/env.py` or the Helm hook Job).
5. No secret, token or PII in code, logs, fixtures or Helm values.
6. Self-review checklist (section 7) done; MR template filled.
7. Spec section implemented is referenced in the MR; deviations from the spec
   are called out explicitly.
