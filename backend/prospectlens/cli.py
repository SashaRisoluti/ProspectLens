"""Riga di comando: `prospectlens <comando>`."""

import argparse
import logging
import time

from prospectlens.config import load_sport
from prospectlens.db.session import new_session
from prospectlens.pipeline.importer import import_provider
from prospectlens.pipeline.sync_config import sync_config
from prospectlens.providers.mock import SCALES, MockProvider
from prospectlens.settings import get_settings

log = logging.getLogger("prospectlens")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="prospectlens")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync-config", help="copia metriche e lenti dal YAML al database")
    seed = sub.add_parser("seed", help="genera e importa i dati mock")
    seed.add_argument("--scale", choices=sorted(SCALES), default="demo")
    seed.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    cfg = load_sport(get_settings().config_dir)
    with new_session() as session:
        sport_id = sync_config(session, cfg)
        log.info(
            "configurazione sincronizzata: %d metriche, %d lenti", len(cfg.metrics), len(cfg.goals)
        )
        if args.cmd == "seed":
            t = time.monotonic()
            report = import_provider(session, MockProvider(cfg, args.scale, args.seed), sport_id)
            log.info(
                "import mock (%s) in %.0f s: %d bundle, %s",
                args.scale,
                time.monotonic() - t,
                report.bundles,
                report.counts,
            )


if __name__ == "__main__":
    main()
