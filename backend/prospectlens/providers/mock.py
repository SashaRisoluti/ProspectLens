"""MockProvider: dati sintetici, deterministici (seme fisso), senza chiave API.

Modello del generatore
- Ogni giocatore ha un "Livello vero" latente che segue la curva d'età del suo
  macro-ruolo (config `age_curves`), con un moltiplicatore di crescita individuale.
- Ogni stagione i giocatori vengono distribuiti nei livelli della piramide in base al
  livello percepito (con rumore e inerzia), poi nelle squadre con quote per ruolo.
- Le partite si simulano per segmenti tra un cambio e l'altro: la forza in campo
  decide il tasso di gol (Poisson). Gol, assist, cartellini e cambi sono eventi.
- Le statistiche avanzate dipendono dal livello *relativo* alla propria lega: chi sale
  di categoria peggiora i suoi numeri per 90. È il segnale che il motore usa per
  stimare la forza delle leghe.

Casi costruiti apposta (ext_id con prefisso `case-`): crescita forte, impatto on/off,
costante per tutte le stagioni, una sola stagione, pochi minuti, girone senza
formazioni. I nomi di squadre e giocatori sono inventati; le regole under sono fittizie.
"""

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from typing import Any

import numpy as np

from prospectlens.config import SportConfig
from prospectlens.providers.base import (
    AppearanceRec,
    CompetitionRec,
    DataProvider,
    EventRec,
    InjuryRec,
    MarketValueRec,
    MatchRec,
    PlayerRec,
    PlayerSeasonStatRec,
    SeasonBundle,
    SeasonRec,
    SquadEntryRec,
    TeamRec,
)

MACROS = ("GK", "DF", "MF", "FW")
FORMATION = {"GK": 1, "DF": 4, "MF": 4, "FW": 2}
SQUAD_QUOTA = {"GK": 3, "DF": 8, "MF": 8, "FW": 6}
POSITIONS = {
    "GK": (("GK",), (1.0,)),
    "DF": (("CB", "FB"), (0.5, 0.5)),
    "MF": (("DM", "CM", "AM"), (0.3, 0.45, 0.25)),
    "FW": (("W", "ST"), (0.45, 0.55)),
}
COMP_NAMES = {1: "Serie A", 2: "Serie B", 3: "Serie C", 4: "Serie D"}
GROUP_LETTERS = "ABCDEFGHI"
FIRST_YEAR = 2021

BASIC = frozenset({"results", "lineups", "substitutions", "events", "player_stats_basic"})
DATA_TYPES = {
    1: BASIC | {"player_stats_advanced", "injuries", "market_values"},
    2: BASIC | {"player_stats_advanced", "injuries", "market_values"},
    3: BASIC | {"player_stats_advanced"},
    4: BASIC,
}
NO_LINEUP_TYPES = frozenset({"results", "player_stats_basic"})
UNDER_RULES: dict[int, dict[str, Any]] = {
    3: {"min_under_starters": 1, "under_max_age": 21, "fittizio": True},
    4: {"min_under_starters": 2, "under_max_age": 21, "fittizio": True},
}

