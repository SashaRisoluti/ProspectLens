# Comandi principali. Richiede: Docker, uv (https://docs.astral.sh/uv/).
SCALE ?= demo
-include .env
export

DB_URL_LOCAL = postgresql+psycopg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@localhost:$(POSTGRES_HOST_PORT)

.PHONY: env up down seed test lint fmt migration

env:
	@test -f .env || (cp .env.example .env && echo "creato .env da .env.example")

up: env
	docker compose up -d --build --wait

down:
	docker compose down

seed: up  ## make seed SCALE=tiny|demo|full
	docker compose exec api prospectlens seed --scale $(SCALE)

test: env
	docker compose up -d --wait db
	cd backend && TEST_DATABASE_URL=$(DB_URL_LOCAL)/$(POSTGRES_DB)_test uv run pytest

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy prospectlens

fmt:
	cd backend && uv run ruff check --fix . && uv run ruff format .

migration: env  ## make migration MSG="descrizione"
	docker compose up -d --wait db
	cd backend && DATABASE_URL=$(DB_URL_LOCAL)/$(POSTGRES_DB) uv run alembic upgrade head
	cd backend && DATABASE_URL=$(DB_URL_LOCAL)/$(POSTGRES_DB) uv run alembic revision --autogenerate -m "$(MSG)"
