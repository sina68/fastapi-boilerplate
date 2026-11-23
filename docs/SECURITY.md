# Security checklist

Run through this before exposing the service to real users.

## Secrets

- [ ] `JWT_SECRET` is unique per environment, >= 32 random bytes, stored in a
      secret manager — not in `.env` on a server, not in git.
- [ ] `ADMIN_SESSION_SECRET` is a separate random value (empty falls back to
      `JWT_SECRET`; rotating one then invalidates the other).
- [ ] `.env` is gitignored (it is) and `.env.example` holds no real values.
- [ ] DB and Redis credentials rotate independently of the app image.
- [ ] `detect-private-key` pre-commit hook is installed on every dev machine.
- [ ] Production boot refuses placeholder secrets, debug mode, and wildcard CORS
      (see `app/core/config.py`).

## Authentication

- [ ] Argon2 hashing (never MD5/SHA/`==` comparisons).
- [ ] Login, register, refresh and logout are rate limited per IP.
- [ ] Access tokens are short lived (30 min) and carry a `jti`.
- [ ] Refresh tokens are opaque, random, single-use, stored as SHA-256 hashes.
- [ ] Refresh rotation revokes the old token; replay revokes the whole family.
- [ ] Rotation and the one-time grace are claimed with conditional UPDATEs
      (`WHERE revoked_at IS NULL` / `WHERE grace_used_at IS NULL`), so two
      concurrent refreshes cannot both mint a live session.
- [ ] Login validates the password's upper bound only; the 12-char minimum is a
      registration policy, so imported/short legacy passwords fail as 401, not 422.
- [ ] Reuse grace is a **single** retry inside `REFRESH_REUSE_GRACE_SECONDS`
      (default 30s); a second presentation of the same row revokes the family.
      Set it to 0 for strict reuse detection, and never widen it without
      accepting the stolen-token window it opens.
- [ ] Logout revokes the refresh token and denylists the presented access `jti`
      (TTL = its remaining lifetime).
- [ ] Tokens are never logged, never in URLs, never in error responses.
- [ ] Logout denylists the access token; a new logout requires the bearer.
- [ ] Role changes bump `tokens:not_before:<user_id>` so every existing token
      dies on its next request, including demoted admins'.
- [ ] Revocation keys carry a TTL; revocation fails open on Redis errors, so
      alert on `rate(revocation_failures_total[5m]) > 0`
      (`RevocationCheckFailing` in `deploy/prometheus/alerts.yml`) and treat
      Redis as security-critical.
- [ ] Redis is not reachable from untrusted networks (revocation depends on it).

## Authorization and RBAC

- [ ] User-creating endpoints never accept a `role` field.
- [ ] Admin routes depend on `AdminUser`; tests cover 401 / 403 / 200.
- [ ] Role changes go through a service and are auditable (add an audit log if
      compliance needs it).
- [ ] Demotion takes effect on the next request (role is re-read, not cached in
      the token).
- [ ] Queries filter by owner; foreign rows return 404, never 403 with data.
- [ ] The first admin is created out of band (`python -m app.cli promote`), not
      through the API.

## Admin panel

- [ ] `/admin` behind the VPN/ingress or an IP allowlist, never on the public
      internet.
- [ ] Panel login is the admin-only path; regular users get a 400 and no session.
- [ ] Session cookie: `https_only` in production (set), `same_site="lax"` (set),
      bounded lifetime via `ADMIN_SESSION_MAX_AGE_SECONDS` (set, default 8h);
      add CSRF tokens if the panel is ever exposed beyond a trusted network.
- [ ] Panel writes are disabled where a form would corrupt data (users, tokens).
- [ ] `password_hash` is excluded from detail views.
- [ ] Panel login is rate limited by the app per IP
      (`ADMIN_LOGIN_RATE_LIMIT_PER_MINUTE`) **and** at the ingress.
- [ ] Panel admin sessions are re-validated against the DB on every request;
      a demotion or deactivation logs the panel out immediately.

## Redis

- [ ] `requirepass` (or ACLs) enabled and TLS if it crosses a network boundary.
- [ ] Redis port never published publicly; bind to the private network.
- [ ] Rate-limit keys always have a TTL; no unbounded keys.
- [ ] Rate limiting fails open — verify that a Redis outage does not take the API
      down, and alert on `ratelimit_failures_total` (`RateLimitUnavailable`).
