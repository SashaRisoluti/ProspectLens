# Comandi principali. Richiede: Docker, uv (https://docs.astral.sh/uv/).
SCALE ?= demo
-include .env
export

DB_URL_LOCAL = postgresql+psycopg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@localhost:$(POSTGRES_HOST_PORT)

.PHONY: env up down seed test lint fmt migration coverage import-real

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
	cd backend && uv run ruff check . ../scripts && uv run ruff format --check . ../scripts && uv run mypy prospectlens

fmt:
	cd backend && uv run ruff check --fix . ../scripts && uv run ruff format . ../scripts

migration: env  ## make migration MSG="descrizione"
	docker compose up -d --wait db
	cd backend && DATABASE_URL=$(DB_URL_LOCAL)/$(POSTGRES_DB) uv run alembic upgrade head
	cd backend && DATABASE_URL=$(DB_URL_LOCAL)/$(POSTGRES_DB) uv run alembic revision --autogenerate -m "$(MSG)"

coverage: env  ## verifica la copertura di API-Football (consuma richieste del piano)
	uv run --project backend python scripts/coverage_check.py $(ARGS)

import-real: env  ## esegue ora il piano di import dei dati reali e il calcolo (consuma richieste)
	docker compose up -d --wait db
	cd backend && DATABASE_URL=$(DB_URL_LOCAL)/$(POSTGRES_DB)_real uv run alembic upgrade head
	cd backend && DATABASE_URL=$(DB_URL_LOCAL)/$(POSTGRES_DB)_real uv run prospectlens import-plan $(ARGS)
