"""Forza delle competizioni, curve d'età, età relativa, precocità e quota minuti
rispetto ai coetanei (regole under)."""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from prospectlens.config import AgeCurve, SportConfig

# --------------------------------------------------------------------------- curve d'età


def default_shape(curve: AgeCurve, age: np.ndarray) -> np.ndarray:
    """Forma della curva di default (0 al picco)."""
    return -curve.growth_per_year * np.maximum(
        curve.peak_age - age, 0
    ) - curve.decline_per_year * np.maximum(age - curve.peak_age, 0)


def default_growth(curve: AgeCurve, age: np.ndarray) -> np.ndarray:
    return np.where(age < curve.peak_age, curve.growth_per_year, -curve.decline_per_year)


@dataclass
class AgeCurves:
    """Livello atteso e crescita attesa per età e macro-ruolo.
    Quadratica stimata sui dati (pesata per minuti) se ci sono abbastanza stagioni valide,
    altrimenti la curva di default del YAML, centrata sulla media del ruolo."""

    defaults: dict[str, AgeCurve]
    poly: dict[str, np.ndarray] = field(default_factory=dict)
    base: dict[str, float] = field(default_factory=dict)

    def expected(self, macro: str, age: np.ndarray | float) -> np.ndarray:
        a = np.asarray(age, dtype=float)
        if macro in self.poly:
            return np.asarray(np.polyval(self.poly[macro], a))
        return self.base.get(macro, 0.0) + default_shape(self.defaults[macro], a)

    def growth(self, macro: str, age: np.ndarray | float) -> np.ndarray:
        a = np.asarray(age, dtype=float)
        if macro in self.poly:
            return np.asarray(np.polyval(np.polyder(self.poly[macro]), a))
        return default_growth(self.defaults[macro], a)

    def describe(self) -> dict[str, str]:
        return {m: ("stimata" if m in self.poly else "default") for m in self.defaults}


def fit_age_curves(ps: pd.DataFrame, cfg: SportConfig) -> AgeCurves:
    """ps: una riga per giocatore-stagione valida con age, level, minutes, macro."""
    curves = AgeCurves(cfg.age_curves)
    for macro, curve in cfg.age_curves.items():
        d = ps[(ps["macro"] == macro) & ps["level"].notna()]
        if d.empty:
            continue
        if len(d) >= cfg.engine.age_curve_min_rows:
            curves.poly[macro] = np.polyfit(d["age"], d["level"], 2, w=np.sqrt(d["minutes"]))
        else:
            shape = default_shape(curve, d["age"].to_numpy())
            curves.base[macro] = float(np.average(d["level"] - shape, weights=d["minutes"]))
    return curves


# --------------------------------------------------------------------------- forza leghe


def estimate_league_strength(
    moves_source: pd.DataFrame,
    comp_level: dict[int, int],
    cfg: SportConfig,
    growth: Callable[[str, float], float],
) -> pd.DataFrame:
    """Coefficiente (in unità di Livello) per competizione/girone dai giocatori che
    cambiano competizione tra due stagioni consecutive.

    Per ogni passaggio da c0 (stagione t) a c1 (t+1):
        off[c1] - off[c0] = z0 - z1 + crescita_attesa(età, ruolo)
    Minimi quadrati pesati, con un prior verso i default di livello (peso
    `league_strength_prior_weight`), che ancora la scala e copre i gironi senza passaggi.

    moves_source: una riga per giocatore-stagione (competizione principale) con
    player_id, season_year, competition_id, z_within, minutes, age, macro.
    """
    defaults = {c: cfg.league_strength_defaults.get(lvl, 0.0) for c, lvl in comp_level.items()}
    comps = sorted(defaults)
    pos = {c: i for i, c in enumerate(comps)}
    d = moves_source.dropna(subset=["z_within"]).sort_values(["player_id", "season_year"])
    nxt = d.groupby("player_id").shift(-1)
    moved = (nxt["season_year"] == d["season_year"] + 1) & (
        nxt["competition_id"] != d["competition_id"]
    )
    m0, m1 = d[moved], nxt[moved]
    rows, target, weight = [], [], []
    n_movers = dict.fromkeys(comps, 0)
    for (_, a), (_, b) in zip(m0.iterrows(), m1.iterrows(), strict=True):
        x = np.zeros(len(comps))
        x[pos[int(b["competition_id"])]] += 1
        x[pos[int(a["competition_id"])]] -= 1
        rows.append(x)
        target.append(a["z_within"] - b["z_within"] + growth(a["macro"], a["age"]))
        weight.append(min(a["minutes"], b["minutes"]) / 900)
        n_movers[int(a["competition_id"])] += 1
        n_movers[int(b["competition_id"])] += 1
    lam = cfg.engine.league_strength_prior_weight
    prior_rows = np.eye(len(comps)) * np.sqrt(lam)
    prior_target = np.array([defaults[c] for c in comps]) * np.sqrt(lam)
    if rows:
        w = np.sqrt(np.asarray(weight))
        a_mat = np.vstack([np.asarray(rows) * w[:, None], prior_rows])
        b_vec = np.concatenate([np.asarray(target) * w, prior_target])
    else:
        a_mat, b_vec = prior_rows, prior_target
    coef = np.linalg.lstsq(a_mat, b_vec, rcond=None)[0]
    return pd.DataFrame(
        {
            "competition_id": comps,
            "coefficient": coef,
            "default_coefficient": [defaults[c] for c in comps],
            "n_movers": [n_movers[c] for c in comps],
        }
    )


# --------------------------------------------------------------------------- età e minuti


def add_age_context(rows: pd.DataFrame) -> pd.DataFrame:
    """Aggiunge, per riga (giocatore, squadra, competizione, stagione):
    - relative_age: età meno età media del macro-ruolo nella competizione e stagione;
    - minutes_share: minuti / minuti disponibili della squadra;
    - share_vs_peers: quota minuti / mediana dei nati nello stesso anno nella stessa
      competizione e stagione (regole under: confronto con i coetanei, non con la rosa);
    - precocity: per i 18-21enni, percentile della quota minuti tra i coetanei di tutte le
      competizioni nella stagione.
    Colonne richieste: age, birth_year, minutes, team_minutes, competition_id, season_id,
    macro."""
    from prospectlens.engine.basics import ecdf_pct

    df = rows.copy()
    df["relative_age"] = df["age"] - df.groupby(["competition_id", "season_id", "macro"])[
        "age"
    ].transform("mean")
    df["minutes_share"] = df["minutes"] / df["team_minutes"].where(df["team_minutes"] > 0)
    peers = df.groupby(["competition_id", "season_id", "birth_year"])["minutes_share"]
    median = peers.transform("median")
    df["share_vs_peers"] = df["minutes_share"] / median.where(median > 0)
    df["precocity"] = np.nan
    young = df["age"].between(18, 22, inclusive="left")
    for _, idx in df[young].groupby(["season_id", "birth_year"]).groups.items():
        df.loc[idx, "precocity"] = ecdf_pct(
            df.loc[idx, "minutes_share"], df.loc[idx, "minutes_share"]
        )
    return df
