"""Lente A (crescita rapida) e lente C (longevità).

Entrambe lavorano su `ps`: una riga per giocatore e stagione con player_id, season_id,
season_year, macro, age, minutes, appearances, team_matches, level, level_pct, offset,
valid (stagione valida), data_types (della competizione principale).
Restituiscono una riga per giocatore-stagione con: status, raw, ci_low_raw, ci_high_raw,
reliability, components, seasons_observed.
"""

from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from prospectlens.config import SportConfig
from prospectlens.engine.context import AgeCurves

Z90 = 1.645  # intervallo al 90%


def _row(
    r: pd.Series,
    status: str,
    reliability: str = "low",
    raw: float = np.nan,
    lo: float = np.nan,
    hi: float = np.nan,
    **components: Any,
) -> dict[str, Any]:
    return {
        "player_id": r["player_id"],
        "season_id": r["season_id"],
        "macro": r["macro"],
        "status": status,
        "raw": raw,
        "ci_low_raw": lo,
        "ci_high_raw": hi,
        "reliability": reliability,
        "components": components,
    }


# --------------------------------------------------------------------------- lente A


def weighted_slope(
    x: np.ndarray, y: np.ndarray, w: np.ndarray, noise_floor_sd: float
) -> tuple[float, float]:
    """Pendenza ai minimi quadrati pesati e suo errore standard. La varianza residua ha
    un minimo (`noise_floor_sd`): con 2 stagioni la retta passa per i punti ma la
    pendenza non è per questo certa."""
    xm = np.average(x, weights=w)
    ym = np.average(y, weights=w)
    sxx = float(np.sum(w * (x - xm) ** 2))
    slope = float(np.sum(w * (x - xm) * (y - ym)) / sxx)
    resid = y - (ym + slope * (x - xm))
    var = float(np.sum(w * resid**2) / max(len(x) - 2, 1)) if len(x) > 2 else 0.0
    var = max(var, noise_floor_sd**2)
    return slope, float(np.sqrt(var / sxx))


def shrink_slope(slope: float, se: float, expected: float, prior_sd: float) -> tuple[float, float]:
    """Media a posteriori normale-normale: la pendenza osservata viene tirata verso la
    crescita attesa per età e ruolo, tanto più quanto è incerta."""
    precision = 1 / se**2 + 1 / prior_sd**2
    post = (slope / se**2 + expected / prior_sd**2) / precision
    return post, float(np.sqrt(1 / precision))


def growth_lens(ps: pd.DataFrame, curves: AgeCurves, cfg: SportConfig) -> pd.DataFrame:
    p = cfg.engine.growth
    min_n = cfg.goal("growth").min_valid_seasons or 2
    valid = ps[ps["valid"] & ps["level"].notna()].sort_values("season_year")
    by_player = dict(tuple(valid.groupby("player_id")))
    out = []
    for _, r in ps.iterrows():
        h = by_player.get(r["player_id"])
        if h is not None:
            h = h[
                (h["season_year"] <= r["season_year"])
                & (h["season_year"] > r["season_year"] - p.window_seasons)
            ]
        n = 0 if h is None else len(h)
        if n < min_n or not (r["valid"] and np.isfinite(r["level"]) and np.isfinite(r["age"])):
            out.append(_row(r, "insufficient_history", seasons_used=n))
            continue
        assert h is not None
        x = h["season_year"].to_numpy(float)
        y = h["level"].to_numpy(float)
        w = h["minutes"].to_numpy(float) / cfg.thresholds.valid_season_minutes
        slope, se = weighted_slope(x, y, w, p.noise_floor_sd)
        expected = float(curves.growth(r["macro"], float(h["age"].mean())))
        post, se_post = shrink_slope(slope, se, expected, p.prior_sd)
        offsets = h["offset"].to_numpy(float)
        jump = sum(
            o1 - o0
            for o0, o1, l0, l1 in zip(offsets, offsets[1:], y, y[1:], strict=False)
            if o1 - o0 > 0.05 and l1 >= l0 - p.jump_tolerance
        )
        raw = post - expected + p.jump_weight * jump
        advanced = "player_stats_advanced" in r["data_types"]
        reliability = "low" if n == 2 else ("high" if advanced else "medium")
        out.append(
            _row(
                r,
                "ok",
                reliability,
                raw,
                raw - Z90 * se_post,
                raw + Z90 * se_post,
                slope=round(slope, 4),
                slope_shrunk=round(post, 4),
                expected_growth=round(expected, 4),
                growth_vs_expected=round(post - expected, 4),
                context_jump=round(float(jump), 4),
                seasons_used=n,
                levels=[round(v, 3) for v in y],
            )
        )
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- lente C


FEATURES = ["age", "age2", "pct", "above", "seasons_above", "consistency", "availability"]


def longevity_features(ps: pd.DataFrame, cfg: SportConfig) -> pd.DataFrame:
    """Storico osservato fino alla stagione T, per ogni giocatore-stagione."""
    medium = (cfg.goal("longevity").thresholds_percentile or {}).get("medium", 50)
    high = (cfg.goal("longevity").thresholds_percentile or {}).get("high", 70)
    df = ps.sort_values(["player_id", "season_year"]).copy()
    df["above"] = (df["valid"] & (df["level_pct"] >= medium)).astype(int)
    df["above_high"] = (df["valid"] & (df["level_pct"] >= high)).astype(int)
    df["avail_season"] = (
        df["appearances"] / df["team_matches"].where(df["team_matches"] > 0)
    ).clip(upper=1)
    rows = []
    for _, g in df.groupby("player_id", sort=False):
        run = run_high = observed = 0
        prev_year = None
        levels: list[float] = []
        avail: list[float] = []
        for _, r in g.iterrows():
            gap = prev_year is not None and r["season_year"] != prev_year + 1
            run = (0 if gap else run) + 1 if r["above"] else 0
            run_high = (0 if gap else run_high) + 1 if r["above_high"] else 0
            if r["valid"] and np.isfinite(r["level"]):
                observed += 1
                levels.append(r["level"])
            if np.isfinite(r["avail_season"]):
                avail.append(r["avail_season"])
            rows.append(
                {
                    "seasons_above": run,
                    "seasons_above_high": run_high,
                    "seasons_observed": observed,
                    "consistency": float(np.std(levels)) if len(levels) >= 2 else np.nan,
                    "availability": float(np.mean(avail)) if avail else np.nan,
                }
            )
            prev_year = r["season_year"]
    feats = pd.DataFrame(rows, index=df.index)
    return pd.concat([df, feats], axis=1)


