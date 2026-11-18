"""ApiFootballProvider: converte le risposte di API-Football v3 in SeasonBundle.

Richieste per (competizione, stagione): calendario (1), dettagli delle partite concluse a
blocchi di 20 (formazioni + eventi), statistiche stagionali dei giocatori (una pagina ogni
20 giocatori), infortuni se dichiarati. Tutto passa dalla cache del client.

I tipi di dato disponibili si ricavano da ciò che arriva davvero, non dalla copertura
dichiarata. Limiti noti del fornitore: nessun valore di mercato, nessun piede, nessuna
informazione su prestiti; ruolo solo per macro-ruolo.
"""

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from prospectlens.providers.api_football_client import ApiFootballClient
from prospectlens.providers.base import (
    AppearanceRec,
    CompetitionRec,
    DataProvider,
    EventRec,
    InjuryRec,
    MatchRec,
    PlayerRec,
    PlayerSeasonStatRec,
    SeasonBundle,
    SeasonRec,
    SquadEntryRec,
    TeamRec,
)

log = logging.getLogger(__name__)

# Competizioni di interesse: espressione sul nome API -> (nome, livello). Gli ID si
# cercano per nome, non sono scritti nel codice.
COMPETITIONS = [
    (r"^Serie A$", "Serie A", 1),
    (r"^Serie B$", "Serie B", 2),
    (r"^Serie C - Girone [A-C]$", "Serie C", 3),
    (r"^Serie D - Girone [A-I]$", "Serie D", 4),
    (r"^Campionato Primavera - 1$", "Primavera 1", 0),
    (r"^Campionato Primavera - 2$", "Primavera 2", 0),
]
POSITION = {
    "Goalkeeper": "GK",
    "Defender": "DF",
    "Midfielder": "MF",
    "Attacker": "FW",
    "G": "GK",
    "D": "DF",
    "M": "MF",
    "F": "FW",
}
FINISHED = {"FT", "AET", "PEN"}
FULL_TIME = 90


@dataclass(frozen=True)
class LeagueSeason:
    league_id: int
    season: int  # anno di inizio, come nel fornitore


def match_competition(api_name: str) -> tuple[str, int] | None:
    for pattern, name, level in COMPETITIONS:
        if re.match(pattern, api_name):
            return name, level
    return None


def _minute(ev: dict[str, Any]) -> int:
    return max(1, min(int((ev.get("time") or {}).get("elapsed") or 1), FULL_TIME))


def _height(raw: Any) -> int | None:
    m = re.match(r"\s*(\d{3})", str(raw or ""))
    return int(m.group(1)) if m else None


def _date(raw: Any) -> date | None:
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


