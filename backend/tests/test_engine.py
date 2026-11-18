"""Unit test del motore delle metriche su dati costruiti a mano."""

import numpy as np
import pandas as pd
import pytest

from prospectlens.config import SportConfig
from prospectlens.engine.basics import add_metrics, ecdf_pct, shrink_per90, shrink_ratio
from prospectlens.engine.context import (
    AgeCurves,
    add_age_context,
    estimate_league_strength,
    fit_age_curves,
)
from prospectlens.engine.impact import decisive_points, shrink_onoff, team_impact
from prospectlens.engine.lenses import (
    growth_lens,
    longevity_features,
    longevity_labels,
    shrink_slope,
    weighted_slope,
)

# --------------------------------------------------------------------------- shrinkage


def test_shrinkage_per90_pulls_small_samples_to_the_mean() -> None:
    prior, k = 0.3, 10
    # 2 gol in 90 minuti: grezzo 2,0 per 90, stimato vicino alla media
    small = shrink_per90(np.array([2.0]), np.array([90.0]), prior, k)[0]
    assert small == pytest.approx((2 + 10 * 0.3) / (1 + 10))
    assert abs(small - prior) < abs(2.0 - prior) / 5
    # 20 gol in 2700 minuti (0,67 per 90): lo shrinkage sposta poco
    big = shrink_per90(np.array([20.0]), np.array([2700.0]), prior, k)[0]
    assert 0.55 < big < 0.67
    assert shrink_ratio(np.array([8.0]), np.array([10.0]), 0.5, 20)[0] == pytest.approx(18 / 30)


def test_ecdf_pct_midrank_and_nan() -> None:
    pct = ecdf_pct([1, 2, 3, np.nan], [1, 2, 2, 3])
    assert pct[0] == pytest.approx(12.5)  # metà del primo quarto
    assert pct[1] == pytest.approx(50.0)  # pareggi: rango medio
    assert pct[2] == pytest.approx(87.5)
    assert np.isnan(pct[3])


# --------------------------------------------------------------------------- percentili


def _rows(cfg: SportConfig) -> pd.DataFrame:
    """Due competizioni con scale di gol molto diverse: i percentili restano interni."""
    rows = []
    for comp, scale in ((1, 1.0), (2, 10.0)):
        for i in range(10):
            rows.append(
                {
                    "competition_id": comp,
                    "season_id": 1,
                    "macro": "FW",
                    "minutes": 1800,
                    "data_types": {"player_stats_basic"},
                    "raw": {
                        "goals": scale * i,
                        "assists": scale * (9 - i) / 3,
                        "yellow_cards": float(i % 3),
                    },
                }
            )
    return pd.DataFrame(rows)


def test_percentiles_are_within_competition_and_role(cfg: SportConfig) -> None:
    df = add_metrics(_rows(cfg), cfg)
    top = df.groupby("competition_id")["goals__pct"].max()
    assert top[1] == pytest.approx(top[2])  # il migliore di ogni lega ha lo stesso percentile
    assert df["shots_on_target__est"].isna().all()  # dato avanzato assente: niente valore
    assert (df["level_n"] == 3).all()
    assert (df["level_perf_n"] == 2).all()  # gol e assist; le ammonizioni non sono prestazione
    assert df.loc[0, "level_metrics"] == ["goals", "assists", "yellow_cards"]
    assert df.groupby("competition_id")["z_within"].mean().abs().max() < 1e-9


def test_goalkeeper_metrics_from_row_columns(cfg: SportConfig) -> None:
    df = pd.DataFrame(
        [
            {
                "competition_id": 1,
                "season_id": 1,
                "macro": "GK",
                "minutes": mins,
                "team_minutes": 3420,
                "data_types": {"results", "lineups", "player_stats_basic"},
                "raw": {"yellow_cards": 1.0, "goals_conceded_on_pitch": conc},
            }
            for mins, conc in ((3420, 30.0), (3000, 45.0), (1700, 30.0), (500, 5.0))
        ]
    )
    out = add_metrics(df, cfg)
    assert out.loc[0, "minutes_share__est"] == pytest.approx(1.0)  # K = 0: nessuno shrinkage
    assert out.loc[0, "goals_conceded_on_pitch__pct"] > out.loc[1, "goals_conceded_on_pitch__pct"]
    assert (out["level_perf_n"] == 1).all()


# --------------------------------------------------------------------------- età e under


