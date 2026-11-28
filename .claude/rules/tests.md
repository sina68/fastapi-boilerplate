---
paths:
  - "tests/**"
---

# Test rules

- Layout mirrors the code: `tests/<slice>/test_<module>.py`; shared fakes in
  `tests/<slice>/fakes.py`, shared helpers in `tests/helpers.py`.
- `tests/conftest.py` puts `src` on `sys.path` and sets env defaults **before**
  importing the app (`settings` is built at import). Every new env var gets a
  test default there.
- Fixtures: fresh app per test, in-memory SQLite schema, fakeredis, empty
  queues. Override wiring with `app.dependency_overrides` on the slice's
  `dependencies.py` functions, not by monkeypatching internals.
- Unit tests never touch the network: mock `httpx` (e.g. `httpx.MockTransport`),
  never call a real broker (call the async task function directly). Real
  Postgres/Redis/broker only in integration tests.
- One behaviour per test, named `test_<what>_<condition>`. Assert status code,
  error `code`, and the side effect that would silently break (row written,
  cursor advanced, health status changed, counter incremented).
- Must-have per new route: happy path, 401 unauthenticated, 404 other user's /
  missing row, 422 validation. Admin routes also 403 for a regular user.
- Connectors (architecture.md §20.2–20.3): store real responses under
  `tests/connectors/fixtures/<connector>/` (HTML, RSS/Atom XML, Telegram
  pages, site-specific pages, HTTP errors, truncated responses) with the capture
  date in the file name; snapshot the normalized output next to each fixture;
  when a site changes its markup add the new fixture and keep the old one.
- Unit tests for `processing/`: normalization, URL canonicalization, hash,
  dedupe, validation, retry classification, checkpoint logic.
- Pipeline tests: idempotency (same run twice → no duplicates), retry policy
  (timeout/429/5xx retried, other 4xx not), zero-new-items run is `succeeded`,
  health counter transitions, one invalid item does not fail the run.
- Integration tests (`@pytest.mark.integration`, real Postgres + Redis, run by
  `make test-integration` / CI, skipped by `make test`): unique constraints,
  upsert, concurrent claim with `FOR UPDATE SKIP LOCKED`, checkpoint only after
  commit, crash recovery of a stuck claim, Celery retry on a real broker,
  Postgres FTS on Persian fixtures.
- Security tests for the fetcher: private/loopback/metadata IPs, redirect to an
  internal IP, DNS rebinding, oversize response, timeout, invalid scheme/URL,
  and 401/403 on every admin action.
- Bug fix = a test that fails before the fix and passes after, in the same MR.
- No `sleep` in tests; freeze or inject time.
- Fixtures contain no real personal data, tokens or credentials.
