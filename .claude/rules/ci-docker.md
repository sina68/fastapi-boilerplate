---
paths:
  - "Dockerfile"
  - "entrypoint.sh"
  - ".gitlab-ci.yml"
  - "docker-compose*.yml"
  - "pyproject.toml"
  - "uv.lock"
  - ".pre-commit-config.yaml"
  - "Makefile"
---

# Docker, entrypoint, CI and tooling rules

Same shape as `notification-python` / `translation`; registry and index URLs
are variables because this service deploys outside the MCI network.

## Tooling

- `uv` is the package manager. `pyproject.toml` uses `[dependency-groups] dev`,
  `[tool.uv] package = false`, and `uv.lock` is committed. Install with
  `uv sync --frozen`; change deps with `uv add` / `uv lock`, never by hand-editing
  the lock.
- Python version pinned in `.python-version` (3.14.x) and
  `requires-python = ">=3.14,<3.15"`; Docker base image and CI image use the
  same patch version.
- Package index is configured in `[[tool.uv.index]]` (or `UV_DEFAULT_INDEX`);
  credentials only via env (`UV_INDEX_<NAME>_USERNAME/PASSWORD`), never in
  files.
- pre-commit hooks are optional for developers; the gates that count are
  `make lint` / `make test` before push (enforced for Claude by
  `.claude/hooks/guard_git.py`) and the CI `quality` / `test` stages.

## Dockerfile

- `FROM <registry>/python:3.14.x-slim` (pinned patch; registry is a build arg).
- `ENV PYTHONPATH=/home/app/src PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Asia/Tehran`.
- `WORKDIR /home/app`; copy `pyproject.toml uv.lock` first, `uv sync --frozen
  --no-dev --no-install-project`, then `src/` and `entrypoint.sh` (layer cache).
- Create `/home/app/logs`; run as a non-root user; no build secrets left in
  layers (use build args/secret mounts only for the index credentials).
- `apt-get` only what is needed, `--no-install-recommends`, clean lists.

## entrypoint.sh

- `set -euo pipefail`. Wait for Postgres (like the other services) using env
  passed through `os.environ`, never interpolated into a script, and **never
  echo credentials** (one reference service prints `POSTGRES_PASSWORD` while
  waiting; do not copy that).
- `alembic -c src/alembic.ini upgrade head` only when `RUN_MIGRATIONS=1`
  (local/dev compose). In Kubernetes migrations run in the Helm hook Job.
  Alembic itself takes no lock, so `alembic/env.py` must hold a Postgres
  advisory lock while migrating; never claim otherwise in comments.
- If arguments are given, `exec "$@"` (worker/beat/scripts reuse the image);
  otherwise `exec uvicorn main:app --app-dir src --host 0.0.0.0 --port "${PORT}"
  --workers 1 --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS}"`.
  `--reload` only when `ENVIRONMENT=development`.

## GitLab CI

Stages: `quality` → `test` → `build` → `scan` → `deploy`.

- `quality` (MRs and `dev`): `uv sync --frozen`, `ruff check .`,
  `ruff format --check .`, `mypy`, single Alembic head, `helm lint` +
  `helm template` for every env values file.
- `test` (MRs and `dev`): `pytest`; `migrations` job against a Postgres service
  (`upgrade head`, `alembic check`, `downgrade base`, `upgrade head`). The other
  services only run ruff in CI; this repo keeps tests in CI — do not remove them.
- `build`: on `dev`/`stage` tag image `$CI_COMMIT_SHORT_SHA` + ref slug; on
  `vX.Y.Z` tags, the tag. Registry/image path are CI variables.
- `scan`: container scan of the built image.
- `deploy`: GitOps — bump `image.tag` in the env values file the CD tool
  (Argo CD) watches; never `kubectl apply` from CI.
- Pin CI images; cache `.venv`/uv cache keyed on `uv.lock`.
