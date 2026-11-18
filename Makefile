# Comandi principali. Richiede: Docker, uv (https://docs.astral.sh/uv/).
SCALE ?= demo
-include .env
export

DB_URL_LOCAL = postgresql+psycopg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@localhost:$(POSTGRES_HOST_PORT)

.PHONY: env up down seed test lint fmt migration coverage import-real real-status

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

real-status:  ## avanzamento dell'import dei dati reali
	@docker compose exec -T db psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)_real -c "\
	SELECT c.name, c.group_code AS girone, s.label AS stagione, count(DISTINCT m.id) AS partite, \
	       count(DISTINCT st.player_id) AS giocatori_con_minuti \
	FROM competition c JOIN season s ON true \
	JOIN match m ON m.competition_id = c.id AND m.season_id = s.id \
	LEFT JOIN player_season_stats st ON st.competition_id = c.id AND st.season_id = s.id \
	GROUP BY 1, 2, 3 ORDER BY 3 DESC, 1, 2;"
	@docker compose logs worker 2>&1 | grep -E "importato|interrotto|richieste reali|prossimo giro" | tail -4
