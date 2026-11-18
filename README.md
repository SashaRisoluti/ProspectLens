# ProspectLens

Piattaforma di scouting data-driven per club italiani di fascia medio-bassa: trova
giovani talenti in Serie C, Serie D e categorie inferiori con tre "lenti" di ricerca
(crescita rapida, impatto sui risultati, longevità).

Stato: **Fase 1** (struttura, database, dati mock). Piano completo: [docs/PLAN.md](docs/PLAN.md).

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

## Struttura

```
backend/prospectlens/
  config.py         validazione di config/sports/*.yaml
  db/models.py      modello dati (SQLAlchemy), migrazioni in backend/alembic
  providers/        DataProvider: MockProvider (Fase 1), ApiFootball e CSV (Fase 2)
  pipeline/         import idempotente, sincronizzazione della configurazione
  api/              FastAPI
config/sports/football.yaml   ruoli, metriche, soglie, curve d'età, lenti
```

## Dati mock

`MockProvider` genera 5 stagioni (2021-22 → 2025-26) di Serie A, B, C a gironi e D a
gironi, con risultati, formazioni, sostituzioni, gol, assist, cartellini, statistiche
avanzate (solo A, B, C), valori di mercato e infortuni (solo A e B). Un girone di Serie
D non ha formazioni, per verificare che la lente B si disattivi. Squadre, giocatori e
regole under sono **inventati**.

Casi costruiti per le lenti (`ext_id`): `case-growth`, `case-impact`, `case-steady`,
`case-oneseason`, `case-lowminutes`, `case-nolineup`.
