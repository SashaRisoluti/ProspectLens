"""Riga di comando: `prospectlens <comando>`."""

import argparse
import logging
import os
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from prospectlens.config import SportConfig, load_sport
from prospectlens.db.session import new_session
from prospectlens.pipeline.compute import compute
from prospectlens.pipeline.importer import import_provider
from prospectlens.pipeline.sync_config import sync_config
from prospectlens.providers.api_football import ApiFootballProvider, LeagueSeason
from prospectlens.providers.api_football_client import (
    ApiFootballClient,
    BudgetExhausted,
    api_key_from_env,
)
from prospectlens.providers.base import CompetitionRec, DataProvider, SeasonRec
from prospectlens.providers.csv_import import CsvImportProvider, load_mapping
from prospectlens.providers.mock import SCALES, MockProvider
from prospectlens.settings import get_settings

log = logging.getLogger("prospectlens")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="prospectlens")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync-config", help="copia metriche e lenti dal YAML al database")
    sub.add_parser("compute", help="calcola metriche, Indice talento e lenti")
    worker = sub.add_parser("worker", help="esegue `compute` ogni giorno all'ora indicata")
    worker.add_argument("--hour", type=int, default=int(os.environ.get("PIPELINE_HOUR", 5)))
    seed = sub.add_parser("seed", help="genera e importa i dati mock")
    seed.add_argument("--scale", choices=sorted(SCALES), default="demo")
    seed.add_argument("--seed", type=int, default=42)
    api = sub.add_parser("import-api", help="importa da API-Football (consuma richieste)")
    api.add_argument(
        "--league",
        type=int,
        required=True,
        action="append",
        help="ID API della competizione (vedi docs/data-coverage.md)",
    )
    api.add_argument("--season", type=int, required=True, help="anno di inizio, es. 2024")
    api.add_argument("--budget", type=int, default=None, help="richieste reali massime")
    api.add_argument(
        "--with-match-details",
        action="store_true",
        help="formazioni ed eventi: una richiesta per partita (serve per la lente B)",
    )
    csv_ = sub.add_parser("import-csv", help="importa un file CSV di statistiche stagionali")
    csv_.add_argument("file", type=Path)
    csv_.add_argument("--mapping", default="wyscout", help="nome del file in config/csv")
    csv_.add_argument("--competition", required=True, help='es. "Serie D"')
    csv_.add_argument("--level", type=int, required=True, help="livello nella piramide")
    csv_.add_argument("--group", default=None, help="girone, es. A")
    csv_.add_argument("--season", required=True, help="es. 2024-25")
    plan = sub.add_parser(
        "import-plan", help="esegue il piano di import API (API_IMPORT_PLAN), poi calcola"
    )
    plan.add_argument("--plan", default=os.environ.get("API_IMPORT_PLAN", ""))
    plan.add_argument("--budget", type=int, default=int(os.environ.get("API_DAILY_BUDGET", 95)))
    args = parser.parse_args(argv)

    settings = get_settings()
    cfg = load_sport(settings.config_dir)
    provider: DataProvider | None = None
    if args.cmd == "seed":
        provider = MockProvider(cfg, args.scale, args.seed)
    elif args.cmd == "import-api":
        client = ApiFootballClient(
            api_key_from_env(), settings.cache_dir / "api-football", budget=args.budget
        )
        targets = [LeagueSeason(lg, args.season) for lg in args.league]
        provider = ApiFootballProvider(client, targets, args.with_match_details)
    elif args.cmd == "import-csv":
        year = int(args.season[:4])
        group = args.group.upper() if args.group else None
        comp = CompetitionRec(
            f"{args.competition}-{group or ''}".lower().replace(" ", "-"),
            args.competition,
            "IT",
            args.level,
            group,
        )
        season = SeasonRec(
            f"{year}-{(year + 1) % 100:02d}", date(year, 7, 1), date(year + 1, 6, 30)
        )
        mapping = load_mapping(settings.config_dir / "csv" / f"{args.mapping}.yaml")
        provider = CsvImportProvider(args.file, mapping, comp, season)
    with new_session() as session:
        sport_id = sync_config(session, cfg)
        log.info(
            "configurazione sincronizzata: %d metriche, %d lenti", len(cfg.metrics), len(cfg.goals)
        )
        if provider is not None:
            t = time.monotonic()
            try:
                report = import_provider(session, provider, sport_id)
            except BudgetExhausted as exc:
                session.rollback()
                log.warning(
                    "import interrotto (%s): le competizioni complete sono salvate, "
                    "rilancia lo stesso comando per riprendere dalla cache",
                    exc,
                )
                return
            log.info(
                "import %s in %.0f s: %d bundle, %s",
                provider.source,
                time.monotonic() - t,
                report.bundles,
                report.counts,
            )
        if args.cmd == "import-plan":
            _import_plan(session, sport_id, args.plan, args.budget)
        if args.cmd in ("seed", "compute", "import-api", "import-csv", "import-plan"):
            _compute(session, sport_id, cfg)
        if args.cmd == "worker":
            _worker(args.hour, sport_id, cfg)