def test_minutes_share_compared_with_peers_not_whole_squad() -> None:
    df = pd.DataFrame(
        {
            "competition_id": 1,
            "season_id": 1,
            "macro": "DF",
            "age": [19.0, 19.2, 28.0, 29.0],
            "birth_year": [2005, 2005, 1996, 1995],
            "minutes": [900, 450, 3000, 2800],
            "team_minutes": 3420,
        }
    )
    out = add_age_context(df)
    # il primo under gioca il doppio del coetaneo: 900 / mediana(900, 450) = 1,33
    assert out.loc[0, "share_vs_peers"] == pytest.approx(900 / 675)
    assert out.loc[0, "precocity"] > out.loc[1, "precocity"]
    assert np.isnan(out.loc[2, "precocity"])  # precocità solo 18-21 anni
    assert out["relative_age"].sum() == pytest.approx(0)


def test_league_strength_recovers_known_offsets(cfg: SportConfig) -> None:
    truth = {1: 0.0, 2: -0.8}  # la lega 2 è più debole di 0,8
    rng = np.random.default_rng(1)
    rows = []
    for pid in range(400):
        level = rng.normal(-0.4, 0.5)
        c0, c1 = (2, 1) if pid % 2 else (1, 2)
        for year, comp in ((2022, c0), (2023, c1)):
            rows.append(
                {
                    "player_id": pid,
                    "season_year": year,
                    "competition_id": comp,
                    "z_within": level - truth[comp] + rng.normal(0, 0.1),
                    "minutes": 1800,
                    "age": 30.0,
                    "macro": "MF",
                }
            )
    est = estimate_league_strength(pd.DataFrame(rows), {1: 2, 2: 2}, cfg, lambda m, a: 0.0)
    coef = dict(zip(est["competition_id"], est["coefficient"], strict=True))
    assert coef[1] - coef[2] == pytest.approx(0.8, abs=0.05)
    assert est["n_movers"].tolist() == [400, 400]


def test_age_curve_falls_back_to_config_with_few_rows(cfg: SportConfig) -> None:
    ps = pd.DataFrame(
        {"macro": "FW", "age": [20.0, 26.0], "level": [-0.5, 0.7], "minutes": [1000, 1000]}
    )
    curves = fit_age_curves(ps, cfg)
    assert curves.describe()["FW"] == "default"
    assert curves.growth("FW", 20.0) == pytest.approx(cfg.age_curves["FW"].growth_per_year)


# --------------------------------------------------------------------------- lente A


def test_weighted_slope_and_shrinkage() -> None:
    x = np.array([2021.0, 2022.0, 2023.0])
    slope, se = weighted_slope(x, np.array([0.0, 0.5, 1.0]), np.ones(3), noise_floor_sd=0.25)
    assert slope == pytest.approx(0.5)
    assert se > 0  # mai certezza assoluta, anche con punti allineati
    post, se_post = shrink_slope(slope, se=1.0, expected=0.1, prior_sd=0.2)
    assert 0.1 < post < 0.15  # pendenza molto incerta: resta vicina all'attesa
    assert se_post < 0.2


def _ps(player: int, levels: list[float], comps: list[float] | None = None) -> list[dict]:
    return [
        {
            "player_id": player,
            "season_id": i,
            "season_year": 2021 + i,
            "macro": "FW",
            "age": 19.0 + i,
            "minutes": 2000,
            "valid": True,
            "level": lv,
            "offset": (comps or [0.0] * len(levels))[i],
            "data_types": {"player_stats_basic"},
        }
        for i, lv in enumerate(levels)
    ]


def test_growth_lens_residual_against_age_curve(cfg: SportConfig) -> None:
    ps = pd.DataFrame(
        _ps(1, [-1.0, -0.4, 0.2])
        + _ps(2, [-1.0, -0.8, -0.6])
        + _ps(3, [-1.0], None)
        + _ps(4, [-1.0, -0.8, -0.6], [-1.2, -0.6, 0.0])
    )
    out = growth_lens(ps, AgeCurves(cfg.age_curves), cfg).set_index(["player_id", "season_id"])
    fast, normal = out.loc[(1, 2)], out.loc[(2, 2)]
    assert fast["raw"] > normal["raw"]
    # crescita uguale all'attesa (0,2 per un attaccante giovane): residuo vicino a 0
    assert abs(normal["components"]["growth_vs_expected"]) < 0.05
    assert out.loc[(3, 0), "status"] == "insufficient_history"
    assert out.loc[(1, 1), "reliability"] == "low"  # solo 2 stagioni
    # stessa crescita di 2, ma salendo di categoria: bonus "salto di contesto"
    assert out.loc[(4, 2), "components"]["context_jump"] > 0
    assert out.loc[(4, 2), "raw"] > normal["raw"]


# --------------------------------------------------------------------------- lente C


