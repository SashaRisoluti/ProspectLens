"""Interfaccia comune a tutte le fonti dati.

Ogni provider produce un `SeasonBundle` per (competizione, stagione), con ID esterni
(stringhe) del provider. L'importer li trasforma in righe del database.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, ClassVar


@dataclass(frozen=True, slots=True)
class CompetitionRec:
    ext_id: str
    name: str
    country_code: str
    level: int
    group_code: str | None


@dataclass(frozen=True, slots=True)
class SeasonRec:
    label: str
    start: date
    end: date


@dataclass(frozen=True, slots=True)
class TeamRec:
    ext_id: str
    name: str
    country_code: str


@dataclass(frozen=True, slots=True)
class PlayerRec:
    ext_id: str
    first_name: str
    last_name: str
    birth_date: date | None
    nationalities: tuple[str, ...]
    foot: str | None
    height_cm: int | None
    primary_position: str
    secondary_positions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SquadEntryRec:
    player_ext: str
    team_ext: str
    status: str  # owned | loan
    owner_team_ext: str | None = None
    contract_until: date | None = None


@dataclass(frozen=True, slots=True)
class MatchRec:
    ext_id: str
    matchday: int | None
    kickoff: datetime | None
    home_ext: str
    away_ext: str
    home_goals: int | None
    away_goals: int | None


@dataclass(frozen=True, slots=True)
class AppearanceRec:
    match_ext: str
    player_ext: str
    team_ext: str
    started: bool
    minute_in: int
    minute_out: int


@dataclass(frozen=True, slots=True)
class EventRec:
    match_ext: str
    team_ext: str
    player_ext: str | None
    related_player_ext: str | None
    minute: int
    type: str  # goal | own_goal | sub | yellow | red


@dataclass(frozen=True, slots=True)
class PlayerSeasonStatRec:
    player_ext: str
    team_ext: str
    minutes: int
    appearances: int
    starts: int
    stats: dict[str, float]


@dataclass(frozen=True, slots=True)
class MarketValueRec:
    player_ext: str
    value_eur: int
    observed_on: date


@dataclass(frozen=True, slots=True)
class InjuryRec:
    player_ext: str
    start: date
    end: date | None
    injury_type: str | None


@dataclass
class SeasonBundle:
    competition: CompetitionRec
    season: SeasonRec
    data_types: frozenset[str]
    under_rules: dict[str, Any] = field(default_factory=dict)
    teams: list[TeamRec] = field(default_factory=list)
    players: list[PlayerRec] = field(default_factory=list)
    squad: list[SquadEntryRec] = field(default_factory=list)
    matches: list[MatchRec] = field(default_factory=list)
    appearances: list[AppearanceRec] = field(default_factory=list)
    events: list[EventRec] = field(default_factory=list)
    stats: list[PlayerSeasonStatRec] = field(default_factory=list)
    market_values: list[MarketValueRec] = field(default_factory=list)
    injuries: list[InjuryRec] = field(default_factory=list)


class DataProvider(ABC):
    source: ClassVar[str]
    description: ClassVar[str]
    license_note: ClassVar[str | None] = None

    @abstractmethod
    def bundles(self) -> Iterator[SeasonBundle]:
        """Un bundle per competizione e stagione, in ordine cronologico."""