def longevity_labels(f: pd.DataFrame) -> pd.Series:
    """Esito alla stagione T+1: 1 sopra soglia (e stagione valida), 0 altrimenti.
    Censura: se il giocatore non compare in T+1 ma i dati di T+1 esistono, non sappiamo
    se ha smesso, è sceso di categoria fuori copertura o è andato all'estero: la riga
    è esclusa (NaN), non contata come successo né come fallimento. Lo stesso per l'ultima
    stagione disponibile."""
    nxt = f.groupby("player_id")[["season_year", "above"]].shift(-1)
    observed_next = nxt["season_year"] == f["season_year"] + 1
    return nxt["above"].where(observed_next)


def _matrix(f: pd.DataFrame, macros: list[str], fill: pd.Series) -> np.ndarray:
    x = pd.DataFrame(
        {
            "age": f["age"],
            "age2": f["age"] ** 2,
            "pct": f["level_pct"] / 100,
            "above": f["above"],
            "seasons_above": f["seasons_above"],
            "consistency": f["consistency"].fillna(fill["consistency"]),
            "availability": f["availability"].fillna(fill["availability"]),
        }
    )
    for m in macros:
        x[f"macro_{m}"] = (f["macro"] == m).astype(float)
    return np.asarray(x.fillna(0).to_numpy(float))


def _project(
    model: Any, f: pd.DataFrame, macros: list[str], fill: pd.Series, horizon: int, medium: float
) -> np.ndarray:
    """P(sopra soglia in ognuna delle prossime `horizon` stagioni) = prodotto delle
    probabilità stagione per stagione, aggiornando età e serie positiva."""
    prob = np.ones(len(f))
    step = f.copy()
    for _ in range(horizon):
        prob *= model.predict_proba(_matrix(step, macros, fill))[:, 1]
        step = step.assign(
            age=step["age"] + 1,
            above=1,
            seasons_above=step["seasons_above"] + 1,
            level_pct=np.maximum(step["level_pct"], medium),
        )
    return prob


def longevity_lens(ps: pd.DataFrame, cfg: SportConfig) -> pd.DataFrame:
    goal = cfg.goal("longevity")
    lp = cfg.engine.longevity
    medium = (goal.thresholds_percentile or {}).get("medium", 50)
    horizon = goal.horizon_seasons or 3
    f = longevity_features(ps, cfg)
    y = longevity_labels(f)
    macros = sorted(cfg.age_curves)
    fill = f[["consistency", "availability"]].median()
    has_age = f["age"].notna()  # senza data di nascita niente proiezione per età
    train = f[y.notna() & f["valid"] & f["level_pct"].notna() & has_age]
    target = y[train.index].astype(int)
    out_status = pd.Series("insufficient_history", index=f.index)
    scorable = f["valid"] & f["level_pct"].notna() & has_age
    probs = pd.Series(np.nan, index=f.index)
    lo, hi = probs.copy(), probs.copy()
    if len(train) >= 30 and target.nunique() == 2:

        def fit(idx: pd.Index) -> Any:
            m = make_pipeline(
                StandardScaler(), LogisticRegression(C=lp.regularization_c, max_iter=1000)
            )
            return m.fit(_matrix(train.loc[idx], macros, fill), target.loc[idx])

        model = fit(train.index)
        sc = f[scorable]
        probs[sc.index] = _project(model, sc, macros, fill, horizon, medium)
        rng = np.random.default_rng(cfg.engine.seed)
        players = train["player_id"].unique()
        draws = []
        for _ in range(lp.bootstrap):
            pick = rng.choice(players, size=len(players), replace=True)
            idx = train.reset_index().set_index("player_id").loc[pick, "index"]
            if target.loc[idx].nunique() == 2:
                draws.append(_project(fit(pd.Index(idx)), sc, macros, fill, horizon, medium))
        if draws:
            lo[sc.index] = np.percentile(draws, 5, axis=0)
            hi[sc.index] = np.percentile(draws, 95, axis=0)
        out_status[sc.index] = "ok"
    out = []
    for i, r in f.iterrows():
        n = int(r["seasons_observed"])
        rel = (
            "high"
            if n >= 4 and (r["availability"] or 0) >= 0.7
            else ("medium" if n >= 3 else "low")
        )
        components: dict[str, Any] = dict(
            seasons_above_threshold=int(r["seasons_above"]),
            seasons_above_high=int(r["seasons_above_high"]),
            seasons_observed=n,
            consistency=None if np.isnan(r["consistency"]) else round(float(r["consistency"]), 3),
            availability=None
            if np.isnan(r["availability"])
            else round(float(r["availability"]), 3),
            horizon_seasons=horizon,
        )
        if out_status[i] == "ok":
            out.append(_row(r, "ok", rel, 100 * probs[i], 100 * lo[i], 100 * hi[i], **components))
        else:
            out.append(_row(r, "insufficient_history", **components))
    return pd.DataFrame(out)
