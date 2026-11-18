from collections import Counter, defaultdict

from prospectlens.config import SportConfig
from prospectlens.providers.base import SeasonBundle
from prospectlens.providers.mock import SQUAD_QUOTA, MockProvider


def _seasons_of(bundles: list[SeasonBundle], ext: str) -> list[SeasonBundle]:
    return [b for b in bundles if any(p.ext_id == ext for p in b.players)]


def _minutes(b: SeasonBundle, ext: str) -> int:
    return sum(s.minutes for s in b.stats if s.player_ext == ext)


def _regular(b: SeasonBundle, ext: str) -> bool:
    """Ha giocato almeno metà dei minuti della stagione della sua squadra."""
    return _minutes(b, ext) >= 0.5 * 2 * (len(b.teams) - 1) * 90


def test_deterministic(cfg: SportConfig, tiny_bundles: list[SeasonBundle]) -> None:
    again = list(MockProvider(cfg, "tiny", seed=7).bundles())
    scores = [[(m.home_goals, m.away_goals) for m in b.matches] for b in tiny_bundles]
    assert scores == [[(m.home_goals, m.away_goals) for m in b.matches] for b in again]


def test_structure(tiny_bundles: list[SeasonBundle]) -> None:
    labels = sorted({b.season.label for b in tiny_bundles})
    assert labels == ["2021-22", "2022-23", "2023-24"]
    for b in tiny_bundles:
        n = len(b.teams)
        assert len(b.matches) == n * (n - 1)  # andata e ritorno
        squads = Counter(s.team_ext for s in b.squad)
        assert set(squads.values()) == {sum(SQUAD_QUOTA.values())}


def test_lineup_minutes_and_goals_are_consistent(tiny_bundles: list[SeasonBundle]) -> None:
    for b in tiny_bundles:
        if "lineups" not in b.data_types:
            continue
        minutes: dict[tuple[str, str], int] = defaultdict(int)
        starters: Counter[tuple[str, str]] = Counter()
        for a in b.appearances:
            minutes[(a.match_ext, a.team_ext)] += a.minute_out - a.minute_in
            starters[(a.match_ext, a.team_ext)] += a.started
        goals: Counter[tuple[str, str]] = Counter(
            (e.match_ext, e.team_ext) for e in b.events if e.type in ("goal", "own_goal")
        )
        for m in b.matches:
            for team, g in ((m.home_ext, m.home_goals), (m.away_ext, m.away_goals)):
                assert minutes[(m.ext_id, team)] == 11 * 90
                assert starters[(m.ext_id, team)] == 11
                assert goals[(m.ext_id, team)] == g
        # i gol nelle statistiche stagionali coincidono con gli eventi
        ev_goals = Counter(e.player_ext for e in b.events if e.type == "goal")
        for s in b.stats:
            assert s.stats["goals"] == ev_goals[s.player_ext]


def test_group_without_lineups(tiny_bundles: list[SeasonBundle]) -> None:
    no_lineups = [b for b in tiny_bundles if "lineups" not in b.data_types]
    assert no_lineups, "serve almeno un girone senza formazioni"
    for b in no_lineups:
        assert not b.appearances and not b.events
        assert b.stats and all(m.home_goals is not None for m in b.matches)
        assert "shots_on_target" not in b.stats[0].stats


def test_constructed_cases(tiny_bundles: list[SeasonBundle]) -> None:
    n_seasons = len({b.season.label for b in tiny_bundles})
    growth = _seasons_of(tiny_bundles, "case-growth")
    assert len(growth) == n_seasons
    assert growth[-1].competition.level < growth[0].competition.level  # sale di categoria
    assert all(_regular(b, "case-growth") for b in growth)

    impact = _seasons_of(tiny_bundles, "case-impact")
    assert len(impact) == n_seasons and all("lineups" in b.data_types for b in impact)
    assert all(_regular(b, "case-impact") for b in impact)

    steady = _seasons_of(tiny_bundles, "case-steady")
    assert len(steady) == n_seasons and all(_regular(b, "case-steady") for b in steady)

    assert len(_seasons_of(tiny_bundles, "case-oneseason")) == 1
    assert all(
        _minutes(b, "case-lowminutes") < 450 for b in _seasons_of(tiny_bundles, "case-lowminutes")
    )
    assert all("lineups" not in b.data_types for b in _seasons_of(tiny_bundles, "case-nolineup"))
