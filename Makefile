.DEFAULT_GOAL := help
VENV := .venv
BIN := $(VENV)/bin
UV ?= uv
# Fallback interpreter for `make install-pip` when uv is not available.
PYTHON ?= python3.12

.PHONY: help install install-pip run worker beat test lint fmt migrate migration migration-check promote up down clean

help:
	@echo "install     create .venv and install app + dev deps (needs uv)"
	@echo "install-pip same, using python3.12 -m venv + pip"
	@echo "run         uvicorn with reload on :8000"
	@echo "worker      celery worker (needs Redis)"
	@echo "beat        celery beat scheduler (periodic tasks)"
	@echo "promote     grant admin role (make promote email=a@b.c)"
	@echo "test        pytest"
	@echo "lint        ruff + mypy"
	@echo "fmt         ruff format + autofix"
	@echo "migrate     alembic upgrade head"
	@echo "migration   alembic autogenerate (make migration m='add x')"
	@echo "migration-check  fail if models and migrations disagree (needs DB)"
	@echo "up/down     docker compose (api + postgres)"

install:
	@command -v $(UV) >/dev/null 2>&1 || { \
		echo "uv not found. Install it (https://docs.astral.sh/uv) or run: make install-pip"; \
		exit 1; }
	$(UV) venv --python 3.12
	$(UV) pip install -e ".[dev]"

install-pip:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"

run:
	$(BIN)/uvicorn app.main:app --reload --port 8000

worker:
	$(BIN)/celery -A app.worker.celery_app worker --loglevel=INFO

beat:
	$(BIN)/celery -A app.worker.celery_app beat --loglevel=INFO

promote:
	$(BIN)/python -m app.cli promote $(email)

test:
	$(BIN)/pytest

lint:
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .
	$(BIN)/mypy src

fmt:
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

migrate:
	$(BIN)/alembic upgrade head

migration:
	$(BIN)/alembic revision --autogenerate -m "$(m)"

migration-check:
	$(BIN)/alembic check

up:
	docker compose up --build

down:
	docker compose down -v

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache .mypy_cache