- [ ] Redis is not a source of truth: losing it must not lose data.

## Celery worker

- [ ] Broker is Redis with credentials; never exposed publicly.
- [ ] Tasks are idempotent (`task_acks_late` is on) and take primitives only.
- [ ] Task time limits set (300s hard / 240s soft).
- [ ] No user-supplied code or query strings are executed from task arguments.
- [ ] Worker runs as the same non-root user and has the same secret scope it
      actually needs (not the whole API's).
- [ ] Task failures are visible in logs/metrics; retry/backoff is configured
      per task (`autoretry_for`, exponential backoff with jitter, capped).
- [ ] Exactly one `beat` process runs; two schedulers duplicate every periodic
      task.
- [ ] Periodic tasks are safe to run twice (`task_acks_late` + retries).

## Uploads

- [ ] Upload routes stream to the sink with their own cap; nothing buffers the
      whole body in memory (see `services/upload.py`).
- [ ] Upload routes are rate limited (`RATE_LIMIT_PER_MINUTE`): the body-cap
      exemption must not become an unthrottled disk-fill path.
- [ ] Over-cap, empty, and failed writes leave no partial file behind.
- [ ] Client filenames are display-only, never path components.
- [ ] `MAX_UPLOAD_BYTES` matches the ingress/body cap, or the ingress will
      truncate before the app rejects.
- [ ] Content type and malware scanning are handled at ingest if uploaded files
      are ever served to other users.
- [ ] Multi-host deployment moves the sink to object storage (local disk is
      per-container).

## Input and output

- [ ] Pydantic models at every external boundary; no raw `dict` reaching SQL.
- [ ] String lengths, list sizes, pagination limits, and file sizes capped.
- [ ] Password length capped (hash cost) and minimum >= 12.
- [ ] Validation errors echo locations, not values (passwords included).
- [ ] Responses use explicit schemas; never return ORM objects directly.
- [ ] No stack traces or driver messages reach the client.
- [ ] Request bodies are capped by declared length *and* by received bytes, so a
      chunked upload without `Content-Length` is still rejected.

## Transport and headers

- [ ] TLS terminated in front of the app; HSTS set when `https` (middleware).
- [ ] `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
      `Permissions-Policy` set (middleware).
- [ ] `Cache-Control: no-store` on API responses (middleware).
- [ ] CORS allowlist explicit and minimal; credentials only if needed.
- [ ] Forwarded-header handling matches your topology. Do not accept
      client-supplied `X-Forwarded-For` for auth or rate limits.

## Logging and data handling

- [ ] JSON logs with request id; sensitive keys redacted.
- [ ] No bodies, tokens, cookies, or PII in logs.
- [ ] Log retention and access defined by whoever runs the log backend.
- [ ] Sentry: `send_default_pii=False` (set), DSN not committed.

## Rate limiting and abuse

- [ ] Global + auth-specific limits configured; limits live in Redis so replicas
      share them.
- [ ] Consider ingress/WAF limits for volumetric attacks; the app limit is the
      last line, not the first.
- [ ] Admin panel and `/metrics` protected at the network layer.

## Dependencies and images

- [ ] Dependencies pinned by range; lock or hash for production builds.
- [ ] `pip-audit` (or Dependabot/Renovate) runs in CI.
- [ ] Base image pinned to a minor version and rebuilt monthly.
- [ ] Container runs as non-root (it does), no shell needed at runtime.
- [ ] Image scanned in CI (`trivy image`, GitLab container scanning, etc.).

## Deployment and ops

- [ ] `/metrics` not publicly reachable (ingress rule or network policy).
- [ ] `/docs` and `/openapi.json` disabled in production (automatic).
- [ ] Health probes wired: liveness without DB, readiness with DB.
- [ ] Migrations run once (Job), not racing across replicas.
- [ ] DB backups tested, not just configured.
- [ ] Alerting on 5xx rate, latency, readiness failures, and the fail-open
      counters (`RevocationCheckFailing`, `RevocationFailuresSpike`,
      `RateLimitUnavailable`). Rules: `deploy/prometheus/alerts.yml`.
- [ ] Log/metric retention and an incident contact exist.
