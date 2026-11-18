"""Modello dati. Indipendente dallo sport: `sport_id` sulle entità principali,
statistiche in JSONB con chiavi definite nella configurazione YAML."""

from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSONB,
        list[str]: ARRAY(String),
    }


def _fk(target: str, *, nullable: bool = False, cascade: bool = False) -> Mapped[Any]:
    return mapped_column(
        ForeignKey(target, ondelete="CASCADE" if cascade else None),
        nullable=nullable,
        index=True,
    )


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------------------- riferimento


class Sport(Base):
    __tablename__ = "sport"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))


class Country(Base):
    """Codice ISO 3166-1 alpha-2. Il nome si mostra con Intl.DisplayNames lato web."""

    __tablename__ = "country"
    code: Mapped[str] = mapped_column(String(2), primary_key=True)
    is_eu: Mapped[bool] = mapped_column(Boolean, default=False)


class DataSource(Base):
    """Una riga per ogni import: dice da quale fonte e da quale data arriva un dato."""

    __tablename__ = "data_source"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    license_note: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = _created()


class Season(Base):
    __tablename__ = "season"
    __table_args__ = (UniqueConstraint("sport_id", "label"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sport_id: Mapped[int] = _fk("sport.id")
    label: Mapped[str] = mapped_column(String(16))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)


class Competition(Base):
    """Una riga per girone: 'Serie C' girone 'A' e girone 'B' sono due competizioni
    con lo stesso `name` e `level`."""

    __tablename__ = "competition"
    __table_args__ = (UniqueConstraint("source", "ext_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sport_id: Mapped[int] = _fk("sport.id")
    country_code: Mapped[str | None] = mapped_column(ForeignKey("country.code"))
    source: Mapped[str] = mapped_column(String(32))
    ext_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    group_code: Mapped[str | None] = mapped_column(String(16))
    level: Mapped[int] = mapped_column(Integer)


class CompetitionSeason(Base):
    """Dati disponibili e regole sugli under, per competizione e stagione."""

    __tablename__ = "competition_season"
    __table_args__ = (UniqueConstraint("competition_id", "season_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = _fk("competition.id")
    season_id: Mapped[int] = _fk("season.id")
    data_types: Mapped[list[str]] = mapped_column(default=list)
    under_rules: Mapped[dict[str, Any]] = mapped_column(default=dict)
    source_id: Mapped[int] = _fk("data_source.id")


class Team(Base):
    __tablename__ = "team"
    __table_args__ = (UniqueConstraint("source", "ext_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sport_id: Mapped[int] = _fk("sport.id")
    country_code: Mapped[str | None] = mapped_column(ForeignKey("country.code"))
    source: Mapped[str] = mapped_column(String(32))
    ext_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))


class Player(Base):
    # shortcut: identità per (source, ext_id); stesso giocatore da due fonti = due righe.
    # Serve una tabella di collegamento quando si importano più fonti insieme.
    __tablename__ = "player"
    __table_args__ = (UniqueConstraint("source", "ext_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sport_id: Mapped[int] = _fk("sport.id")
    source: Mapped[str] = mapped_column(String(32))
    ext_id: Mapped[str] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(64))
    last_name: Mapped[str] = mapped_column(String(64))
    birth_date: Mapped[date | None] = mapped_column(Date, index=True)
    nationalities: Mapped[list[str]] = mapped_column(default=list)
    foot: Mapped[str | None] = mapped_column(String(8))
    height_cm: Mapped[int | None] = mapped_column(Integer)
    primary_position: Mapped[str] = mapped_column(String(8))
    secondary_positions: Mapped[list[str]] = mapped_column(default=list)


class PlayerTeamSeason(Base):
    __tablename__ = "player_team_season"
    __table_args__ = (UniqueConstraint("player_id", "team_id", "competition_id", "season_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = _fk("player.id")
    team_id: Mapped[int] = _fk("team.id")
    competition_id: Mapped[int] = _fk("competition.id")
    season_id: Mapped[int] = _fk("season.id")
    status: Mapped[str] = mapped_column(String(8))  # owned | loan
    owner_team_id: Mapped[int | None] = _fk("team.id", nullable=True)
    contract_until: Mapped[date | None] = mapped_column(Date)


# --------------------------------------------------------------------------- partite


class Match(Base):
    __tablename__ = "match"
    __table_args__ = (
        UniqueConstraint("source", "ext_id"),
        Index("ix_match_comp_season", "competition_id", "season_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competition.id"))
    season_id: Mapped[int] = mapped_column(ForeignKey("season.id"))
    source: Mapped[str] = mapped_column(String(32))
    ext_id: Mapped[str] = mapped_column(String(64))
    matchday: Mapped[int | None] = mapped_column(Integer)
    kickoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    home_team_id: Mapped[int] = _fk("team.id")
    away_team_id: Mapped[int] = _fk("team.id")
    home_goals: Mapped[int | None] = mapped_column(Integer)
    away_goals: Mapped[int | None] = mapped_column(Integer)
    source_id: Mapped[int] = _fk("data_source.id")


class Appearance(Base):
    __tablename__ = "appearance"
    __table_args__ = (UniqueConstraint("match_id", "player_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("match.id", ondelete="CASCADE"))
    player_id: Mapped[int] = _fk("player.id")
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id"))
    started: Mapped[bool] = mapped_column(Boolean)
    minute_in: Mapped[int] = mapped_column(Integer)
    minute_out: Mapped[int] = mapped_column(Integer)


class MatchEvent(Base):
    """type: goal (related = assist), own_goal, sub (player = entra, related = esce),
    yellow, red."""

    __tablename__ = "match_event"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    match_id: Mapped[int] = _fk("match.id", cascade=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id"))
    player_id: Mapped[int | None] = _fk("player.id", nullable=True)
    related_player_id: Mapped[int | None] = mapped_column(ForeignKey("player.id"))
    minute: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(16))


class PlayerSeasonStats(Base):
    """`raw`: totali stagionali per codice statistica; `per90`: riempito dal motore."""

    __tablename__ = "player_season_stats"
    __table_args__ = (UniqueConstraint("player_id", "team_id", "competition_id", "season_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = _fk("player.id")
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id"))
    competition_id: Mapped[int] = mapped_column(ForeignKey("competition.id"))
    season_id: Mapped[int] = _fk("season.id")
    minutes: Mapped[int] = mapped_column(Integer)
    appearances: Mapped[int] = mapped_column(Integer)
    starts: Mapped[int] = mapped_column(Integer)
    raw: Mapped[dict[str, Any]] = mapped_column(default=dict)
    per90: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_id: Mapped[int] = _fk("data_source.id")


class MarketValueSnapshot(Base):
    __tablename__ = "market_value_snapshot"
    __table_args__ = (UniqueConstraint("player_id", "observed_on"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = _fk("player.id")
    value_eur: Mapped[int] = mapped_column(BigInteger)
    observed_on: Mapped[date] = mapped_column(Date)
    source_id: Mapped[int] = _fk("data_source.id")


class InjuryRecord(Base):
    __tablename__ = "injury_record"
    __table_args__ = (UniqueConstraint("player_id", "start_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = _fk("player.id")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    injury_type: Mapped[str | None] = mapped_column(String(64))
    source_id: Mapped[int] = _fk("data_source.id")


class LeagueStrength(Base):
    """Coefficiente di forza per competizione/girone, in unità di Livello.
    source: estimated (stimato dalla pipeline) | admin (fissato dall'amministratore,
    la pipeline non lo sovrascrive)."""

    __tablename__ = "league_strength"
    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competition.id"), unique=True)
    coefficient: Mapped[float] = mapped_column(Float)
    default_coefficient: Mapped[float] = mapped_column(Float)
    n_movers: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(16), default="estimated")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# --------------------------------------------------------------------------- definizioni


class MetricDefinition(Base):
    """Copia di `metrics:` del YAML, sincronizzata dalla pipeline."""

    __tablename__ = "metric_definition"
    __table_args__ = (UniqueConstraint("sport_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sport_id: Mapped[int] = _fk("sport.id")
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))
    roles: Mapped[list[str]] = mapped_column(default=list)
    higher_is_better: Mapped[bool] = mapped_column(Boolean)
    requires: Mapped[str] = mapped_column(String(32))
    formula: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    how_to_read: Mapped[str] = mapped_column(Text)
    definition: Mapped[dict[str, Any]] = mapped_column(default=dict)


class GoalDefinition(Base):
    """Copia di `goals:` (le lenti) del YAML."""

    __tablename__ = "goal_definition"
    __table_args__ = (UniqueConstraint("sport_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sport_id: Mapped[int] = _fk("sport.id")
    code: Mapped[str] = mapped_column(String(32))
    letter: Mapped[str] = mapped_column(String(1))
    name: Mapped[str] = mapped_column(String(64))
    definition: Mapped[dict[str, Any]] = mapped_column(default=dict)


# --------------------------------------------------------------------------- punteggi


class PlayerScore(Base):
    __tablename__ = "player_score"
    __table_args__ = (UniqueConstraint("player_id", "season_id", "model_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = _fk("player.id")
    season_id: Mapped[int] = _fk("season.id")
    level: Mapped[float | None] = mapped_column(Float)
    talent_index: Mapped[float | None] = mapped_column(Float)
    promotion_prob: Mapped[float | None] = mapped_column(Float)
    reliability: Mapped[str] = mapped_column(String(8))  # high | medium | low
    components: Mapped[dict[str, Any]] = mapped_column(default=dict)
    data_used: Mapped[dict[str, Any]] = mapped_column(default=dict)
    model_version: Mapped[str] = mapped_column(String(32))
    computed_at: Mapped[datetime] = _created()


class PlayerGoalScore(Base):
    __tablename__ = "player_goal_score"
    __table_args__ = (UniqueConstraint("player_id", "season_id", "goal_code", "model_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = _fk("player.id")
    season_id: Mapped[int] = _fk("season.id")
    goal_code: Mapped[str] = mapped_column(String(32))
    # ok | insufficient_history | not_available (dati mancanti per la competizione)
    status: Mapped[str] = mapped_column(String(24))
    score: Mapped[float | None] = mapped_column(Float)
    ci_low: Mapped[float | None] = mapped_column(Float)
    ci_high: Mapped[float | None] = mapped_column(Float)
    reliability: Mapped[str] = mapped_column(String(8))
    components: Mapped[dict[str, Any]] = mapped_column(default=dict)
    data_used: Mapped[dict[str, Any]] = mapped_column(default=dict)
    model_version: Mapped[str] = mapped_column(String(32))
    computed_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- multi-utente
# Tutto ciò che appartiene a un club si cancella con il club (GDPR).


class Organization(Base):
    __tablename__ = "organization"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _created()


class AppUser(Base):
    __tablename__ = "app_user"  # "user" è riservato in PostgreSQL
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = _fk("organization.id", cascade=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))  # platform_admin | org_admin | scout
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    tour_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()


class Shortlist(Base):
    __tablename__ = "shortlist"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = _fk("organization.id", cascade=True)
    name: Mapped[str] = mapped_column(String(128))
    role_code: Mapped[str | None] = mapped_column(String(8))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()


class ShortlistItem(Base):
    __tablename__ = "shortlist_item"
    __table_args__ = (UniqueConstraint("shortlist_id", "player_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    shortlist_id: Mapped[int] = _fk("shortlist.id", cascade=True)
    player_id: Mapped[int] = _fk("player.id")
    # to_watch | watched | negotiating | discarded
    status: Mapped[str] = mapped_column(String(16), default="to_watch")
    added_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    added_at: Mapped[datetime] = _created()


class Note(Base):
    __tablename__ = "note"
    __table_args__ = (Index("ix_note_org_player", "organization_id", "player_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organization.id", ondelete="CASCADE"))
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id"))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SavedSearch(Base):
    __tablename__ = "saved_search"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = _fk("organization.id", cascade=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(128))
    goal_code: Mapped[str] = mapped_column(String(32))  # una lente o "custom"
    weights: Mapped[dict[str, Any]] = mapped_column(default=dict)
    filters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = _created()
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Alert(Base):
    __tablename__ = "alert"
    __table_args__ = (UniqueConstraint("saved_search_id", "player_id", "season_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = _fk("organization.id", cascade=True)
    saved_search_id: Mapped[int] = _fk("saved_search.id", cascade=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id"))
    season_id: Mapped[int] = mapped_column(ForeignKey("season.id"))
    created_at: Mapped[datetime] = _created()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
