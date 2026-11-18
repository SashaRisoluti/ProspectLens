"""Caricamento e validazione di config/sports/*.yaml.

Un errore nel YAML (campo sconosciuto, riferimento a un ruolo inesistente...) ferma
l'avvio con un messaggio che indica il campo sbagliato.
"""

from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NamedCode(_Strict):
    code: str
    name_it: str


class SpecificRole(NamedCode):
    macro: str


class Roles(_Strict):
    macro: list[NamedCode]
    specific: list[SpecificRole]


class Normalization(_Strict):
    unit: str
    per: float


class AgeConfig(_Strict):
    max_search_age: int
    max_search_age_by_goal: dict[str, int] = {}


class Thresholds(_Strict):
    min_minutes_sample: int
    valid_season_minutes: int
    default_shrinkage_k: float


class AgeCurve(_Strict):
    peak_age: float
    growth_per_year: float
    decline_per_year: float


class Metric(_Strict):
    code: str
    name_it: str
    kind: Literal["per90", "ratio"]
    stat: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    roles: list[str]
    higher_is_better: bool
    requires: str
    shrinkage_k: float | None = None
    description_it: str
    how_to_read_it: str
    formula_it: str

    @model_validator(mode="after")
    def _check_kind(self) -> Self:
        if self.kind == "per90" and not self.stat:
            raise ValueError(f"metrica {self.code}: kind=per90 richiede 'stat'")
        if self.kind == "ratio" and not (self.numerator and self.denominator):
            raise ValueError(f"metrica {self.code}: kind=ratio richiede numerator e denominator")
        return self


class Goal(_Strict):
    code: str
    letter: str
    name_it: str
    tagline_it: str
    requires: list[str]
    default_sort: str
    columns: list[str]
    suggested_filters: dict[str, Any]
    measures_it: str
    not_measures_it: str
    when_to_trust_it: str
    min_valid_seasons: int | None = None
    thresholds_percentile: dict[str, float] | None = None
    horizon_seasons: int | None = None


class SportConfig(_Strict):
    sport: NamedCode
    normalization: Normalization
    age: AgeConfig
    thresholds: Thresholds
    data_types: list[NamedCode]
    roles: Roles
    age_curves: dict[str, AgeCurve]
    league_strength_defaults: dict[int, float]
    metrics: list[Metric]
    goals: list[Goal]

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        macro = {r.code for r in self.roles.macro}
        data_types = {d.code for d in self.data_types}
        goals = {g.code for g in self.goals}
        errors: list[str] = []
        for role in self.roles.specific:
            if role.macro not in macro:
                errors.append(f"ruolo {role.code}: macro-ruolo sconosciuto {role.macro}")
        if set(self.age_curves) != macro:
            errors.append(f"age_curves deve avere esattamente i macro-ruoli {sorted(macro)}")
        for m in self.metrics:
            errors += [
                f"metrica {m.code}: ruolo sconosciuto {r}" for r in m.roles if r not in macro
            ]
            if m.requires not in data_types:
                errors.append(f"metrica {m.code}: tipo di dato sconosciuto {m.requires}")
        for g in self.goals:
            errors += [
                f"lente {g.code}: tipo di dato sconosciuto {d}"
                for d in g.requires
                if d not in data_types
            ]
        for code in self.age.max_search_age_by_goal:
            if code not in goals:
                errors.append(f"age.max_search_age_by_goal: lente sconosciuta {code}")
        for name, codes in (
            ("metriche", [m.code for m in self.metrics]),
            ("lenti", [g.code for g in self.goals]),
        ):
            if len(codes) != len(set(codes)):
                errors.append(f"codici {name} duplicati")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @property
    def macro_of(self) -> dict[str, str]:
        """Ruolo specifico -> macro-ruolo."""
        return {r.code: r.macro for r in self.roles.specific}


def load_sport_config(path: Path) -> SportConfig:
    with path.open(encoding="utf-8") as f:
        return SportConfig.model_validate(yaml.safe_load(f))


def load_sport(config_dir: Path, sport_code: str = "football") -> SportConfig:
    return load_sport_config(config_dir / "sports" / f"{sport_code}.yaml")
