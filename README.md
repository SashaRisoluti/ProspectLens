# ProspectLens

Piattaforma di scouting data-driven per club italiani di fascia medio-bassa: trova
giovani talenti in Serie C, Serie D e categorie inferiori con tre "lenti" di ricerca
(crescita rapida, impatto sui risultati, longevità).

Stato: **Fase 2** (fonti dati reali: API-Football e CSV). Piano completo: [docs/PLAN.md](docs/PLAN.md).

## Avvio rapido

Requisiti: Docker, [uv](https://docs.astral.sh/uv/) (solo per test e lint locali), `make`.

```sh
make up                 # crea .env da .env.example, avvia db e api
make seed               # genera e importa i dati mock (SCALE=tiny|demo|full, default demo)
curl localhost:8000/healthz
```

Altri comandi:

| Comando | Effetto |
|---|---|
| `make test` | test Python (usa il database `<POSTGRES_DB>_test` del container) |
| `make lint` | Ruff, formattazione, mypy |
| `make fmt` | corregge formattazione e import |
| `make migration MSG="..."` | genera una migrazione Alembic dai modelli |
| `make down` | ferma lo stack |
| `make coverage` | verifica la copertura di API-Football e scrive [docs/data-coverage.md](docs/data-coverage.md) (consuma richieste; `ARGS="--budget 50"`) |

## Dati reali

La chiave va in `.env` (`API_FOOTBALL_KEY`). Le risposte del fornitore sono salvate in
`data/cache/` (non versionata): ripetere un comando non consuma richieste.

```sh
# una o più competizioni (ID da docs/data-coverage.md), stagione = anno di inizio
docker compose exec api prospectlens import-api --league 426 --season 2024 --budget 90

# file CSV del club (mappatura colonne in config/csv/wyscout.yaml)
docker compose exec api prospectlens import-csv /app/data/export.csv \
    --competition "Serie D" --level 4 --group A --season 2024-25
```

Se il budget di richieste finisce a metà, il comando si ferma senza importare la
competizione incompleta: rilancialo il giorno dopo e riparte dalla cache.

## Struttura

```
backend/prospectlens/
  config.py         validazione di config/sports/*.yaml
  db/models.py      modello dati (SQLAlchemy), migrazioni in backend/alembic
  providers/        DataProvider: Mock, ApiFootball (+ client con cache), CsvImport
  pipeline/         import idempotente, sincronizzazione della configurazione
  api/              FastAPI
config/sports/football.yaml   ruoli, metriche, soglie, curve d'età, lenti
config/csv/                   mappature delle colonne dei file CSV
scripts/coverage_check.py     verifica della copertura dei dati
```

## Dati mock

`MockProvider` genera 5 stagioni (2021-22 → 2025-26) di Serie A, B, C a gironi e D a
gironi, con risultati, formazioni, sostituzioni, gol, assist, cartellini, statistiche
avanzate (solo A, B, C), valori di mercato e infortuni (solo A e B). Un girone di Serie
D non ha formazioni, per verificare che la lente B si disattivi. Squadre, giocatori e
regole under sono **inventati**.

Casi costruiti per le lenti (`ext_id`): `case-growth`, `case-impact`, `case-steady`,
`case-oneseason`, `case-lowminutes`, `case-nolineup`.
