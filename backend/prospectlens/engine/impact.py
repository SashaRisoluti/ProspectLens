"""Lente B: impatto sui risultati.

Richiede formazioni, cambi ed eventi. Ogni partita è divisa in segmenti tra un cambio
e l'altro; in ogni segmento sono noti i giocatori in campo e i gol.

- On/off: differenza reti per 90 e punti a partita con il giocatore in campo e fuori,
  con shrinkage forte verso 0.
- Ridge (plus-minus rettificato): per squadra e stagione, differenza reti per 90 del
  segmento ~ compagni in campo + forza dell'avversario + casa/trasferta. Il coefficiente
  del giocatore è il suo effetto al netto dei compagni. Intervallo con bootstrap sulle
  partite.
- Decisività: punti che la squadra avrebbe perso togliendo il gol (o l'assist, con peso).
"""

import itertools
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from prospectlens.config import SportConfig

REQUIRED = {"lineups", "substitutions", "events"}


def points(gf: int, ga: int) -> int:
    return 3 if gf > ga else (1 if gf == ga else 0)


def decisive_points(gf: int, ga: int) -> int:
    """Punti persi dalla squadra se il gol non ci fosse stato."""
    return points(gf, ga) - points(gf - 1, ga)


def shrink_onoff(diff: float, n_on: float, n_off: float, k: float) -> float:
    """Shrinkage verso 0: peso = media armonica dei campioni (in 90 minuti) / (+K)."""
    if n_on <= 0 or n_off <= 0:
        return 0.0
    h = n_on * n_off / (n_on + n_off)
    return diff * h / (h + k)


def build_segments(matches: pd.DataFrame, apps: pd.DataFrame, goals: pd.DataFrame) -> pd.DataFrame:
    """Una riga per (partita, squadra, segmento): len, gf, ga, home, players (tupla)."""
    apps_by = dict(tuple(apps.groupby("match_id")))
    goals_by = dict(tuple(goals.groupby("match_id")))
    rows = []
    for m in matches.itertuples():
        a = apps_by.get(m.id)
        if a is None:
            continue
        g = goals_by.get(m.id)
        bounds = sorted({0, 90, *a["minute_in"], *a["minute_out"]})
        for lo, hi in itertools.pairwise(bounds):
            on = a[(a["minute_in"] <= lo) & (a["minute_out"] >= hi)]
            scored: dict[int, int] = defaultdict(int)
            if g is not None:
                for team in g[(g["minute"] > lo) & (g["minute"] <= hi)]["team_id"]:
                    scored[int(team)] += 1
            for team, opp, home in (
                (m.home_team_id, m.away_team_id, 1),
                (m.away_team_id, m.home_team_id, 0),
            ):
                rows.append(
                    {
                        "match_id": m.id,
                        "competition_id": m.competition_id,
                        "season_id": m.season_id,
                        "team_id": team,
                        "opp_id": opp,
                        "home": home,
                        "len": hi - lo,
                        "gf": scored[team],
                        "ga": scored[opp],
                        "players": tuple(on[on["team_id"] == team]["player_id"]),
                    }
                )
    return pd.DataFrame(rows)


def _ridge(
    x: np.ndarray, controls: np.ndarray, y: np.ndarray, w: np.ndarray, alpha: float
) -> np.ndarray:
    model = Ridge(alpha=alpha).fit(np.hstack([x, controls]), y, sample_weight=w)
    return np.asarray(model.coef_[: x.shape[1]])


