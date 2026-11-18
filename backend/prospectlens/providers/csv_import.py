"""CsvImportProvider: statistiche stagionali da file esportati (Wyscout o simili).

Un file = una competizione in una stagione. La mappatura delle colonne sta in
config/csv/<nome>.yaml. Il file non ha ID: giocatori e squadre ricevono un ID stabile
calcolato da nome, data di nascita (o età) e squadra.
"""

import csv
import hashlib
import logging
import re
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from prospectlens.providers.base import (
    CompetitionRec,
    DataProvider,
    MarketValueRec,
    PlayerRec,
    PlayerSeasonStatRec,
    SeasonBundle,
    SeasonRec,
    SquadEntryRec,
    TeamRec,
)

log = logging.getLogger(__name__)
REQUIRED = ("player_name", "team", "minutes")
ADVANCED = {
    "shots_on_target",
    "key_passes",
    "passes",
    "duels",
    "duels_won",
    "dribbles_won",
    "tackles_interceptions",
    "saves",
}


class StatColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    per90: bool = False


class CsvMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delimiter: str = ","
    columns: dict[str, str]
    stats: dict[str, StatColumn]
    positions: dict[str, str]
    foot: dict[str, str] = {}
    countries: dict[str, str] = {}


def load_mapping(path: Path) -> CsvMapping:
    with path.open(encoding="utf-8") as f:
        mapping = CsvMapping.model_validate(yaml.safe_load(f))
    missing = [k for k in REQUIRED if k not in mapping.columns]
    if missing:
        raise ValueError(f"{path.name}: colonne obbligatorie non mappate: {missing}")
    return mapping


def _number(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = raw.strip().replace("€", "").replace(" ", "")
    if not text or text == "-":
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _date(raw: str | None) -> date | None:
    raw = (raw or "").strip()
    for pattern, order in (
        (r"^(\d{4})-(\d{2})-(\d{2})", "ymd"),
        (r"^(\d{2})/(\d{2})/(\d{4})", "dmy"),
    ):
        m = re.match(pattern, raw)
        if m:
            a, b, c = map(int, m.groups())
            return date(a, b, c) if order == "ymd" else date(c, b, a)
    return None


def _id(*parts: object) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]


class CsvImportProvider(DataProvider):
    source = "csv"
    description = "Import da file CSV fornito dal club"
    license_note = "File fornito dall'utente: la licenza d'uso è responsabilità del club"

    def __init__(
        self, path: Path, mapping: CsvMapping, competition: CompetitionRec, season: SeasonRec
    ) -> None:
        self.path = path
        self.mapping = mapping
        self.competition = competition
        self.season = season

    def bundles(self) -> Iterator[SeasonBundle]:
        cols = self.mapping.columns
        with self.path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f, delimiter=self.mapping.delimiter))
        if rows:
            missing = [cols[k] for k in REQUIRED if cols[k] not in rows[0]]
            if missing:
                raise ValueError(f"{self.path.name}: colonne mancanti nel file: {missing}")
        b = SeasonBundle(self.competition, self.season, frozenset())
        teams: dict[str, TeamRec] = {}
        has_advanced = has_value = False
        for n, row in enumerate(rows, start=2):

            def get(key: str, row: dict[str, str] = row) -> str | None:
                col = cols.get(key)
                return row.get(col) if col else None

            name = (get("player_name") or "").strip()
            team_name = (get("team") or "").strip()
            minutes = int(_number(get("minutes")) or 0)
            if not name or not team_name:
                log.warning("riga %d: giocatore o squadra mancante, saltata", n)
                continue
            team = teams.setdefault(team_name, TeamRec(_id("team", team_name), team_name, "IT"))
            birth = _date(get("birth_date"))
            age = _number(get("age"))
            if birth is None and age is not None:
                birth = self.season.start - timedelta(days=int((age + 0.5) * 365.25))
            pid = _id("player", name, birth or "", team_name if birth is None else "")
            first, _, last = name.rpartition(" ") if " " in name else ("", "", name)
            pos = [
                self.mapping.positions.get(p.strip()) for p in (get("position") or "").split(",")
            ]
            roles = [p for p in pos if p]
            nats = []
            for country in (get("nationality") or "").split(","):
                country = country.strip()
                if country:
                    code = self.mapping.countries.get(country)
                    if code:
                        nats.append(code)
                    else:
                        log.warning("riga %d: paese non mappato '%s'", n, country)
            height = _number(get("height_cm"))
            b.players.append(
                PlayerRec(
                    pid,
                    first,
                    last,
                    birth,
                    tuple(dict.fromkeys(nats)),
                    self.mapping.foot.get((get("foot") or "").strip().lower()),
                    int(height) if height else None,
                    roles[0] if roles else "MF",
                    tuple(roles[1:]),
                )
            )
            loan = (get("on_loan") or "").strip().lower() in ("yes", "sì", "si", "true", "1")
            b.squad.append(
                SquadEntryRec(
                    pid,
                    team.ext_id,
                    "loan" if loan else "owned",
                    None,
                    _date(get("contract_until")),
                )
            )
            stats: dict[str, float] = {}
            for code, spec in self.mapping.stats.items():
                value = _number(row.get(spec.column))
                if value is None:
                    continue
                stats[code] = round(value * minutes / 90, 2) if spec.per90 else value
                has_advanced |= code in ADVANCED
            if minutes:
                apps = _number(get("appearances"))
                b.stats.append(
                    PlayerSeasonStatRec(pid, team.ext_id, minutes, int(apps or 0), 0, stats)
                )
            value = _number(get("market_value_eur"))
            if value:
                has_value = True
                b.market_values.append(MarketValueRec(pid, int(value), self.season.start))
        b.teams = list(teams.values())
        b.data_types = frozenset(
            {"player_stats_basic"}
            | ({"player_stats_advanced"} if has_advanced else set())
            | ({"market_values"} if has_value else set())
        )
        yield b
