"""Metriche per 90, shrinkage bayesiano, percentili e Livello dentro la lega.

Tutte le funzioni lavorano sulle definizioni di `metrics:` del YAML: nessun nome di
metrica è scritto qui. Una riga = un giocatore in una squadra, competizione e stagione.

Colonne richieste in `stats`: competition_id, season_id, macro, minutes, data_types (set),
raw (dict statistica -> totale stagionale).
"""

from collections.abc import Iterable

import numpy as np
import pandas as pd

from prospectlens.config import Metric, SportConfig

GROUP = ["competition_id", "season_id", "macro"]


def ecdf_pct(values: Iterable[float], reference: Iterable[float]) -> np.ndarray:
    """Percentile (0-100) di ogni valore rispetto alla popolazione di riferimento.
    Ranghi medi: valori uguali ricevono lo stesso percentile."""
    ref = np.sort(np.asarray([r for r in reference if np.isfinite(r)], dtype=float))
    vals = np.asarray(list(values), dtype=float)
    if ref.size == 0:
        return np.full(vals.shape, np.nan)
    left = np.searchsorted(ref, vals, side="left")
    right = np.searchsorted(ref, vals, side="right")
    out = (left + right) / 2 / ref.size * 100
    return np.where(np.isfinite(vals), out, np.nan)


def shrink_per90(
    total: np.ndarray, minutes: np.ndarray, prior: float, k: float, per: float = 90.0
) -> np.ndarray:
    """stima = (totale + K x media) / (minuti/90 + K)."""
    return (total + k * prior) / (minutes / per + k)


def shrink_ratio(num: np.ndarray, den: np.ndarray, prior: float, k: float) -> np.ndarray:
    """stima = (riusciti + K x media) / (tentati + K), K in tentativi."""
    return (num + k * prior) / (den + k)


def _metric_values(stats: pd.DataFrame, m: Metric) -> tuple[pd.Series, pd.Series]:
    """(numeratore, denominatore) per riga; NaN se il dato manca."""

    def col(key: str | None) -> pd.Series:
        return stats["raw"].map(lambda r: r.get(key, np.nan) if key else np.nan).astype(float)

    if m.kind == "per90":
        return col(m.stat), stats["minutes"].astype(float)
    return col(m.numerator), col(m.denominator)


def add_metrics(stats: pd.DataFrame, cfg: SportConfig) -> pd.DataFrame:
    """Aggiunge per ogni metrica: <code>__raw (per 90 o rapporto grezzo), <code>__est
    (con shrinkage), <code>__pct (percentile nel gruppo), <code>__z (z-score con segno:
    più alto = meglio). Poi `level_n` (metriche usate) e `z_within` (Livello nella lega)."""
    df = stats.copy()
    per = cfg.normalization.per
    min_sample = cfg.thresholds.min_minutes_sample
    reference = df["minutes"] >= min_sample
    z_cols = []
    for m in cfg.metrics:
        num, den = _metric_values(df, m)
        ok = (
            df["macro"].isin(m.roles)
            & df["data_types"].map(lambda t, r=m.requires: r in t)
            & num.notna()
            & den.notna()
            & (den > 0)
        )
        k = m.shrinkage_k if m.shrinkage_k is not None else cfg.thresholds.default_shrinkage_k
        raw = pd.Series(np.nan, index=df.index)
        est = pd.Series(np.nan, index=df.index)
        for _, idx in df[ok].groupby(GROUP).groups.items():
            ref = idx[reference.loc[idx]] if reference.loc[idx].any() else idx
            n, d = num.loc[idx].to_numpy(), den.loc[idx].to_numpy()
            if m.kind == "per90":
                prior = num.loc[ref].sum() / (den.loc[ref].sum() / per)
                raw.loc[idx] = n / (d / per)
                est.loc[idx] = shrink_per90(n, d, prior, k, per)
            else:
                prior = num.loc[ref].sum() / den.loc[ref].sum()
                raw.loc[idx] = n / d
                est.loc[idx] = shrink_ratio(n, d, prior, k)
        signed = est if m.higher_is_better else -est
        pct = pd.Series(np.nan, index=df.index)
        z = pd.Series(np.nan, index=df.index)
        for _, idx in df[ok].groupby(GROUP).groups.items():
            ref = idx[reference.loc[idx]] if reference.loc[idx].any() else idx
            pct.loc[idx] = ecdf_pct(signed.loc[idx], signed.loc[ref])
            sd = signed.loc[ref].std(ddof=0)
            if sd > 0:
                z.loc[idx] = (signed.loc[idx] - signed.loc[ref].mean()) / sd
        df[f"{m.code}__raw"], df[f"{m.code}__est"] = raw, est
        df[f"{m.code}__pct"], df[f"{m.code}__z"] = pct, z
        z_cols.append(f"{m.code}__z")
    weights = pd.Series({f"{m.code}__z": m.weight for m in cfg.metrics})
    zs = df[z_cols]
    df["level_n"] = zs.notna().sum(axis=1)
    # media pesata degli z-score disponibili per la riga
    composite = zs.mul(weights, axis=1).sum(axis=1) / zs.notna().mul(weights, axis=1).sum(axis=1)
    composite[df["level_n"] < cfg.engine.min_metrics_for_level] = np.nan
    df["z_within"] = np.nan
    for _, idx in df.groupby(GROUP).groups.items():
        c = composite.loc[idx]
        ref = c[reference.loc[idx]].dropna()
        if len(ref) >= 2 and ref.std(ddof=0) > 0:
            df.loc[idx, "z_within"] = (c - ref.mean()) / ref.std(ddof=0)
    return df


def metric_payload(row: pd.Series, cfg: SportConfig) -> dict[str, dict[str, float]]:
    """JSON per player_season_stats.per90: grezzo, stimato, percentile per metrica."""
    out = {}
    for m in cfg.metrics:
        est = row.get(f"{m.code}__est")
        if est is not None and np.isfinite(est):
            out[m.code] = {
                "raw": round(float(row[f"{m.code}__raw"]), 4),
                "est": round(float(est), 4),
                "pct": round(float(row[f"{m.code}__pct"]), 1),
            }
    return out