GOALS_PER_TEAM_90 = 1.3
HOME_ADV = 0.12
STRENGTH_EFFECT = 0.9
SCORER_W = {"GK": 0.005, "DF": 0.12, "MF": 0.3, "FW": 1.0}
ASSIST_W = {"GK": 0.01, "DF": 0.25, "MF": 0.6, "FW": 0.5}
YELLOW_W = {"GK": 0.3, "DF": 1.3, "MF": 1.2, "FW": 0.8}
ADV_RATES = {  # per 90 minuti, giocatore medio della lega
    "GK": {
        "shots_on_target": 0.0,
        "key_passes": 0.05,
        "passes": 28.0,
        "tackles_interceptions": 0.3,
        "duels": 0.8,
        "dribbles_won": 0.0,
        "saves": 2.8,
    },
    "DF": {
        "shots_on_target": 0.15,
        "key_passes": 0.4,
        "passes": 42.0,
        "tackles_interceptions": 3.6,
        "duels": 9.0,
        "dribbles_won": 0.3,
        "saves": 0.0,
    },
    "MF": {
        "shots_on_target": 0.35,
        "key_passes": 1.0,
        "passes": 46.0,
        "tackles_interceptions": 2.6,
        "duels": 10.0,
        "dribbles_won": 0.9,
        "saves": 0.0,
    },
    "FW": {
        "shots_on_target": 1.0,
        "key_passes": 0.9,
        "passes": 22.0,
        "tackles_interceptions": 0.8,
        "duels": 12.0,
        "dribbles_won": 1.3,
        "saves": 0.0,
    },
}
PASS_ACC = {"GK": 0.68, "DF": 0.80, "MF": 0.82, "FW": 0.72}
DUEL_WIN = {"GK": 0.60, "DF": 0.56, "MF": 0.50, "FW": 0.45}


def _words(text: str) -> tuple[str, ...]:
    """Lista separata da virgole su più righe."""
    return tuple(w.strip() for w in text.split(",") if w.strip())


IT_FIRST = _words("""Alessandro, Andrea, Antonio, Christian, Daniele, Davide, Diego, Edoardo,
    Emanuele, Federico, Filippo, Francesco, Gabriele, Giacomo, Giorgio, Giovanni, Giuseppe,
    Jacopo, Leonardo, Lorenzo, Luca, Manuel, Marco, Mattia, Matteo, Michele, Nicola, Nicolò,
    Pietro, Riccardo, Samuele, Simone, Stefano, Tommaso, Valerio""")
IT_LAST = _words("""Rossi, Russo, Ferrari, Esposito, Bianchi, Romano, Colombo, Ricci, Marino,
    Greco, Bruno, Gallo, Conti, De Luca, Mancini, Costa, Giordano, Rizzo, Lombardi, Moretti,
    Barbieri, Fontana, Santoro, Mariani, Rinaldi, Caruso, Ferrara, Galli, Martini, Leone, Longo,
    Gentile, Martinelli, Vitale, Lombardo, Serra, Coppola, De Santis, D'Angelo, Marchetti,
    Parisi, Villa, Conte, Ferraro, Ferri, Fabbri, Bianco, Marini, Grasso, Valentini, Messina,
    Sala, De Angelis, Gatti, Pellegrini, Palumbo, Sanna, Farina, Rizzi, Monti, Cattaneo""")
FOREIGN_FIRST = _words("""Lucas, Mateo, Thiago, Hugo, Ivan, Luka, Marko, Amadou, Moussa,
    Ibrahim, Kevin, Jonas, Tomás, Rafael, Bruno, Adrian, Mihai, Erik, Kwame, Youssef""")
FOREIGN_LAST = _words("""Silva, Fernández, Diallo, Traoré, Kovač, Novak, Petrović, Mendes,
    Dupont, Martin, Popescu, Mensah, Ndiaye, Benali, Schmidt, Kowalski, Jansen, Pereira,
    Okafor, Haddad""")
FOREIGN_NATS = _words("""AR, BR, FR, ES, AL, RO, SN, NG, CI, GH, MA, HR, RS, DE, PT, GM,
    BE, NL, PL, UY""")
TOWN_A = _words("""Val, Monte, Castel, Borgo, Villa, Rocca, Porto, San, Ponte, Torre, Colle,
    Fonte, Campo, Pieve, Lago""")
TOWN_B = _words("""fiorito, rosso, nuovo, verde, alto, bruno, chiaro, lungo, sereno, antico,
    marino, bello, grande, dorato, stella, vento, sole, quercia, luce""")
CLUB_PREFIX = ("US", "AS", "SS", "FC", "AC", "ASD", "Polisportiva", "Virtus", "Sporting")
INJURY_TYPES = ("muscolare", "distorsione", "contusione", "frattura", "tendinea")


