"""Import idempotente dei SeasonBundle nel database.

- Entità con ID esterno: upsert su (source, ext_id).
- Presenze ed eventi: cancellati e reinseriti per le partite del bundle.
- Ogni import crea una riga `data_source`: ogni dato sa da quale fonte e data arriva.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from prospectlens.db import models as m
from prospectlens.providers.base import DataProvider, SeasonBundle

EU = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
    }
)
_MAX_PARAMS = 30_000


@dataclass
class ImportReport:
    bundles: int = 0
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, name: str, n: int) -> None:
        self.counts[name] = self.counts.get(name, 0) + n


def _upsert(
    session: Session,
    model: type[m.Base],
    rows: Sequence[dict[str, Any]],
    key: tuple[str, ...],
    returning: bool = True,
) -> dict[tuple[Any, ...], int]:
    """INSERT ... ON CONFLICT (key) DO UPDATE. Restituisce chiave -> id."""
    unique = list({tuple(r[k] for k in key): r for r in rows}.values())
    ids: dict[tuple[Any, ...], int] = {}
    if not unique:
        return ids
    table = model.__table__
    cols = list(unique[0])
    size = max(1, _MAX_PARAMS // len(cols))
    for i in range(0, len(unique), size):
        stmt = pg_insert(model).values(unique[i : i + size])
        update = {c: stmt.excluded[c] for c in cols if c not in key}
        stmt = (
            stmt.on_conflict_do_update(index_elements=list(key), set_=update)
            if update
            else stmt.on_conflict_do_nothing(index_elements=list(key))
        )
        if returning:
            res = session.execute(stmt.returning(table.c.id, *(table.c[k] for k in key)))
            ids.update({tuple(row[1:]): row[0] for row in res})
        else:
            session.execute(stmt)
    return ids


def _bulk_insert(session: Session, model: type[m.Base], rows: list[dict[str, Any]]) -> None:
    if rows:
        session.execute(insert(model), rows)


def ensure_sport(session: Session, code: str, name: str) -> int:
    ids = _upsert(session, m.Sport, [{"code": code, "name": name}], ("code",))
    return ids[(code,)]


def import_provider(session: Session, provider: DataProvider, sport_id: int) -> ImportReport:
    source = m.DataSource(
        provider=provider.source,
        description=provider.description,
        license_note=provider.license_note,
    )
    session.add(source)
    session.flush()
    report = ImportReport()
    for bundle in provider.bundles():
        _import_bundle(session, bundle, provider.source, sport_id, source.id, report)
        session.commit()
        report.bundles += 1
    return report


def _countries(session: Session, codes: Iterable[str]) -> None:
    rows = [{"code": c, "is_eu": c in EU} for c in set(codes)]
    _upsert(session, m.Country, rows, ("code",), returning=False)


def _import_bundle(
    session: Session, b: SeasonBundle, src: str, sport_id: int, source_id: int, report: ImportReport
) -> None:
    c = b.competition
    _countries(
        session,
        [
            c.country_code,
            *(t.country_code for t in b.teams),
            *(n for p in b.players for n in p.nationalities),
        ],
    )
    season_id = _upsert(
        session,
        m.Season,
        [
            {
                "sport_id": sport_id,
                "label": b.season.label,
                "start_date": b.season.start,
                "end_date": b.season.end,
            }
        ],
        ("sport_id", "label"),
    )[(sport_id, b.season.label)]
    comp_id = _upsert(
        session,
        m.Competition,
        [
            {
                "sport_id": sport_id,
                "country_code": c.country_code,
                "source": src,
                "ext_id": c.ext_id,
                "name": c.name,
                "group_code": c.group_code,
                "level": c.level,
            }
        ],
        ("source", "ext_id"),
    )[(src, c.ext_id)]
    _upsert(
        session,
        m.CompetitionSeason,
        [
            {
                "competition_id": comp_id,
                "season_id": season_id,
                "data_types": sorted(b.data_types),
                "under_rules": b.under_rules,
                "source_id": source_id,
            }
        ],
        ("competition_id", "season_id"),
        returning=False,
    )

    team_ids = {
        k[1]: v
        for k, v in _upsert(
            session,
            m.Team,
            [
                {
                    "sport_id": sport_id,
                    "country_code": t.country_code,
                    "source": src,
                    "ext_id": t.ext_id,
                    "name": t.name,
                }
                for t in b.teams
            ],
            ("source", "ext_id"),
        ).items()
    }
    owner_exts = {s.owner_team_ext for s in b.squad if s.owner_team_ext} - set(team_ids)
    if owner_exts:  # club proprietari dei prestiti, importati con un altro bundle
        rows = session.execute(
            select(m.Team.ext_id, m.Team.id).where(
                m.Team.source == src, m.Team.ext_id.in_(owner_exts)
            )
        )
        team_ids |= {ext: tid for ext, tid in rows}
    player_ids = {
        k[1]: v
        for k, v in _upsert(
            session,
            m.Player,
            [
                {
                    "sport_id": sport_id,
                    "source": src,
                    "ext_id": p.ext_id,
                    "first_name": p.first_name,
                    "last_name": p.last_name,
                    "birth_date": p.birth_date,
                    "nationalities": list(p.nationalities),
                    "foot": p.foot,
                    "height_cm": p.height_cm,
                    "primary_position": p.primary_position,
                    "secondary_positions": list(p.secondary_positions),
                }
                for p in b.players
            ],
            ("source", "ext_id"),
        ).items()
    }
    scope = {"competition_id": comp_id, "season_id": season_id}

    _upsert(
        session,
        m.PlayerTeamSeason,
        [
            {
                "player_id": player_ids[s.player_ext],
                "team_id": team_ids[s.team_ext],
                **scope,
                "status": s.status,
                "owner_team_id": team_ids.get(s.owner_team_ext or ""),
                "contract_until": s.contract_until,
            }
            for s in b.squad
        ],
        ("player_id", "team_id", "competition_id", "season_id"),
        returning=False,
    )

    match_ids = {
        k[1]: v
        for k, v in _upsert(
            session,
            m.Match,
            [
                {
                    **scope,
                    "source": src,
                    "ext_id": x.ext_id,
                    "matchday": x.matchday,
                    "kickoff": x.kickoff,
                    "home_team_id": team_ids[x.home_ext],
                    "away_team_id": team_ids[x.away_ext],
                    "home_goals": x.home_goals,
                    "away_goals": x.away_goals,
                    "source_id": source_id,
                }
                for x in b.matches
            ],
            ("source", "ext_id"),
        ).items()
    }
    ids = list(match_ids.values())
    session.execute(delete(m.Appearance).where(m.Appearance.match_id.in_(ids)))
    session.execute(delete(m.MatchEvent).where(m.MatchEvent.match_id.in_(ids)))

    def pid(ext: str | None) -> int | None:
        return player_ids[ext] if ext else None

    _bulk_insert(
        session,
        m.Appearance,
        [
            {
                "match_id": match_ids[a.match_ext],
                "player_id": player_ids[a.player_ext],
                "team_id": team_ids[a.team_ext],
                "started": a.started,
                "minute_in": a.minute_in,
                "minute_out": a.minute_out,
            }
            for a in b.appearances
        ],
    )
    _bulk_insert(
        session,
        m.MatchEvent,
        [
            {
                "match_id": match_ids[e.match_ext],
                "team_id": team_ids[e.team_ext],
                "player_id": pid(e.player_ext),
                "related_player_id": pid(e.related_player_ext),
                "minute": e.minute,
                "type": e.type,
            }
            for e in b.events
        ],
    )
    _upsert(
        session,
        m.PlayerSeasonStats,
        [
            {
                "player_id": player_ids[s.player_ext],
                "team_id": team_ids[s.team_ext],
                **scope,
                "minutes": s.minutes,
                "appearances": s.appearances,
                "starts": s.starts,
                "raw": s.stats,
                "source_id": source_id,
            }
            for s in b.stats
        ],
        ("player_id", "team_id", "competition_id", "season_id"),
        returning=False,
    )
    _upsert(
        session,
        m.MarketValueSnapshot,
        [
            {
                "player_id": player_ids[v.player_ext],
                "value_eur": v.value_eur,
                "observed_on": v.observed_on,
                "source_id": source_id,
            }
            for v in b.market_values
        ],
        ("player_id", "observed_on"),
        returning=False,
    )
    _upsert(
        session,
        m.InjuryRecord,
        [
            {
                "player_id": player_ids[i.player_ext],
                "start_date": i.start,
                "end_date": i.end,
                "injury_type": i.injury_type,
                "source_id": source_id,
            }
            for i in b.injuries
        ],
        ("player_id", "start_date"),
        returning=False,
    )

    for name, n in (
        ("matches", len(b.matches)),
        ("appearances", len(b.appearances)),
        ("events", len(b.events)),
        ("stats", len(b.stats)),
    ):
        report.add(name, n)
