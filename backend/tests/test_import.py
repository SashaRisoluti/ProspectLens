from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from prospectlens.config import SportConfig
from prospectlens.db import models as m
from prospectlens.pipeline.importer import import_provider
from prospectlens.pipeline.sync_config import sync_config
from prospectlens.providers.base import SeasonBundle
from prospectlens.providers.mock import MockProvider

COUNTED = (
    m.Match,
    m.Appearance,
    m.MatchEvent,
    m.PlayerSeasonStats,
    m.Player,
    m.PlayerTeamSeason,
    m.CompetitionSeason,
    m.MarketValueSnapshot,
    m.InjuryRecord,
)


def _counts(db: Session) -> dict[str, int]:
    return {t.__tablename__: db.scalar(select(func.count()).select_from(t)) or 0 for t in COUNTED}


def test_import_is_complete_and_idempotent(
    db: Session, cfg: SportConfig, tiny_bundles: list[SeasonBundle]
) -> None:
    sport_id = sync_config(db, cfg)
    import_provider(db, MockProvider(cfg, "tiny", seed=7), sport_id)
    first = _counts(db)

    assert first["match"] == sum(len(b.matches) for b in tiny_bundles)
    assert first["appearance"] == sum(len(b.appearances) for b in tiny_bundles)
    assert first["match_event"] == sum(len(b.events) for b in tiny_bundles)
    assert first["player"] == len({p.ext_id for b in tiny_bundles for p in b.players})
    assert first["competition_season"] == len(tiny_bundles)

    import_provider(db, MockProvider(cfg, "tiny", seed=7), sport_id)
    assert _counts(db) == first

    defs = db.scalars(select(m.MetricDefinition.code)).all()
    assert set(defs) == {x.code for x in cfg.metrics}
    loan = db.scalars(select(m.PlayerTeamSeason).where(m.PlayerTeamSeason.status == "loan")).first()
    assert loan is not None and loan.owner_team_id is not None


def test_healthz(db: Session) -> None:
    from prospectlens.api.main import app
    from prospectlens.db.session import get_engine

    get_engine.cache_clear()
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}
