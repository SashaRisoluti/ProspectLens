"""Pipeline completa sui dati mock `tiny`: import, calcolo, punteggi salvati."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from prospectlens.config import SportConfig
from prospectlens.db import models as m
from prospectlens.pipeline.compute import compute
from prospectlens.pipeline.importer import import_provider
from prospectlens.pipeline.sync_config import sync_config
from prospectlens.providers.mock import MockProvider


def _goal(db: Session, ext: str, goal: str) -> list[m.PlayerGoalScore]:
    q = (
        select(m.PlayerGoalScore)
        .join(m.Player, m.Player.id == m.PlayerGoalScore.player_id)
        .join(m.Season, m.Season.id == m.PlayerGoalScore.season_id)
        .where(m.Player.ext_id == ext, m.PlayerGoalScore.goal_code == goal)
        .order_by(m.Season.label)
    )
    return list(db.scalars(q))


def test_compute_on_mock_data(db: Session, cfg: SportConfig) -> None:
    # `tiny` ha stagioni da 10 partite (900 minuti al massimo): soglie in proporzione
    th = cfg.thresholds.model_copy(update={"valid_season_minutes": 450, "min_minutes_sample": 200})
    cfg = cfg.model_copy(update={"thresholds": th})
    sport_id = sync_config(db, cfg)
    import_provider(db, MockProvider(cfg, "tiny", seed=7), sport_id)
    result = compute(db, sport_id, cfg)

    n_stats = db.scalar(select(func.count()).select_from(m.PlayerSeasonStats))
    assert result["player_seasons"] == db.scalar(select(func.count()).select_from(m.PlayerScore))
    assert result["goal_scores"] == 3 * result["player_seasons"]
    assert (
        db.scalar(
            select(func.count())
            .select_from(m.PlayerSeasonStats)
            .where(m.PlayerSeasonStats.per90.is_not(None))
        )
        == n_stats
    )
    assert db.scalar(select(func.count()).select_from(m.LeagueStrength)) == 5

    scores = list(db.scalars(select(m.PlayerGoalScore).where(m.PlayerGoalScore.status == "ok")))
    assert all(0 <= s.score <= 100 for s in scores if s.score is not None)
    assert all(s.ci_low <= s.ci_high for s in scores if s.ci_low is not None)
    assert all("source" in s.data_used for s in scores)

    assert [s.status for s in _goal(db, "case-oneseason", "growth")] == ["insufficient_history"]
    assert {s.status for s in _goal(db, "case-nolineup", "impact")} == {"not_available"}
    # pochi o zero minuti: nessun punteggio "ok"
    assert "ok" not in {s.status for s in _goal(db, "case-lowminutes", "longevity")}
    growth = _goal(db, "case-growth", "growth")[-1]
    assert growth.status == "ok" and growth.score is not None and growth.score > 50
    steady = _goal(db, "case-steady", "longevity")[-1]
    assert steady.components["seasons_above_threshold"] >= 2

    # portieri: gol subiti in campo e titolarità calcolati dai dati di partita
    gk = db.scalars(
        select(m.PlayerSeasonStats)
        .join(m.Player)
        .where(m.Player.primary_position == "GK", m.PlayerSeasonStats.minutes > 450)
    )
    gk_metrics = [set(s.per90 or {}) for s in gk]
    assert any({"goals_conceded_on_pitch", "minutes_share"} <= ms for ms in gk_metrics)

    # il calcolo è ripetibile: stessi conteggi, nessun duplicato
    compute(db, sport_id, cfg)
    assert db.scalar(select(func.count()).select_from(m.PlayerGoalScore)) == result["goal_scores"]