@dataclass(frozen=True)
class MockScale:
    seasons: int
    groups: dict[int, int]  # livello -> numero di gironi
    teams_per_group: dict[int, int]
    no_lineup_groups: int = 1  # ultimi gironi di livello 4 senza formazioni


SCALES = {
    "tiny": MockScale(3, {1: 1, 2: 1, 3: 1, 4: 2}, {1: 6, 2: 6, 3: 6, 4: 6}),
    "demo": MockScale(5, {1: 1, 2: 1, 3: 3, 4: 3}, {1: 20, 2: 20, 3: 20, 4: 18}),
    "full": MockScale(5, {1: 1, 2: 1, 3: 3, 4: 9}, {1: 20, 2: 20, 3: 20, 4: 18}),
}


@dataclass(slots=True, eq=False)
class _P:
    ext_id: str
    first: str
    last: str
    birth: date
    nats: tuple[str, ...]
    foot: str
    height: int
    macro: str
    pos: str
    potential: float
    growth_mult: float
    impact: float
    availability: float
    form_sd: float = 0.12
    entry_season: int = 0
    pin_level: int | None = None
    pin_group: int | None = None
    pin_seasons: frozenset[int] | None = None  # None = tutte
    regular: bool = False  # titolare fisso quando disponibile (casi costruiti)
    level: int | None = None
    team: str | None = None
    idle: int = 0
    cur: float = 0.0

    def age(self, on: date) -> float:
        return (on - self.birth).days / 365.25

    def pinned(self, s: int) -> bool:
        return self.pin_level is not None and (self.pin_seasons is None or s in self.pin_seasons)