def _lc(cfg: SportConfig) -> pd.DataFrame:
    rows = []
    for year, pct, valid in (
        (2020, 80, True),
        (2021, 75, True),
        (2022, 30, True),
        (2023, 60, True),
        (2025, 90, True),
    ):
        rows.append(
            {
                "player_id": 1,
                "season_id": year,
                "season_year": year,
                "macro": "DF",
                "age": 22 + year - 2020,
                "valid": valid,
                "level": pct / 100,
                "level_pct": pct,
                "appearances": 30,
                "team_matches": 38,
            }
        )
    rows.append(
        {
            "player_id": 2,
            "season_id": 2020,
            "season_year": 2020,
            "macro": "DF",
            "age": 25,
            "valid": True,
            "level": 0.5,
            "level_pct": 70,
            "appearances": 10,
            "team_matches": 38,
        }
    )
    rows.append(
        {
            "player_id": 2,
            "season_id": 2021,
            "season_year": 2021,
            "macro": "DF",
            "age": 26,
            "valid": False,
            "level": 0.5,
            "level_pct": 70,
            "appearances": 2,
            "team_matches": 38,
        }
    )
    return pd.DataFrame(rows)


def test_seasons_above_threshold_counts_consecutive_runs(cfg: SportConfig) -> None:
    f = longevity_features(_lc(cfg), cfg).set_index(["player_id", "season_year"])
    assert f.loc[(1, 2021), "seasons_above"] == 2
    assert f.loc[(1, 2021), "seasons_above_high"] == 2  # 80 e 75 sopra 70
    assert f.loc[(1, 2022), "seasons_above"] == 0  # sotto soglia: la serie si azzera
    assert f.loc[(1, 2023), "seasons_above"] == 1
    assert f.loc[(1, 2025), "seasons_above"] == 1  # stagione mancante (2024): niente serie
    assert f.loc[(1, 2023), "seasons_observed"] == 4


def test_censoring_absent_next_season_is_not_a_failure(cfg: SportConfig) -> None:
    f = longevity_features(_lc(cfg), cfg)
    y = longevity_labels(f)
    lab = dict(zip(zip(f["player_id"], f["season_year"], strict=True), y, strict=True))
    assert lab[(1, 2020)] == 1 and lab[(1, 2021)] == 0
    assert np.isnan(lab[(1, 2023)])  # assente nel 2024: censurato, escluso
    assert np.isnan(lab[(1, 2025)])  # ultima stagione: esito ignoto
    assert lab[(2, 2020)] == 0  # presente ma senza minuti sufficienti: non è "sopra soglia"


# --------------------------------------------------------------------------- lente B


def test_decisive_points() -> None:
    assert decisive_points(1, 0) == 2  # vittoria 1-0: senza quel gol, pareggio
    assert decisive_points(2, 2) == 1  # pareggio: senza, sconfitta
    assert decisive_points(3, 0) == 0
    assert shrink_onoff(1.0, 0, 10, 10) == 0.0
    assert 0 < shrink_onoff(1.0, 20, 10, 10) < 1.0


def test_onoff_and_ridge_find_the_impact_player(cfg: SportConfig) -> None:
    """La squadra segna di più quando c'è il giocatore 99, che a volte esce o non gioca."""
    rng = np.random.default_rng(0)
    squad = list(range(1, 16))
    seg, minutes, matches = [], [], []
    for mid in range(40):
        on = list(rng.choice(squad, 10, replace=False))
        star = mid % 4 != 0  # assente in una partita su quattro
        for lo, hi in ((0, 60), (60, 90)):
            present = star and lo == 0
            players = (*on, 99) if present else (*on, int(rng.choice(squad)))
            gd = rng.poisson(1.8 if present else 0.9) - rng.poisson(1.0)
            seg.append(
                {
                    "match_id": mid,
                    "len": hi - lo,
                    "gf": max(gd, 0),
                    "ga": max(-gd, 0),
                    "players": players,
                    "opp_strength": 0.0,
                    "home": mid % 2,
                }
            )
            minutes += [{"match_id": mid, "player_id": p, "minutes": hi - lo} for p in players]
        matches.append({"match_id": mid, "points": 1})
    out = pd.DataFrame(
        team_impact(pd.DataFrame(seg), pd.DataFrame(matches), pd.DataFrame(minutes), cfg, rng)
    ).set_index("player_id")
    star = out.loc[99]
    assert star["onoff_goal_diff_p90_raw"] > 0.5
    assert 0 < star["onoff_goal_diff_p90"] < star["onoff_goal_diff_p90_raw"]  # shrinkage
    assert star["rank_in_team"] == 1
    assert star["ci_low"] < star["adjusted_impact"] < star["ci_high"]