def team_impact(
    seg: pd.DataFrame,
    team_matches: pd.DataFrame,
    minutes: pd.DataFrame,
    cfg: SportConfig,
    rng: np.random.Generator,
) -> list[dict[str, Any]]:
    """Impatto dei giocatori di una squadra in una stagione."""
    p = cfg.engine.impact
    roster = sorted({pl for t in seg["players"] for pl in t})
    col = {pl: i for i, pl in enumerate(roster)}
    x = np.zeros((len(seg), len(roster)))
    for r, players in enumerate(seg["players"]):
        x[r, [col[pl] for pl in players]] = 1
    length = seg["len"].to_numpy(float)
    gd = (seg["gf"] - seg["ga"]).to_numpy(float)
    controls = seg[["opp_strength", "home"]].to_numpy(float)
    y, w = gd / length * 90, length / 90
    coef = _ridge(x, controls, y, w, p.ridge_alpha)
    match_ids = seg["match_id"].to_numpy()
    unique = np.unique(match_ids)
    rows_of = {mid: np.flatnonzero(match_ids == mid) for mid in unique}
    boot = []
    for _ in range(p.bootstrap):
        idx = np.concatenate([rows_of[mid] for mid in rng.choice(unique, len(unique))])
        boot.append(_ridge(x[idx], controls[idx], y[idx], w[idx], p.ridge_alpha))
    lo, hi = np.percentile(boot, [5, 95], axis=0) if boot else (np.full(len(roster), np.nan),) * 2
    on_len, on_gd = x.T @ length, x.T @ gd
    tot_len, tot_gd = length.sum(), gd.sum()
    # punti a partita in campo / fuori, pesati per la quota di minuti in ogni partita
    pts = team_matches.set_index("match_id")["points"]
    share = (
        minutes.pivot_table(index="match_id", columns="player_id", values="minutes", aggfunc="sum")
        .reindex(pts.index)
        .fillna(0)
        / 90
    )
    rank = pd.Series(coef, index=roster).rank(ascending=False)
    out = []
    for pl, i in col.items():
        off_len = tot_len - on_len[i]
        gd_on = on_gd[i] / on_len[i] * 90 if on_len[i] else 0.0
        gd_off = (tot_gd - on_gd[i]) / off_len * 90 if off_len else 0.0
        s = share[pl] if pl in share else pd.Series(0.0, index=pts.index)
        ppm_on = float((pts * s).sum() / s.sum()) if s.sum() else 0.0
        ppm_off = float((pts * (1 - s)).sum() / (1 - s).sum()) if (1 - s).sum() else 0.0
        n_on, n_off = on_len[i] / 90, off_len / 90
        out.append(
            {
                "player_id": pl,
                "on_minutes": int(on_len[i]),
                "off_minutes": int(off_len),
                "onoff_goal_diff_p90_raw": round(gd_on - gd_off, 3),
                "onoff_goal_diff_p90": round(
                    shrink_onoff(gd_on - gd_off, n_on, n_off, p.onoff_shrinkage_k), 3
                ),
                "onoff_ppm_raw": round(ppm_on - ppm_off, 3),
                "onoff_ppm": round(
                    shrink_onoff(ppm_on - ppm_off, s.sum(), (1 - s).sum(), p.onoff_shrinkage_k), 3
                ),
                "adjusted_impact": float(coef[i]),
                "ci_low": float(lo[i]),
                "ci_high": float(hi[i]),
                "rank_in_team": int(rank[pl]),
                "team_players": len(roster),
            }
        )
    return out


def impact_by_team(
    matches: pd.DataFrame,
    apps: pd.DataFrame,
    goals: pd.DataFrame,
    comp_ok: set[tuple[int, int]],
    cfg: SportConfig,
) -> pd.DataFrame:
    """Una riga per (giocatore, squadra, competizione, stagione) con dati sufficienti.
    goals: eventi goal/own_goal con team_id = squadra accreditata."""
    keep = [
        (c, s) in comp_ok
        for c, s in zip(matches["competition_id"], matches["season_id"], strict=True)
    ]
    m = matches[np.asarray(keep, dtype=bool) & matches["home_goals"].notna()]
    if m.empty:
        return pd.DataFrame()
    a = apps[apps["match_id"].isin(m["id"])]
    g = goals[goals["match_id"].isin(m["id"])]
    seg = build_segments(m, a, g)
    # forza dell'avversario: differenza reti media a partita nella stagione
    long = pd.concat(
        [
            m.assign(
                team_id=m["home_team_id"],
                gd=m["home_goals"] - m["away_goals"],
                pts=[points(h, w) for h, w in zip(m["home_goals"], m["away_goals"], strict=True)],
            ),
            m.assign(
                team_id=m["away_team_id"],
                gd=m["away_goals"] - m["home_goals"],
                pts=[points(w, h) for h, w in zip(m["home_goals"], m["away_goals"], strict=True)],
            ),
        ]
    )
    strength = long.groupby(["team_id", "season_id"])["gd"].mean()
    seg["opp_strength"] = [
        strength[(o, s)] for o, s in zip(seg["opp_id"], seg["season_id"], strict=True)
    ]
    rng = np.random.default_rng(cfg.engine.seed)
    minutes = a.assign(minutes=a["minute_out"] - a["minute_in"])
    out = []
    for (team, comp, season), s in seg.groupby(["team_id", "competition_id", "season_id"]):
        tm = long[(long["team_id"] == team) & (long["season_id"] == season)]
        tm = tm.rename(columns={"id": "match_id", "pts": "points"})[["match_id", "points"]]
        mins = minutes[(minutes["team_id"] == team) & minutes["match_id"].isin(tm["match_id"])]
        for r in team_impact(s, tm, mins, cfg, rng):
            out.append({"team_id": team, "competition_id": comp, "season_id": season, **r})
    df = pd.DataFrame(out)
    # decisività: gol e assist che hanno cambiato l'esito
    res = {
        r.id: (r.home_team_id, int(r.home_goals), r.away_team_id, int(r.away_goals))
        for r in m.itertuples()
    }
    dec: dict[tuple[int, int], float] = defaultdict(float)
    for e in g[g["type"] == "goal"].itertuples():
        ht, hg, _at, ag = res[e.match_id]
        gf, ga = (hg, ag) if e.team_id == ht else (ag, hg)
        pts = decisive_points(gf, ga)
        dec[(e.player_id, e.team_id)] += pts
        if pd.notna(e.related_player_id):
            dec[(int(e.related_player_id), e.team_id)] += cfg.engine.impact.assist_weight * pts
    df["decisive_points"] = [
        dec.get((p, t), 0.0) for p, t in zip(df["player_id"], df["team_id"], strict=True)
    ]
    return df