class ApiFootballProvider(DataProvider):
    source = "api-football"
    description = "API-Football v3 (api-sports.io)"
    license_note = (
        "Dati soggetti ai termini d'uso di API-Football: verificare la licenza "
        "prima di mostrarli a terzi"
    )

    def __init__(
        self,
        client: ApiFootballClient,
        targets: list[LeagueSeason],
        match_details: bool = False,
        max_pages: int = 3,  # limite del piano Free per l'elenco giocatori
    ) -> None:
        """match_details: scarica formazioni ed eventi, una richiesta per partita (sul piano
        Free circa 380 per girone). Senza: solo risultati e statistiche stagionali."""
        self.client = client
        self.targets = targets
        self.match_details = match_details
        self.max_pages = max_pages

    def bundles(self) -> Iterator[SeasonBundle]:
        leagues = self.client.get("leagues", {"country": "Italy"}, ttl=timedelta(days=7))
        countries = self.client.get("countries")
        self._country = {
            c["name"]: c["code"]
            for c in countries.get("response", [])
            if c.get("code") and len(c["code"]) == 2
        }
        info = {item["league"]["id"]: item for item in leagues["response"]}
        for t in self.targets:
            item = info.get(t.league_id)
            if item is None:
                raise ValueError(f"competizione {t.league_id} non trovata tra quelle italiane")
            yield self._bundle(t, item)

    # ------------------------------------------------------------------ bundle

    def _bundle(self, t: LeagueSeason, item: dict[str, Any]) -> SeasonBundle:
        api_name = item["league"]["name"]
        found = match_competition(api_name)
        if found is None:
            raise ValueError(f"competizione non prevista: {api_name}")
        name, level = found
        group = re.search(r"Girone ([A-I])$", api_name)
        season_meta = next(s for s in item["seasons"] if s["year"] == t.season)
        comp = CompetitionRec(
            str(t.league_id), name, "IT", level, group.group(1) if group else None
        )
        season = SeasonRec(
            f"{t.season}-{(t.season + 1) % 100:02d}",
            date.fromisoformat(season_meta["start"]),
            date.fromisoformat(season_meta["end"]),
        )
        params = {"league": t.league_id, "season": t.season}
        fixtures = self._ok(self.client.get("fixtures", params))
        b = SeasonBundle(comp, season, frozenset())
        teams: dict[str, TeamRec] = {}
        players: dict[str, PlayerRec] = {}
        done = []
        for f in fixtures:
            for side in ("home", "away"):
                tm = f["teams"][side]
                teams[str(tm["id"])] = TeamRec(str(tm["id"]), tm["name"], "IT")
            rnd = re.search(r"(\d+)$", f["league"].get("round") or "")
            b.matches.append(
                MatchRec(
                    str(f["fixture"]["id"]),
                    int(rnd.group(1)) if rnd else None,
                    datetime.fromisoformat(f["fixture"]["date"]),
                    str(f["teams"]["home"]["id"]),
                    str(f["teams"]["away"]["id"]),
                    f["goals"]["home"],
                    f["goals"]["away"],
                )
            )
            if f["fixture"]["status"]["short"] in FINISHED:
                done.append(f["fixture"]["id"])
        if self.match_details:
            for fid in done:  # il piano Free non accetta `ids`
                for d in self._ok(self.client.get("fixtures", {"id": fid})):
                    self._match_detail(d, b, players)
        self._season_stats(t, name, set(teams), b, players)
        if season_meta["coverage"].get("injuries"):
            for row in self._ok(self.client.get("injuries", params)):
                start = _date((row.get("fixture") or {}).get("date"))
                pid = str(row["player"]["id"])
                if start and pid in players:
                    # shortcut: una riga per partita saltata, non per periodo di infortunio
                    b.injuries.append(InjuryRec(pid, start, None, row["player"].get("reason")))
        b.teams = list(teams.values())
        b.players = list(players.values())
        types = {"results"} if done else set()
        if b.appearances:
            types.add("lineups")
        if any(e.type == "sub" for e in b.events):
            types.add("substitutions")
        if any(e.type in ("goal", "own_goal") for e in b.events):
            types.add("events")
        if b.stats:
            types.add("player_stats_basic")
            adv = sum(1 for s in b.stats if "key_passes" in s.stats)
            if adv >= 0.5 * len(b.stats):
                types.add("player_stats_advanced")
        if b.injuries:
            types.add("injuries")
        b.data_types = frozenset(types)
        return b

    @staticmethod
    def _ok(body: dict[str, Any]) -> list[dict[str, Any]]:
        if body.get("errors"):
            raise RuntimeError(f"errore del fornitore: {body['errors']}")
        return list(body.get("response", []))

    def _player_from_lineup(self, p: dict[str, Any]) -> PlayerRec:
        name = (p.get("name") or "").split(" ", 1)
        first, last = (name[0], name[1]) if len(name) == 2 else ("", name[0])
        return PlayerRec(
            str(p["id"]), first, last, None, (), None, None, POSITION.get(p.get("pos") or "", "MF")
        )

    # ------------------------------------------------------------------ partita

    def _match_detail(
        self, d: dict[str, Any], b: SeasonBundle, players: dict[str, PlayerRec]
    ) -> None:
        ext = str(d["fixture"]["id"])
        lineups = d.get("lineups") or []
        team_of: dict[str, str] = {}
        on_pitch: set[str] = set()
        minute_in: dict[str, int] = {}
        minute_out: dict[str, int] = {}
        starters: set[str] = set()
        for lu in lineups:
            team = str(lu["team"]["id"])
            for key in ("startXI", "substitutes"):
                for row in lu.get(key) or []:
                    p = row["player"]
                    if p.get("id") is None:
                        continue
                    pid = str(p["id"])
                    team_of[pid] = team
                    players.setdefault(pid, self._player_from_lineup(p))
                    if key == "startXI":
                        starters.add(pid)
                        on_pitch.add(pid)
                        minute_in[pid], minute_out[pid] = 0, FULL_TIME
        events = sorted(d.get("events") or [], key=_minute)
        for ev in events:
            team = str((ev.get("team") or {}).get("id"))
            pid = str((ev.get("player") or {}).get("id"))
            other = (ev.get("assist") or {}).get("id")
            oid = str(other) if other is not None else None
            minute = _minute(ev)
            kind, detail = ev.get("type"), ev.get("detail") or ""
            if kind == "subst" and oid:
                # il fornitore non è coerente su chi entra ed esce: decide chi era in campo
                out_p, in_p = (pid, oid) if pid in on_pitch else (oid, pid)
                on_pitch.discard(out_p)
                on_pitch.add(in_p)
                minute_out[out_p] = minute
                minute_in[in_p], minute_out[in_p] = minute, FULL_TIME
                b.events.append(EventRec(ext, team, in_p, out_p, minute, "sub"))
            elif kind == "Goal" and detail != "Missed Penalty":
                if detail == "Own Goal":
                    # la squadra accreditata è l'avversaria di chi ha fatto autogol
                    scorer_team = team_of.get(pid, team)
                    credited = next(
                        (
                            str(lu["team"]["id"])
                            for lu in lineups
                            if str(lu["team"]["id"]) != scorer_team
                        ),
                        team,
                    )
                    b.events.append(EventRec(ext, credited, pid, None, minute, "own_goal"))
                else:
                    b.events.append(EventRec(ext, team, pid, oid, minute, "goal"))
            elif kind == "Card":
                red = "Red" in detail or "Second Yellow" in detail
                b.events.append(EventRec(ext, team, pid, None, minute, "red" if red else "yellow"))
                if red and pid in on_pitch:
                    on_pitch.discard(pid)
                    minute_out[pid] = minute
        for pid, mi in minute_in.items():
            if pid not in team_of:  # entrato da un cambio ma assente dalle formazioni
                continue
            b.appearances.append(
                AppearanceRec(ext, pid, team_of[pid], pid in starters, mi, max(mi, minute_out[pid]))
            )
        # eventi di giocatori fuori dalle formazioni (dati incompleti): li togliamo
        known = set(players)
        b.events = [
            e
            for e in b.events
            if e.match_ext != ext
            or (
                (e.player_ext is None or e.player_ext in known)
                and (e.related_player_ext is None or e.related_player_ext in known)
            )
        ]

    # ------------------------------------------------------------------ stagione

    def _season_stats(
        self,
        t: LeagueSeason,
        family: str,
        teams: set[str],
        b: SeasonBundle,
        players: dict[str, PlayerRec],
    ) -> None:
        """Statistiche stagionali, squadra per squadra: il piano Free limita l'elenco
        giocatori a 3 pagine, quindi non si può scaricarlo per intera competizione.

        Per ogni squadra il fornitore restituisce tutte le competizioni (campionato e
        coppe). Si tiene la voce del campionato: stesso ID oppure, per le etichette anomale
        del fornitore (Serie C -> 'Serie C - Supercoppa Lega Finals'), stesso nome di
        famiglia ('Serie C ...'); le coppe ('Coppa Italia Serie C') sono escluse."""

        def league_entry(stats: list[dict[str, Any]], team: str) -> dict[str, Any] | None:
            own = [s for s in stats if str((s.get("team") or {}).get("id")) == team]
            exact = [s for s in own if (s.get("league") or {}).get("id") == t.league_id]
            family_match = [
                s for s in own if str((s.get("league") or {}).get("name", "")).startswith(family)
            ]
            candidates = exact or family_match
            return candidates[0] if candidates else None

        for team in sorted(teams):
            page, pages = 1, 1
            while page <= min(pages, self.max_pages):
                body = self.client.get("players", {"team": team, "season": t.season, "page": page})
                pages = int((body.get("paging") or {}).get("total") or 1)
                if page == 1 and pages > self.max_pages:
                    log.warning(
                        "squadra %s: %d pagine di giocatori, il piano ne consente %d",
                        team,
                        pages,
                        self.max_pages,
                    )
                for row in self._ok(body):
                    s = league_entry(row.get("statistics", []), team)
                    if s is not None:
                        self._add_player(row["player"], s, team, b, players)
                page += 1

    def _add_player(
        self,
        p: dict[str, Any],
        s: dict[str, Any],
        team: str,
        b: SeasonBundle,
        players: dict[str, PlayerRec],
    ) -> None:
        pid = str(p["id"])
        pos = POSITION.get(s["games"].get("position") or "")
        nat = self._country.get(p.get("nationality") or "")
        players[pid] = PlayerRec(
            pid,
            p.get("firstname") or "",
            p.get("lastname") or p.get("name") or "",
            _date((p.get("birth") or {}).get("date")),
            (nat,) if nat else (),
            None,
            _height(p.get("height")),
            pos or (players[pid].primary_position if pid in players else "MF"),
        )
        b.squad.append(SquadEntryRec(pid, team, "unknown"))
        minutes = int(s["games"].get("minutes") or 0)
        if minutes:
            b.stats.append(
                PlayerSeasonStatRec(
                    pid,
                    team,
                    minutes,
                    int(s["games"].get("appearences") or 0),
                    int(s["games"].get("lineups") or 0),
                    _season_values(s),
                )
            )


def _season_values(s: dict[str, Any]) -> dict[str, float]:
    def g(group: str, key: str) -> float | None:
        v = (s.get(group) or {}).get(key)
        return float(v) if v is not None else None

    values = {
        "goals": g("goals", "total") or 0.0,
        "assists": g("goals", "assists") or 0.0,
        "yellow_cards": g("cards", "yellow") or 0.0,
        "red_cards": (g("cards", "red") or 0.0) + (g("cards", "yellowred") or 0.0),
    }
    advanced = {
        "shots_on_target": g("shots", "on"),
        "key_passes": g("passes", "key"),
        "passes": g("passes", "total"),
        "duels": g("duels", "total"),
        "duels_won": g("duels", "won"),
        "dribbles_won": g("dribbles", "success"),
        "saves": g("goals", "saves"),
    }
    tackles, inter = g("tackles", "total"), g("tackles", "interceptions")
    if tackles is not None or inter is not None:
        advanced["tackles_interceptions"] = (tackles or 0.0) + (inter or 0.0)
    # passes.accuracy non è usato: nel fornitore è ambiguo (conteggio o percentuale)
    values |= {k: v for k, v in advanced.items() if v is not None}
    return values