def parse_plan(text: str) -> list[tuple[list[int], int]]:
    """'138,942,943:2024; 136:2024' -> [([138, 942, 943], 2024), ([136], 2024)]."""
    plan = []
    for item in text.strip().strip("'\"").replace("\n", ";").split(";"):
        if item.strip():
            leagues, season = item.split(":")
            plan.append(([int(x) for x in leagues.split(",")], int(season)))
    return plan


def _import_plan(session: Session, sport_id: int, plan_text: str, budget: int) -> None:
    """Importa le voci del piano in ordine finché c'è budget. Le voci già importate si
    rileggono dalla cache senza consumare richieste: il piano si completa in più giorni."""
    plan = parse_plan(plan_text)
    if not plan:
        log.info("nessun piano di import (API_IMPORT_PLAN vuoto)")
        return
    settings = get_settings()
    client = ApiFootballClient(
        api_key_from_env(), settings.cache_dir / "api-football", budget=budget
    )
    for leagues, season in plan:
        provider = ApiFootballProvider(client, [LeagueSeason(lg, season) for lg in leagues])
        try:
            report = import_provider(session, provider, sport_id)
        except BudgetExhausted as exc:
            session.rollback()
            log.warning(
                "piano interrotto a %s:%s (%s): riprende al prossimo giro", leagues, season, exc
            )
            break
        log.info("importato %s:%s %s", leagues, season, report.counts)
    log.info("richieste reali usate: %d", client.used)


def _compute(session: Session, sport_id: int, cfg: SportConfig) -> None:
    t = time.monotonic()
    result = compute(session, sport_id, cfg)
    log.info("calcolo completato in %.0f s: %s", time.monotonic() - t, result)


def _worker(hour: int, sport_id: int, cfg: SportConfig) -> None:
    """Ciclo minimo: esegue subito il piano di import (se configurato) e il calcolo, poi
    ogni giorno all'ora indicata (UTC). L'esecuzione all'avvio recupera i giorni persi se
    la macchina era spenta."""
    while True:
        try:
            with new_session() as session:
                if os.environ.get("API_IMPORT_PLAN") and os.environ.get("API_FOOTBALL_KEY"):
                    _import_plan(
                        session,
                        sport_id,
                        os.environ["API_IMPORT_PLAN"],
                        int(os.environ.get("API_DAILY_BUDGET", 95)),
                    )
                _compute(session, sport_id, cfg)
        except Exception:
            log.exception("import o calcolo fallito, riprovo al prossimo giro")
        now = datetime.now(UTC)
        run_at = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if run_at <= now:
            run_at += timedelta(days=1)
        log.info("prossimo giro: %s", run_at.isoformat())
        time.sleep((run_at - now).total_seconds())


if __name__ == "__main__":
    main()
