"""Pipeline completa sui dati mock `tiny`: import, calcolo, punteggi salvati."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from prospectlens.config import SportConfig
from prospectlens.db import models as m
from prospectlens.pipeline.compute import compute, load_stats
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


def test_compute_without_match_details(db: Session, cfg: SportConfig) -> None:
    # Come i dati reali sul piano Free: nessuna competizione ha formazioni ed eventi
    sport_id = sync_config(db, cfg)
    import_provider(db, MockProvider(cfg, "tiny", seed=7), sport_id)
    for cs in db.scalars(select(m.CompetitionSeason)):
        cs.data_types = [t for t in cs.data_types if t not in ("lineups", "events")]
    db.flush()
    compute(db, sport_id, cfg)
    statuses = set(
        db.scalars(select(m.PlayerGoalScore.status).where(m.PlayerGoalScore.goal_code == "impact"))
    )
    assert statuses == {"not_available"}


def test_compute_with_missing_birth_dates(db: Session, cfg: SportConfig) -> None:
    # Dati reali: alcuni giocatori non hanno la data di nascita. Curve d'età stimate, non default
    th = cfg.thresholds.model_copy(update={"valid_season_minutes": 450, "min_minutes_sample": 200})
    engine = cfg.engine.model_copy(update={"age_curve_min_rows": 5})
    cfg = cfg.model_copy(update={"thresholds": th, "engine": engine})
    sport_id = sync_config(db, cfg)
    import_provider(db, MockProvider(cfg, "tiny", seed=7), sport_id)
    players = list(db.scalars(select(m.Player).order_by(m.Player.id)))
    for p in players[::5]:
        p.birth_date = None
    db.flush()
    result = compute(db, sport_id, cfg)
    assert result["goal_scores"] == 3 * result["player_seasons"]
    no_age = set(db.scalars(select(m.Player.id).where(m.Player.birth_date.is_(None))))
    for s in db.scalars(select(m.PlayerGoalScore).where(m.PlayerGoalScore.status == "ok")):
        assert s.score is not None
        if s.goal_code in ("growth", "longevity"):
            assert s.player_id not in no_age


def test_team_totals_ignore_playoffs(db: Session, cfg: SportConfig) -> None:
    # Dati reali: partite di playoff senza giornata (Serie B) e statistiche giocatore che
    # includono i playoff (Serie C). Le quote minuti e presenze restano al massimo 1.
    sport_id = sync_config(db, cfg)
    import_provider(db, MockProvider(cfg, "tiny", seed=7), sport_id)
    before = load_stats(db, sport_id, cfg).set_index("stat_id")
    match = db.scalars(select(m.Match).order_by(m.Match.id)).first()
    assert match is not None
    db.add(
        m.Match(
            competition_id=match.competition_id,
            season_id=match.season_id,
            source=match.source,
            ext_id="playoff-1",
            matchday=None,
            home_team_id=match.home_team_id,
            away_team_id=match.away_team_id,
            source_id=match.source_id,
        )
    )
    for st in db.scalars(
        select(m.PlayerSeasonStats).where(m.PlayerSeasonStats.team_id == match.home_team_id)
    ):
        st.minutes = int(st.minutes * 1.3)
        st.appearances += 4
    db.flush()
    after = load_stats(db, sport_id, cfg).set_index("stat_id")
    other = after.index[after["team_id"] != match.home_team_id]
    assert (after.loc[other, "team_matches"] == before.loc[other, "team_matches"]).all()
    assert (after["minutes"] / after["team_minutes"]).max() <= 1
    assert (after["appearances"] / after["team_matches"]).max() <= 1
