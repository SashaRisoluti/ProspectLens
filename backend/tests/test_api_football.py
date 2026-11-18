"""ApiFootballProvider su risposte finte con la stessa struttura di API-Football v3."""

from datetime import timedelta
from pathlib import Path
from typing import Any

from prospectlens.providers.api_football import ApiFootballProvider, LeagueSeason
from prospectlens.providers.api_football_client import ApiFootballClient

HOME, AWAY, LEAGUE = 10, 20, 999


def _lineup(team: int, first_id: int) -> dict[str, Any]:
    pos = ["G"] + ["D"] * 4 + ["M"] * 4 + ["F"] * 2
    return {
        "team": {"id": team},
        "startXI": [
            {"player": {"id": first_id + i, "name": f"N. Uno{first_id + i}", "pos": pos[i]}}
            for i in range(11)
        ],
        "substitutes": [{"player": {"id": first_id + 11, "name": "R. Panchina", "pos": "M"}}],
    }


def _event(
    minute: int, team: int, kind: str, detail: str, player: int, assist: int | None = None
) -> dict[str, Any]:
    return {
        "time": {"elapsed": minute, "extra": None},
        "team": {"id": team},
        "player": {"id": player},
        "assist": {"id": assist},
        "type": kind,
        "detail": detail,
    }


def _fixture(fid: int, status: str, home: int | None, away: int | None) -> dict[str, Any]:
    return {
        "fixture": {"id": fid, "date": "2024-09-08T14:30:00+00:00", "status": {"short": status}},
        "league": {"id": LEAGUE, "round": "Regular Season - 1"},
        "teams": {"home": {"id": HOME, "name": "Casa"}, "away": {"id": AWAY, "name": "Ospite"}},
        "goals": {"home": home, "away": away},
    }


RESPONSES: dict[tuple[str, tuple[tuple[str, Any], ...]], dict[str, Any]] = {
    ("leagues", (("country", "Italy"),)): {
        "response": [
            {
                "league": {"id": LEAGUE, "name": "Serie D - Girone B", "type": "League"},
                "seasons": [
                    {
                        "year": 2024,
                        "start": "2024-09-08",
                        "end": "2025-05-04",
                        "coverage": {"injuries": False},
                    }
                ],
            }
        ]
    },
    ("countries", ()): {"response": [{"name": "Italy", "code": "IT"}]},
    ("fixtures", (("league", LEAGUE), ("season", 2024))): {
        "errors": [],
        "response": [_fixture(1, "FT", 2, 1), _fixture(2, "NS", None, None)],
    },
    ("fixtures", (("id", 1),)): {
        "errors": [],
        "response": [
            {
                **_fixture(1, "FT", 2, 1),
                "lineups": [_lineup(HOME, 100), _lineup(AWAY, 200)],
                "events": [
                    _event(10, HOME, "Goal", "Normal Goal", 110, 109),
                    # cambio con convenzione "player = chi entra": il provider deve capirlo
                    _event(60, HOME, "subst", "Substitution 1", 111, 105),
                    _event(70, AWAY, "Card", "Yellow Card", 203),
                    _event(75, AWAY, "Goal", "Penalty", 210),
                    _event(
                        80, AWAY, "Goal", "Own Goal", 202
                    ),  # autogol: vale per la squadra di casa
                    _event(85, AWAY, "Goal", "Missed Penalty", 209),
                ],
            }
        ],
    },
    ("players", (("page", 1), ("season", 2024), ("team", str(AWAY)))): {
        "errors": [],
        "paging": {"current": 1, "total": 1},
        "response": [],
    },
    ("players", (("page", 1), ("season", 2024), ("team", str(HOME)))): {
        "errors": [],
        "paging": {"current": 1, "total": 1},
        "response": [
            {
                "player": {
                    "id": 110,
                    "firstname": "Nome",
                    "lastname": "Punta",
                    "birth": {"date": "2004-01-31"},
                    "nationality": "Italy",
                    "height": "183 cm",
                },
                "statistics": [
                    {
                        "team": {"id": HOME},
                        # il fornitore etichetta a volte con un'altra competizione
                        "league": {"id": 997, "name": "Serie D - Promotion - Play-offs"},
                        "games": {
                            "minutes": 1500,
                            "appearences": 20,
                            "lineups": 15,
                            "position": "Attacker",
                        },
                        "goals": {"total": 7, "assists": 2, "saves": None},
                        "cards": {"yellow": 3, "red": 0, "yellowred": 1},
                        "shots": {"on": None},
                        "passes": {"key": None},
                    },
                    {  # coppa della stessa squadra: va ignorata
                        "team": {"id": HOME},
                        "league": {"id": 891, "name": "Coppa Italia Serie D"},
                        "games": {"minutes": 300, "position": "Attacker"},
                    },
                ],
            }
        ],
    },
}


class FakeClient(ApiFootballClient):
    def __init__(self) -> None:
        super().__init__("finta", Path("/nonexistent"))

    def get(
        self, endpoint: str, params: dict[str, Any] | None = None, ttl: timedelta | None = None
    ) -> dict[str, Any]:
        return RESPONSES[(endpoint, tuple(sorted((params or {}).items())))]


def test_provider_maps_api_football_responses() -> None:
    provider = ApiFootballProvider(FakeClient(), [LeagueSeason(LEAGUE, 2024)], match_details=True)
    [b] = list(provider.bundles())

    assert (b.competition.name, b.competition.level, b.competition.group_code) == (
        "Serie D",
        4,
        "B",
    )
    assert b.season.label == "2024-25"
    assert len(b.matches) == 2 and b.matches[1].home_goals is None
    assert b.data_types == {"results", "lineups", "substitutions", "events", "player_stats_basic"}

    minutes = {AWAY: 0, HOME: 0}
    for a in b.appearances:
        minutes[int(a.team_ext)] += a.minute_out - a.minute_in
    assert minutes == {HOME: 990, AWAY: 990}
    [sub] = [e for e in b.events if e.type == "sub"]
    assert (sub.player_ext, sub.related_player_ext, sub.minute) == ("111", "105", 60)

    goals = [(e.type, e.team_ext, e.player_ext) for e in b.events if "goal" in e.type]
    assert goals == [("goal", "10", "110"), ("goal", "20", "210"), ("own_goal", "10", "202")]

    striker = next(p for p in b.players if p.ext_id == "110")
    assert striker.nationalities == ("IT",) and striker.height_cm == 183
    assert striker.primary_position == "FW"
    [stat] = b.stats
    assert stat.team_ext == str(HOME)
    assert stat.stats == {"goals": 7, "assists": 2, "yellow_cards": 3, "red_cards": 1}
