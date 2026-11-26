"""Job di calcolo: legge i dati importati, esegue il motore, salva punteggi e coefficienti.

Ordine: metriche per 90 e Livello nella lega -> forza delle leghe -> Livello confrontabile
tra leghe -> curve d'età e Indice talento -> lenti A, B, C -> salvataggio.
Ogni punteggio porta con sé affidabilità e dati usati (tipi di dato, fonte, data).
"""

import logging
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from prospectlens.config import SportConfig
from prospectlens.db import models as m
from prospectlens.engine.basics import add_metrics, ecdf_pct, metric_payload
from prospectlens.engine.context import (
    add_age_context,
    default_growth,
    estimate_league_strength,
    fit_age_curves,
)
from prospectlens.engine.impact import REQUIRED, impact_by_team
from prospectlens.engine.lenses import growth_lens, longevity_lens

log = logging.getLogger(__name__)
ENGINE_VERSION = "engine-0.1"

STATS_SQL = """
SELECT s.id AS stat_id, s.player_id, s.team_id, s.competition_id, s.season_id, s.minutes,
       s.appearances, s.raw, c.level AS comp_level, cs.data_types,
       EXTRACT(YEAR FROM se.start_date)::int AS season_year, se.start_date AS season_start,
       p.birth_date, p.primary_position, ds.provider AS source, ds.fetched_at
FROM player_season_stats s
JOIN competition c ON c.id = s.competition_id
JOIN season se ON se.id = s.season_id
JOIN player p ON p.id = s.player_id
JOIN data_source ds ON ds.id = s.source_id
LEFT JOIN competition_season cs
       ON cs.competition_id = s.competition_id AND cs.season_id = s.season_id
WHERE c.sport_id = :sport_id
"""


CONCEDED_SQL = """
SELECT a.player_id, a.team_id, m.competition_id, m.season_id, count(e.id) AS conceded
FROM appearance a
JOIN match m ON m.id = a.match_id
LEFT JOIN match_event e
       ON e.match_id = a.match_id AND e.type IN ('goal', 'own_goal')
      AND e.team_id <> a.team_id AND e.minute > a.minute_in AND e.minute <= a.minute_out
GROUP BY 1, 2, 3, 4
"""


def _read(session: Session, sql: str, **params: Any) -> pd.DataFrame:
    return pd.read_sql(text(sql), session.connection(), params=params)


def load_stats(session: Session, sport_id: int, cfg: SportConfig) -> pd.DataFrame:
    df = _read(session, STATS_SQL, sport_id=sport_id)
    df["macro"] = df["primary_position"].map(cfg.macro_of)
    unknown = df["macro"].isna().sum()
    if unknown:
        log.warning("%d righe con ruolo sconosciuto escluse", unknown)
    df = df[df["macro"].notna()].copy()
    df["data_types"] = df["data_types"].map(lambda t: set(t or []))
    birth = pd.to_datetime(df["birth_date"])
    df["age"] = (pd.to_datetime(df["season_start"]) - birth).dt.days / 365.25
    df["birth_year"] = birth.dt.year
    # solo stagione regolare (con giornata): in Serie B le statistiche escludono playoff e playout
    team_games = _read(
        session,
        """
        SELECT team_id, competition_id, season_id, count(*) AS n FROM (
          SELECT home_team_id AS team_id, competition_id, season_id FROM match
           WHERE matchday IS NOT NULL
          UNION ALL SELECT away_team_id, competition_id, season_id FROM match
           WHERE matchday IS NOT NULL) t
        GROUP BY 1, 2, 3""",
    )
    df = df.merge(team_games, on=["team_id", "competition_id", "season_id"], how="left")
    # in Serie C invece le statistiche includono i playoff: il totale della squadra non è mai
    # sotto quanto giocato dai suoi giocatori
    team = df.groupby(["team_id", "competition_id", "season_id"])
    norm = cfg.normalization
    df["team_minutes"] = np.fmax(
        df["n"] * norm.per, team["minutes"].transform("sum") / norm.players_on_field
    )
    df["team_matches"] = np.fmax(df["n"], team["appearances"].transform("max"))
    # gol subiti dalla squadra mentre il giocatore era in campo (da formazioni ed eventi)
    conceded = _read(session, CONCEDED_SQL)
    df = df.drop(columns="n").merge(
        conceded, on=["player_id", "team_id", "competition_id", "season_id"], how="left"
    )
    df["raw"] = [
        r | {"goals_conceded_on_pitch": float(c)} if pd.notna(c) else r
        for r, c in zip(df["raw"], df["conceded"], strict=True)
    ]
    df["raw"] = _drop_unrecorded(df)
    return df.drop(columns="conceded")