@dataclass
class _Acc:
    """Accumulatori stagionali di un giocatore."""

    minutes: int = 0
    apps: int = 0
    starts: int = 0
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def round_robin(teams: list[str]) -> list[list[tuple[str, str]]]:
    """Andata e ritorno, metodo del cerchio. Numero di squadre pari."""
    t = list(teams)
    n = len(t)
    rounds = []
    for r in range(n - 1):
        pairs = [(t[i], t[n - 1 - i]) for i in range(n // 2)]
        rounds.append([(b, a) for a, b in pairs] if r % 2 else pairs)
        t = [t[0], t[-1], *t[1:-1]]
    return rounds + [[(b, a) for a, b in rd] for rd in rounds]


class MockProvider(DataProvider):
    source = "mock"
    description = "Dati sintetici generati dal MockProvider (dimostrativi, non reali)"
    license_note = "Dati inventati: nessuna licenza necessaria"

    def __init__(self, cfg: SportConfig, scale: str = "demo", seed: int = 42) -> None:
        self.cfg = cfg
        self.scale = SCALES[scale]
        self.seed = seed

    def bundles(self) -> Iterator[SeasonBundle]:
        world = _World(self.cfg, self.scale, self.seed)
        for s in range(self.scale.seasons):
            yield from world.play_season(s)


class _World:
    def __init__(self, cfg: SportConfig, scale: MockScale, seed: int) -> None:
        self.rng = np.random.default_rng(seed)
        self.curves = cfg.age_curves
        self.tier_mean = cfg.league_strength_defaults
        self.scale = scale
        self.levels = sorted(scale.groups)
        self.groups: dict[int, list[list[str]]] = {}
        self.team_names: dict[str, str] = {}
        self._build_teams()
        self.capacity = {
            (lvl, m): len(self._teams_of(lvl)) * SQUAD_QUOTA[m]
            for lvl in self.levels
            for m in MACROS
        }
        self.pool: list[_P] = []
        self._n = 0
        start0 = self.season_start(0)
        for m in MACROS:
            n = int(1.15 * sum(self.capacity[(lvl, m)] for lvl in self.levels))
            for _ in range(n):
                self.pool.append(self._new_player(m, start0, self.rng.uniform(17, 34)))
        self.pool += self._cases(start0)

    # ------------------------------------------------------------------ costruzione

    def _teams_of(self, level: int) -> list[str]:
        return [t for g in self.groups[level] for t in g]

    def _build_teams(self) -> None:
        towns = [a + b for a in TOWN_A for b in TOWN_B]
        self.rng.shuffle(towns)
        i = 0
        for lvl in self.levels:
            self.groups[lvl] = []
            for g in range(self.scale.groups[lvl]):
                ids = []
                for k in range(self.scale.teams_per_group[lvl]):
                    ext = f"t-{lvl}{GROUP_LETTERS[g]}-{k:02d}"
                    self.team_names[ext] = f"{self.rng.choice(CLUB_PREFIX)} {towns[i]}"
                    i += 1
                    ids.append(ext)
                self.groups[lvl].append(ids)

    @staticmethod
    def season_start(s: int) -> date:
        return date(FIRST_YEAR + s, 8, 15)

    def _new_player(self, macro: str, on: date, age: float, **kw: Any) -> _P:
        r = self.rng
        self._n += 1
        roll = r.random()
        if roll < 0.82:
            nats: tuple[str, ...] = ("IT",)
        elif roll < 0.87:
            nats = ("IT", str(r.choice(FOREIGN_NATS)))
        else:
            nats = (str(r.choice(FOREIGN_NATS)),)
        it = nats[0] == "IT"
        positions, weights = POSITIONS[macro]
        height_mu = {"GK": 188, "DF": 183, "MF": 177, "FW": 179}[macro]
        params: dict[str, Any] = {
            "ext_id": f"p{self._n:06d}",
            "first": str(r.choice(IT_FIRST if it else FOREIGN_FIRST)),
            "last": str(r.choice(IT_LAST if it else FOREIGN_LAST)),
            "birth": on - timedelta(days=int(age * 365.25)),
            "nats": nats,
            "foot": str(r.choice(["right", "left", "both"], p=[0.75, 0.22, 0.03])),
            "height": int(r.normal(height_mu, 5.5)),
            "macro": macro,
            "pos": str(r.choice(positions, p=weights)),
            "potential": float(r.normal(-0.3, 0.7)),
            "growth_mult": float(r.lognormal(0.0, 0.3)),
            "impact": float(r.normal(0.0, 0.02)),
            "availability": float(np.clip(r.beta(14, 1.5), 0.5, 0.99)),
        }
        params.update(kw)
        return _P(**params)

    def _cases(self, start0: date) -> list[_P]:
        last = self.scale.seasons - 1
        no_lineup_group = self.scale.groups[4] - 1
        mk = self._new_player
        cases = [
            mk(
                "FW",
                start0,
                18.3,
                ext_id="case-growth",
                pos="ST",
                potential=1.6,
                growth_mult=1.8,
                availability=0.97,
                form_sd=0.05,
                pin_level=4,
                pin_group=0,
                pin_seasons=frozenset({0}),
                regular=True,
            ),
            mk(
                "MF",
                start0,
                24.0,
                ext_id="case-impact",
                pos="CM",
                potential=0.0,
                growth_mult=1.0,
                impact=0.35,
                availability=0.8,
                pin_level=3,
                pin_group=0,
                regular=True,
            ),
            mk(
                "DF",
                start0,
                23.0,
                ext_id="case-steady",
                pos="CB",
                potential=0.1,
                growth_mult=0.15,
                availability=0.98,
                form_sd=0.03,
                pin_level=2,
                regular=True,
            ),
            mk(
                "FW",
                self.season_start(last),
                19.0,
                ext_id="case-oneseason",
                pos="W",
                potential=0.3,
                entry_season=last,
                pin_level=4,
                pin_group=0,
                regular=True,
            ),
            mk(
                "MF",
                start0,
                20.0,
                ext_id="case-lowminutes",
                pos="DM",
                potential=-1.8,
                availability=0.25,
                pin_level=3,
                pin_group=0,
            ),
            mk(
                "DF",
                start0,
                21.0,
                ext_id="case-nolineup",
                pos="FB",
                potential=-0.6,
                availability=0.95,
                pin_level=4,
                pin_group=no_lineup_group,
                regular=True,
            ),
        ]
        return cases

    def level_at(self, p: _P, age: float) -> float:
        c = self.curves[p.macro]
        return (
            p.potential
            - c.growth_per_year * p.growth_mult * max(c.peak_age - age, 0.0)
            - c.decline_per_year * max(age - c.peak_age, 0.0)
        )

    # ------------------------------------------------------------------ stagione

    def play_season(self, s: int) -> Iterator[SeasonBundle]:
        start = self.season_start(s)
        self._renew_pool(s, start)
        self._assign(s, start)
        season = SeasonRec(
            f"{start.year}-{(start.year + 1) % 100:02d}", start, date(start.year + 1, 6, 30)
        )
        level_mean = {
            lvl: float(np.mean([p.cur for p in self.pool if p.level == lvl])) for lvl in self.levels
        }
        for lvl in self.levels:
            for g, teams in enumerate(self.groups[lvl]):
                yield self._simulate_group(s, lvl, g, teams, season, level_mean[lvl])

    def _renew_pool(self, s: int, start: date) -> None:
        r = self.rng
        self.pool = [
            p
            for p in self.pool
            if p.ext_id.startswith("case-") or (p.age(start) <= 35 and p.idle < 2)
        ]
        for m in MACROS:
            cap = sum(self.capacity[(lvl, m)] for lvl in self.levels)
            active = sum(1 for p in self.pool if p.macro == m)
            n_new = max(int(1.15 * cap) - active, int(0.10 * cap)) if s else 0
            for _ in range(n_new):
                self.pool.append(
                    self._new_player(
                        m, start, r.uniform(17, 18.9), potential=float(r.normal(-0.2, 0.75))
                    )
                )
        for p in self.pool:
            p.cur = self.level_at(p, p.age(start)) + float(r.normal(0.0, p.form_sd))

    def _assign(self, s: int, start: date) -> None:
        """Livello della piramide per classifica di livello percepito, poi squadra."""
        r = self.rng
        prev = {id(p): (p.level, p.team) for p in self.pool}
        tier_mean = self.tier_mean
        for p in self.pool:
            p.level, p.team = None, None
        for m in MACROS:
            cands = [p for p in self.pool if p.macro == m and p.entry_season <= s]
            pinned = [p for p in cands if p.pinned(s)]
            free = [p for p in cands if not p.pinned(s)]

            def perceived(p: _P) -> float:
                prev_level = prev[id(p)][0]
                base = p.cur if prev_level is None else 0.7 * p.cur + 0.3 * tier_mean[prev_level]
                return base + float(r.normal(0.0, 0.2))

            free.sort(key=perceived, reverse=True)
            for p in pinned:
                p.level = p.pin_level
            i = 0
            for lvl in self.levels:
                n = self.capacity[(lvl, m)] - sum(1 for p in pinned if p.pin_level == lvl)
                for p in free[i : i + n]:
                    p.level = lvl
                i += n
            for p in cands:
                p.idle = 0 if p.level else p.idle + 1
            for lvl in self.levels:
                self._fill_teams(lvl, m, [p for p in cands if p.level == lvl], prev, s)

    def _fill_teams(
        self,
        lvl: int,
        m: str,
        members: list[_P],
        prev: dict[int, tuple[int | None, str | None]],
        s: int,
    ) -> None:
        r = self.rng
        slots = {t: SQUAD_QUOTA[m] for t in self._teams_of(lvl)}
        for p in members:
            if p.pinned(s) and p.pin_group is not None:
                options = [t for t in self.groups[lvl][p.pin_group] if slots[t] > 0]
                p.team = str(r.choice(options))
                slots[p.team] -= 1
        for p in members:
            old_level, old_team = prev[id(p)]
            if (
                p.team is None
                and old_level == lvl
                and old_team in slots
                and slots[old_team] > 0
                and r.random() < 0.8
            ):
                p.team = old_team
                slots[old_team] -= 1
        open_slots = [t for t, n in slots.items() for _ in range(n)]
        r.shuffle(open_slots)
        rest = [p for p in members if p.team is None]
        for p, t in zip(rest, open_slots, strict=False):
            p.team = t

    # ------------------------------------------------------------------ partite

    def _simulate_group(
        self, s: int, lvl: int, g: int, teams: list[str], season: SeasonRec, level_mean: float
    ) -> SeasonBundle:
        r = self.rng
        n_groups = self.scale.groups[lvl]
        has_lineups = not (lvl == 4 and g >= n_groups - self.scale.no_lineup_groups)
        letter = GROUP_LETTERS[g] if n_groups > 1 else None
        comp = CompetitionRec(f"mock-{lvl}{GROUP_LETTERS[g]}", COMP_NAMES[lvl], "IT", lvl, letter)
        data_types = DATA_TYPES[lvl] if has_lineups else NO_LINEUP_TYPES
        under = UNDER_RULES.get(lvl, {})
        rosters = {t: [p for p in self.pool if p.team == t] for t in teams}
        players = [p for t in teams for p in rosters[t]]
        b = SeasonBundle(comp, season, data_types, dict(under))
        b.teams = [TeamRec(t, self.team_names[t], "IT") for t in teams]
        b.players = [
            PlayerRec(p.ext_id, p.first, p.last, p.birth, p.nats, p.foot, p.height, p.pos)
            for p in players
        ]
        b.squad = [self._squad_entry(p, lvl, season) for p in players]
        acc: dict[str, _Acc] = defaultdict(_Acc)
        for md, pairs in enumerate(round_robin(teams), start=1):
            kickoff = datetime.combine(
                season.start + timedelta(days=7 * md), datetime.min.time(), UTC
            ) + timedelta(hours=14)
            for home, away in pairs:
                ext = f"m-{s}-{comp.ext_id}-{md:02d}-{home}"
                hg, ag = self._match(
                    ext, home, away, rosters, under, season.start, acc, b, has_lineups
                )
                b.matches.append(MatchRec(ext, md, kickoff, home, away, hg, ag))
        advanced = "player_stats_advanced" in data_types
        for p in players:
            a = acc[p.ext_id]
            if a.apps == 0:
                continue
            stats: dict[str, float] = {
                k: float(a.counts[k]) for k in ("goals", "assists", "yellow_cards", "red_cards")
            }
            if advanced:
                stats |= self._advanced(p, a.minutes, p.cur - level_mean)
            b.stats.append(
                PlayerSeasonStatRec(p.ext_id, str(p.team), a.minutes, a.apps, a.starts, stats)
            )
        if "market_values" in data_types:
            b.market_values = [
                MarketValueRec(
                    p.ext_id, self._market_value(p, season.start), season.start + timedelta(days=45)
                )
                for p in players
                if r.random() < 0.7
            ]
        if "injuries" in data_types:
            for p in players:
                if p.availability < 0.85:
                    st = season.start + timedelta(days=int(r.integers(10, 250)))
                    b.injuries.append(
                        InjuryRec(
                            p.ext_id,
                            st,
                            st + timedelta(days=int(r.integers(7, 60))),
                            str(r.choice(INJURY_TYPES)),
                        )
                    )
        return b

    def _squad_entry(self, p: _P, lvl: int, season: SeasonRec) -> SquadEntryRec:
        r = self.rng
        if lvl >= 3 and p.age(season.start) <= 22 and r.random() < 0.15:
            owner = str(r.choice(self._teams_of(lvl - 2)))
            return SquadEntryRec(p.ext_id, str(p.team), "loan", owner, season.end)
        until = date(season.end.year + int(r.integers(0, 4)), 6, 30) if r.random() < 0.6 else None
        return SquadEntryRec(p.ext_id, str(p.team), "owned", None, until)

    def _lineup(
        self, roster: list[_P], under: dict[str, Any], on: date
    ) -> tuple[list[_P], list[_P]]:
        r = self.rng
        avail = [p for p in roster if r.random() < p.availability]
        if len(avail) < 14:
            avail = list(roster)
        score = {id(p): p.cur + float(r.normal(0.0, 0.3)) + 5.0 * p.regular for p in avail}
        avail.sort(key=lambda p: score[id(p)], reverse=True)
        starters: list[_P] = []
        for m, n in FORMATION.items():
            starters += [p for p in avail if p.macro == m][:n]
        for p in avail:  # reparto incompleto: completa con i migliori rimasti
            if len(starters) >= 11:
                break
            if p not in starters:
                starters.append(p)
        k = int(under.get("min_under_starters", 0))
        max_age = float(under.get("under_max_age", 0))

        def is_under(p: _P) -> bool:
            return p.age(on) < max_age + 1

        while sum(map(is_under, starters)) < k:
            subs_in = [p for p in avail if p not in starters and is_under(p) and p.macro != "GK"]
            outs = [p for p in starters if not is_under(p) and p.macro != "GK"]
            if not subs_in or not outs:
                break
            new = subs_in[0]
            same = [p for p in outs if p.macro == new.macro] or outs
            starters[starters.index(min(same, key=lambda p: score[id(p)]))] = new
        bench = [p for p in avail if p not in starters][:9]
        return starters, bench

    def _match(
        self,
        ext: str,
        home: str,
        away: str,
        rosters: dict[str, list[_P]],
        under: dict[str, Any],
        on: date,
        acc: dict[str, _Acc],
        b: SeasonBundle,
        has_lineups: bool,
    ) -> tuple[int, int]:
        r = self.rng
        field_: dict[str, list[_P]] = {}
        minute_in: dict[str, int] = {}
        minute_out: dict[str, int] = {}
        starters_ids: set[str] = set()
        subs: list[tuple[int, str, _P, _P]] = []
        for t in (home, away):
            starters, bench = self._lineup(rosters[t], under, on)
            field_[t] = list(starters)
            for p in starters:
                minute_in[p.ext_id], minute_out[p.ext_id] = 0, 90
                starters_ids.add(p.ext_id)
            n_subs = min(int(r.choice([2, 3, 4, 5], p=[0.1, 0.25, 0.35, 0.3])), len(bench))
            on_pitch = [p for p in starters if p.macro != "GK"]
            for minute in sorted(int(x) for x in r.integers(40, 89, n_subs)):
                out = on_pitch.pop(int(r.integers(len(on_pitch))))
                cands = [p for p in bench if p.macro == out.macro] or bench
                inn = cands[0]
                bench.remove(inn)
                on_pitch.append(inn)
                subs.append((minute, t, out, inn))
        subs.sort(key=lambda x: x[0])
        goals = {home: 0, away: 0}
        bounds = sorted({0, 90, *(x[0] for x in subs)})
        si = 0
        for a, z in pairwise(bounds):
            while si < len(subs) and subs[si][0] == a:
                minute, t, out, inn = subs[si]
                field_[t][field_[t].index(out)] = inn
                minute_out[out.ext_id], minute_in[inn.ext_id], minute_out[inn.ext_id] = (
                    minute,
                    minute,
                    90,
                )
                if has_lineups:
                    b.events.append(EventRec(ext, t, inn.ext_id, out.ext_id, minute, "sub"))
                si += 1
            strength = {
                t: float(np.mean([p.cur for p in field_[t]])) + sum(p.impact for p in field_[t])
                for t in (home, away)
            }
            for t, opp in ((home, away), (away, home)):
                lam = GOALS_PER_TEAM_90 * np.exp(
                    STRENGTH_EFFECT * (strength[t] - strength[opp])
                    + (HOME_ADV if t == home else -HOME_ADV)
                )
                for _ in range(int(r.poisson(lam * (z - a) / 90))):
                    goals[t] += 1
                    minute = int(r.integers(a, z)) + 1
                    self._goal(ext, t, opp, field_, minute, acc, b, has_lineups)
        for t in (home, away):
            for p in rosters[t]:
                if p.ext_id not in minute_in:
                    continue
                mins = minute_out[p.ext_id] - minute_in[p.ext_id]
                a_ = acc[p.ext_id]
                a_.apps += 1
                a_.minutes += mins
                a_.starts += p.ext_id in starters_ids
                if has_lineups:
                    b.appearances.append(
                        AppearanceRec(
                            ext,
                            p.ext_id,
                            t,
                            p.ext_id in starters_ids,
                            minute_in[p.ext_id],
                            minute_out[p.ext_id],
                        )
                    )
                for kind, prob in (("yellow", 0.11 * YELLOW_W[p.macro]), ("red", 0.006)):
                    if r.random() < prob * mins / 90:
                        a_.counts[f"{kind}_cards"] += 1
                        if has_lineups:
                            mn = int(r.integers(minute_in[p.ext_id], minute_out[p.ext_id] + 1))
                            b.events.append(EventRec(ext, t, p.ext_id, None, max(mn, 1), kind))
        return goals[home], goals[away]

    def _goal(
        self,
        ext: str,
        t: str,
        opp: str,
        field_: dict[str, list[_P]],
        minute: int,
        acc: dict[str, _Acc],
        b: SeasonBundle,
        has_lineups: bool,
    ) -> None:
        r = self.rng
        if r.random() < 0.03:  # autogol: lo segna un avversario, conta per `t`
            scorer = field_[opp][int(r.integers(len(field_[opp])))]
            if has_lineups:
                b.events.append(EventRec(ext, t, scorer.ext_id, None, minute, "own_goal"))
            return
        ps = field_[t]
        w = np.array([SCORER_W[p.macro] * np.exp(0.8 * p.cur) for p in ps])
        scorer = ps[int(r.choice(len(ps), p=w / w.sum()))]
        acc[scorer.ext_id].counts["goals"] += 1
        assister = None
        if r.random() < 0.72:
            mates = [p for p in ps if p is not scorer]
            w = np.array([ASSIST_W[p.macro] * np.exp(0.6 * p.cur) for p in mates])
            assister = mates[int(r.choice(len(mates), p=w / w.sum()))]
            acc[assister.ext_id].counts["assists"] += 1
        if has_lineups:
            b.events.append(
                EventRec(
                    ext, t, scorer.ext_id, assister.ext_id if assister else None, minute, "goal"
                )
            )

    def _advanced(self, p: _P, minutes: int, rel: float) -> dict[str, float]:
        r = self.rng
        k = minutes / 90 * float(np.exp(0.35 * rel))
        out = {s: float(r.poisson(rate * k)) for s, rate in ADV_RATES[p.macro].items()}
        pass_p = float(np.clip(PASS_ACC[p.macro] + 0.04 * rel, 0.3, 0.97))
        duel_p = float(np.clip(DUEL_WIN[p.macro] + 0.04 * rel, 0.2, 0.9))
        out["passes_completed"] = float(r.binomial(int(out["passes"]), pass_p))
        out["duels_won"] = float(r.binomial(int(out["duels"]), duel_p))
        return out

    def _market_value(self, p: _P, on: date) -> int:
        age = p.age(on)
        v = np.exp(13.5 + 1.2 * p.cur - 0.05 * max(age - 24, 0) + 0.5 * self.rng.normal())
        return max(25_000, int(round(v / 25_000) * 25_000))