def _drop_unrecorded(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Un dato quasi sempre 0 in una competizione e stagione (diverso da 0 in meno dell'1%
    delle righe) non è rilevato dal fornitore: in Serie C gli assist valgono 0 per tutti
    tranne un caso isolato. Si toglie, così risulta mancante e non uno 0 falso. Il dato
    vero più raro, le espulsioni, riguarda circa il 10% dei giocatori."""
    missing: dict[tuple[int, int], set[str]] = {}
    for key, raws in df.groupby(["competition_id", "season_id"])["raw"]:
        if len(raws) >= 30:  # con pochi giocatori uno 0 per tutti può essere vero
            keys = set().union(*raws)
            missing[key] = {k for k in keys if sum(bool(r.get(k)) for r in raws) < 0.01 * len(raws)}
    return [
        {k: v for k, v in r.items() if k not in missing.get((c, s), set())}
        for r, c, s in zip(df["raw"], df["competition_id"], df["season_id"], strict=True)
    ]


def aggregate_player_seasons(rows: pd.DataFrame, cfg: SportConfig) -> pd.DataFrame:
    """Una riga per giocatore e stagione. Competizione principale = più minuti; Livello =
    media dei Livelli delle righe pesata per i minuti."""
    r = rows.sort_values("minutes", ascending=False)
    primary = r.drop_duplicates(["player_id", "season_id"]).set_index(["player_id", "season_id"])
    w = r["minutes"].where(r["level_row"].notna(), 0)
    agg = (
        r.assign(wl=r["level_row"].fillna(0) * w, w=w)
        .groupby(["player_id", "season_id"])
        .agg(
            minutes=("minutes", "sum"),
            appearances=("appearances", "sum"),
            team_matches=("team_matches", "sum"),
            wl=("wl", "sum"),
            w=("w", "sum"),
        )
    )
    ps = primary[
        [
            "competition_id",
            "comp_level",
            "season_year",
            "macro",
            "age",
            "offset",
            "z_within",
            "data_types",
            "level_n",
            "level_perf_n",
            "level_metrics",
            "relative_age",
            "minutes_share",
            "share_vs_peers",
            "precocity",
            "source",
            "fetched_at",
        ]
    ].join(agg)
    ps["level"] = (ps["wl"] / ps["w"]).where(ps["w"] > 0)
    ps["valid"] = ps["minutes"] >= cfg.thresholds.valid_season_minutes
    return ps.drop(columns=["wl", "w"]).reset_index()


def pct_by_group(
    df: pd.DataFrame, value: str, ref_mask: pd.Series, extra: list[str] | None = None
) -> dict[str, pd.Series]:
    """Percentile di `value` (e delle colonne `extra`, es. estremi dell'intervallo) dentro
    (stagione, macro-ruolo), rispetto alle righe di riferimento."""
    cols = [value, *(extra or [])]
    out = {c: pd.Series(np.nan, index=df.index) for c in cols}
    for _, idx in df.groupby(["season_id", "macro"]).groups.items():
        ref = df.loc[idx][ref_mask.loc[idx]][value]
        for c in cols:
            out[c].loc[idx] = ecdf_pct(df.loc[idx, c], ref)
    return out


def _clean(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_clean(x) for x in v]
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and not np.isfinite(v):
        return None
    return v


def compute(session: Session, sport_id: int, cfg: SportConfig) -> dict[str, int]:
    rows = load_stats(session, sport_id, cfg)
    if rows.empty:
        log.warning("nessuna statistica da elaborare")
        return {}
    rows = add_age_context(add_metrics(rows, cfg))

    # forza delle leghe (coefficienti fissati dall'amministratore restano fissi)
    comp_level = dict(zip(rows["competition_id"], rows["comp_level"], strict=False))
    first = rows.sort_values("minutes", ascending=False).drop_duplicates(["player_id", "season_id"])
    first = first[first["minutes"] >= cfg.thresholds.min_minutes_sample]
    strength = estimate_league_strength(
        first,
        comp_level,
        cfg,
        lambda macro, age: float(default_growth(cfg.age_curves[macro], np.asarray(age))),
    )
    admin_q = select(m.LeagueStrength.competition_id, m.LeagueStrength.coefficient).where(
        m.LeagueStrength.source == "admin"
    )
    admin = {int(c): float(v) for c, v in session.execute(admin_q).all()}
    strength["coefficient"] = [
        admin.get(c, v)
        for c, v in zip(strength["competition_id"], strength["coefficient"], strict=True)
    ]
    offset = dict(zip(strength["competition_id"], strength["coefficient"], strict=True))
    rows["offset"] = rows["competition_id"].map(offset)
    rows["level_row"] = rows["z_within"] + rows["offset"]

    ps = aggregate_player_seasons(rows, cfg)
    ps["level_pct"] = pct_by_group(ps, "level", ps["valid"] & ps["level"].notna())["level"]
    curves = fit_age_curves(ps[ps["valid"]], cfg)
    ps["expected_level"] = [
        float(curves.expected(mc, a)) if np.isfinite(a) else np.nan
        for mc, a in zip(ps["macro"], ps["age"], strict=True)
    ]
    ps["talent_resid"] = ps["level"] - ps["expected_level"]
    ps["talent_index"] = pct_by_group(ps, "talent_resid", ps["valid"] & ps["talent_resid"].notna())[
        "talent_resid"
    ]
    log.info(
        "Livello calcolato per %d giocatori-stagione; curve d'età: %s",
        ps["level"].notna().sum(),
        curves.describe(),
    )

    goal_rows = [
        _score_growth(ps, curves, cfg),
        _score_impact(session, ps, rows, cfg),
        _score_longevity(ps, cfg),
    ]
    _persist(session, rows, ps, strength, admin, goal_rows, cfg)
    return {"player_seasons": len(ps), "goal_scores": sum(len(g) for g in goal_rows)}


# --------------------------------------------------------------------------- lenti


def _to_percentiles(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    ok = df["status"] == "ok"
    pct = pct_by_group(df, "raw", ok, ["ci_low_raw", "ci_high_raw"])
    df["score"] = pct["raw"].where(ok)
    df["ci_low"] = pct["ci_low_raw"].where(ok)
    df["ci_high"] = pct["ci_high_raw"].where(ok)
    return df


def _score_growth(ps: pd.DataFrame, curves: Any, cfg: SportConfig) -> pd.DataFrame:
    df = _to_percentiles(growth_lens(ps, curves, cfg))
    df["goal_code"] = "growth"
    return df


def _score_longevity(ps: pd.DataFrame, cfg: SportConfig) -> pd.DataFrame:
    df = longevity_lens(ps, cfg)
    df["score"], df["ci_low"], df["ci_high"] = df["raw"], df["ci_low_raw"], df["ci_high_raw"]
    df["goal_code"] = "longevity"
    return df


def _score_impact(
    session: Session, ps: pd.DataFrame, rows: pd.DataFrame, cfg: SportConfig
) -> pd.DataFrame:
    cs = _read(session, "SELECT competition_id, season_id, data_types FROM competition_season")
    comp_ok = {(c, s) for c, s, t in cs.itertuples(index=False) if set(t or []) >= REQUIRED}
    matches = _read(
        session,
        """SELECT id, competition_id, season_id, home_team_id, away_team_id,
                                       home_goals, away_goals FROM match""",
    )
    apps = _read(
        session, "SELECT match_id, player_id, team_id, minute_in, minute_out FROM appearance"
    )
    goals = _read(
        session,
        """SELECT match_id, team_id, player_id, related_player_id, minute, type
                              FROM match_event WHERE type IN ('goal', 'own_goal')""",
    )
    by_team = impact_by_team(matches, apps, goals, comp_ok, cfg)
    best = (
        by_team.sort_values("on_minutes", ascending=False)
        .drop_duplicates(["player_id", "season_id"])
        .set_index(["player_id", "season_id"])
        if not by_team.empty
        else pd.DataFrame()
    )
    p = cfg.engine.impact
    valid_min = cfg.thresholds.valid_season_minutes
    out = []
    for r in ps.itertuples():
        base = {
            "player_id": r.player_id,
            "season_id": r.season_id,
            "macro": r.macro,
            "ci_low_raw": np.nan,  # colonne presenti anche se nessuna riga è "ok"
            "ci_high_raw": np.nan,
        }
        key = (r.player_id, r.season_id)
        if (r.competition_id, r.season_id) not in comp_ok:
            out.append(
                {
                    **base,
                    "status": "not_available",
                    "reliability": "low",
                    "raw": np.nan,
                    "components": {"reason": "formazioni o cambi non disponibili"},
                }
            )
            continue
        if key not in best.index or best.loc[key, "on_minutes"] < cfg.thresholds.min_minutes_sample:
            out.append(
                {
                    **base,
                    "status": "insufficient_history",
                    "reliability": "low",
                    "raw": np.nan,
                    "components": {},
                }
            )
            continue
        b = best.loc[key]
        rel = "low"
        if b["on_minutes"] >= valid_min and b["off_minutes"] >= p.min_off_minutes:
            rel = "medium"
        if b["on_minutes"] >= 2 * valid_min and b["off_minutes"] >= 3 * p.min_off_minutes:
            rel = "high"
        comp = {
            k: b[k]
            for k in (
                "on_minutes",
                "off_minutes",
                "onoff_goal_diff_p90",
                "onoff_goal_diff_p90_raw",
                "onoff_ppm",
                "onoff_ppm_raw",
                "rank_in_team",
                "team_players",
                "decisive_points",
            )
        }
        comp["adjusted_impact"] = round(float(b["adjusted_impact"]), 4)
        comp["decisive_points_p90"] = round(b["decisive_points"] / b["on_minutes"] * 90, 3)
        comp["team_id"] = int(b["team_id"])
        out.append(
            {
                **base,
                "status": "ok",
                "reliability": rel,
                "raw": b["adjusted_impact"],
                "ci_low_raw": b["ci_low"],
                "ci_high_raw": b["ci_high"],
                "components": comp,
            }
        )
    df = _to_percentiles(pd.DataFrame(out))
    df["goal_code"] = "impact"
    return df


# --------------------------------------------------------------------------- salvataggio


def _reliability(r: Any, cfg: SportConfig) -> str:
    if not np.isfinite(r.level) or r.minutes < cfg.thresholds.min_minutes_sample:
        return "low"
    # poche metriche di prestazione (es. solo gol, o solo minuti e cartellini): Livello indiretto
    if r.level_perf_n < cfg.engine.min_performance_metrics:
        return "low"
    if r.valid and "player_stats_advanced" in r.data_types:
        return "high"
    return "medium"


def _persist(
    session: Session,
    rows: pd.DataFrame,
    ps: pd.DataFrame,
    strength: pd.DataFrame,
    admin: dict[int, float],
    goal_rows: list[pd.DataFrame],
    cfg: SportConfig,
) -> None:
    session.execute(
        update(m.PlayerSeasonStats),
        [{"id": int(r["stat_id"]), "per90": metric_payload(r, cfg)} for _, r in rows.iterrows()],
    )

    upsert = pg_insert(m.LeagueStrength).values(
        [
            {
                "competition_id": int(r.competition_id),
                "coefficient": float(r.coefficient),
                "default_coefficient": float(r.default_coefficient),
                "n_movers": int(r.n_movers),
                "source": "admin" if int(r.competition_id) in admin else "estimated",
            }
            for r in strength.itertuples()
        ]
    )
    session.execute(
        upsert.on_conflict_do_update(
            index_elements=["competition_id"],
            set_={
                "default_coefficient": upsert.excluded.default_coefficient,
                "n_movers": upsert.excluded.n_movers,
                "coefficient": upsert.excluded.coefficient,
            },
            where=m.LeagueStrength.source != "admin",
        )
    )

    data_used = {
        (r.player_id, r.season_id): {
            "data_types": sorted(r.data_types),
            "metrics_in_level": int(r.level_n),
            "level_metrics": list(r.level_metrics),
            "level_has_performance_metrics": bool(r.level_perf_n),
            "source": r.source,
            "fetched_at": r.fetched_at.isoformat(),
            "competition_id": int(r.competition_id),
            "minutes": int(r.minutes),
        }
        for r in ps.itertuples()
    }
    session.execute(delete(m.PlayerScore).where(m.PlayerScore.model_version == ENGINE_VERSION))
    session.execute(
        delete(m.PlayerGoalScore).where(m.PlayerGoalScore.model_version == ENGINE_VERSION)
    )
    session.execute(
        pg_insert(m.PlayerScore),
        [
            _clean(
                {
                    "player_id": r.player_id,
                    "season_id": r.season_id,
                    "level": r.level,
                    "talent_index": r.talent_index,
                    "promotion_prob": None,
                    "reliability": _reliability(r, cfg),
                    "components": {
                        "level_pct": r.level_pct,
                        "level_within_league": r.z_within,
                        "league_coefficient": r.offset,
                        "expected_level_for_age": r.expected_level,
                        "age": r.age,
                        "relative_age": r.relative_age,
                        "minutes_share": r.minutes_share,
                        "share_vs_peers": r.share_vs_peers,
                        "precocity": r.precocity,
                        "valid_season": bool(r.valid),
                    },
                    "data_used": data_used[(r.player_id, r.season_id)],
                    "model_version": ENGINE_VERSION,
                }
            )
            for r in ps.itertuples()
        ],
    )
    goal = pd.concat([g for g in goal_rows if not g.empty], ignore_index=True)
    session.execute(
        pg_insert(m.PlayerGoalScore),
        [
            _clean(
                {
                    "player_id": r.player_id,
                    "season_id": r.season_id,
                    "goal_code": r.goal_code,
                    "status": r.status,
                    "score": r.score,
                    "ci_low": r.ci_low,
                    "ci_high": r.ci_high,
                    "reliability": r.reliability,
                    "components": r.components,
                    "data_used": data_used[(r.player_id, r.season_id)],
                    "model_version": ENGINE_VERSION,
                }
            )
            for r in goal.itertuples()
        ],
    )
    session.commit()
