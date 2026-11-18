"""Verifica quali dati API-Football offre davvero per le competizioni italiane di interesse.

Uso:  make coverage            (oppure: uv run --project backend python scripts/coverage_check.py)
      --budget N   richieste reali massime per questa esecuzione (default 85)
      --refresh    ignora la cache

Per ogni competizione e stagione:
1. copertura *dichiarata* dal fornitore (endpoint /leagues, una richiesta in totale);
2. verifica *a campione*: calendario e risultati, due partite concluse (formazioni, cambi,
   eventi, statistiche per partita), prima pagina delle statistiche stagionali dei giocatori,
   infortuni (solo se dichiarati).
Gli ID delle competizioni si cercano per nome via API, non sono scritti nel codice.
Le risposte sono in cache (data/cache/api-football): se il budget finisce, la prossima
esecuzione riprende da dove si era fermata. Scrive docs/data-coverage.md.
"""

import argparse
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from prospectlens.providers.api_football_client import (
    ApiFootballClient,
    BudgetExhausted,
    api_key_from_env,
)

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache" / "api-football"
REPORT = ROOT / "docs" / "data-coverage.md"
log = logging.getLogger("coverage")

# Competizioni di interesse: (espressione sul nome, nome breve, livello della piramide)
TARGETS = [
    (r"^Serie A$", "Serie A", 1),
    (r"^Serie B$", "Serie B", 2),
    (r"^Serie C - Girone [A-C]$", "Serie C", 3),
    (r"^Serie D - Girone [A-I]$", "Serie D", 4),
    (r"^Campionato Primavera - 1$", "Primavera 1", None),
    (r"^Campionato Primavera - 2$", "Primavera 2", None),
]
DATA_TYPES = [
    "results",
    "lineups",
    "substitutions",
    "events",
    "player_stats_basic",
    "player_stats_advanced",
    "injuries",
    "market_values",
]
HEADERS = {
    "results": "Risultati",
    "lineups": "Formazioni",
    "substitutions": "Cambi",
    "events": "Eventi",
    "player_stats_basic": "Stat. base",
    "player_stats_advanced": "Stat. avanzate",
    "injuries": "Infortuni",
    "market_values": "Valori mercato",
}
FINISHED = {"FT", "AET", "PEN"}
ADVANCED_SEASON = [
    ("shots", "on"),
    ("passes", "key"),
    ("tackles", "total"),
    ("duels", "total"),
    ("dribbles", "success"),
]

# Stati di una cella del report
YES, NO, DECL_YES, DECL_NO, PLAN, NOT_OFFERED = (
    "sì",
    "no",
    "dich. sì",
    "dich. no",
    "piano",
    "n.o.",
)


@dataclass
class Cell:
    league_id: int
    name: str
    short: str
    level: int | None
    season: int
    declared: dict[str, bool]
    status: dict[str, str] = field(default_factory=dict)
    verified: bool = False
    finished: int | None = None
    player_pages: int | None = None
    players_league: int = 0  # ID usato per interrogare i giocatori della competizione
    notes: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.season}-{(self.season + 1) % 100:02d}"


def declared(cov: dict[str, Any]) -> dict[str, bool]:
    fx = cov.get("fixtures", {})
    return {
        "results": bool(fx),
        "lineups": bool(fx.get("lineups")),
        "substitutions": bool(fx.get("events")),
        "events": bool(fx.get("events")),
        "player_stats_basic": bool(cov.get("players")),
        "player_stats_advanced": bool(fx.get("statistics_players")),
        "injuries": bool(cov.get("injuries")),
        "market_values": False,
    }


def discover(client: ApiFootballClient, n_seasons: int) -> list[Cell]:
    body = client.get("leagues", {"country": "Italy"}, ttl=timedelta(days=7))
    this_year = date.today().year
    cells = []
    for item in body["response"]:
        lg = item["league"]
        for pattern, short, level in TARGETS:
            if lg["type"] == "League" and re.match(pattern, lg["name"]):
                for s in item["seasons"]:
                    # solo stagioni concluse, le ultime n
                    if (
                        this_year - n_seasons <= s["year"]
                        and not s["current"]
                        and date.fromisoformat(s["end"]) < date.today()
                    ):
                        cells.append(
                            Cell(
                                lg["id"],
                                lg["name"],
                                short,
                                level,
                                s["year"],
                                declared(s["coverage"]),
                            )
                        )
    cells.sort(key=lambda c: (c.level or 9, c.name, c.season))
    anchor: dict[str, int] = {}
    for c in cells:
        anchor[c.short] = min(anchor.get(c.short, c.league_id), c.league_id)
    for c in cells:
        c.players_league = anchor[c.short]
    return cells


def run(client: ApiFootballClient, cells: list[Cell], plan: list[tuple[int, int]]) -> None:
    """Ordine di verifica, dal più utile al meno utile:
    1. tutte le stagioni del primo girone di ogni competizione;
    2. per ogni altro girone, la stagione più recente accessibile con il piano;
    3. tutto il resto."""
    first: dict[str, int] = {}
    for c in cells:
        first.setdefault(c.short, c.league_id)
    by_league: dict[int, list[Cell]] = {}
    for c in sorted(cells, key=lambda c: -c.season):
        by_league.setdefault(c.league_id, []).append(c)

    def check(c: Cell) -> None:
        if not c.verified:
            log.info("verifico %s %s", c.name, c.label)
            verify(client, c, plan)

    for c in cells:
        if c.league_id == first[c.short]:
            check(c)
    for league_id, seasons in by_league.items():
        if league_id in first.values():
            continue
        for c in seasons:
            check(c)
            if c.status.get("results") != PLAN:
                break
    for c in cells:
        check(c)


def _plan_range(errors: Any) -> tuple[int, int] | None:
    if isinstance(errors, dict) and "plan" in errors:
        m = re.search(r"from (\d{4}) to (\d{4})", str(errors["plan"]))
        if m:
            return int(m.group(1)), int(m.group(2))
        return (0, -1)
    return None


def _non_null_share(rows: list[dict[str, Any]], path: tuple[str, str]) -> float:
    if not rows:
        return 0.0
    ok = sum(1 for r in rows if (r.get(path[0]) or {}).get(path[1]) is not None)
    return ok / len(rows)


def verify(client: ApiFootballClient, c: Cell, plan: list[tuple[int, int]]) -> None:
    if plan and not plan[0][0] <= c.season <= plan[0][1]:
        c.status = {t: PLAN for t in DATA_TYPES}
        c.status["market_values"] = NOT_OFFERED
        c.verified = True
        return
    params = {"league": c.league_id, "season": c.season}
    fixtures = client.get("fixtures", params)
    rng = _plan_range(fixtures.get("errors"))
    if rng is not None:
        plan.append(rng)
        verify(client, c, plan)
        return
    done = [
        f
        for f in fixtures.get("response", [])
        if f["fixture"]["status"]["short"] in FINISHED and f["goals"]["home"] is not None
    ]
    c.finished = len(done)
    st: dict[str, str] = {}  # assegnato solo a verifica completa
    st["results"] = YES if done else NO
    st["market_values"] = NOT_OFFERED
    teams = {f["teams"][side]["id"] for f in done for side in ("home", "away")}
    if done:
        # il piano Free non accetta `ids`: una richiesta per partita
        sample = done[len(done) // 2]
        detail = (client.get("fixtures", {"id": sample["fixture"]["id"]}).get("response") or [{}])[
            0
        ]
        lineups = detail.get("lineups") or []
        events = detail.get("events") or []
        st["lineups"] = (
            YES
            if len(lineups) == 2 and all(len(t.get("startXI") or []) == 11 for t in lineups)
            else NO
        )
        st["substitutions"] = YES if any(e["type"] == "subst" for e in events) else NO
        goals = sum(1 for e in events if e["type"] == "Goal" and e["detail"] != "Missed Penalty")
        score = (sample["goals"]["home"] or 0) + (sample["goals"]["away"] or 0)
        st["events"] = YES if events and goals == score else NO
        if events and goals != score:
            c.notes.append("eventi presenti ma i gol non tornano con il risultato")
        if detail.get("players"):
            c.notes.append("statistiche anche per singola partita")
    # la API restituisce i giocatori dell'intera competizione (tutti i gironi): una sola
    # interrogazione per competizione, poi si filtra per le squadre del girone
    players = client.get("players", {"league": c.players_league, "season": c.season})
    stats = [s for p in players.get("response", []) for s in p.get("statistics", [])]
    rows = [s for s in stats if (s.get("team") or {}).get("id") in teams]
    labels = {(s.get("league") or {}).get("name") for s in rows} - {c.name}
    if labels:
        c.notes.append(f"statistiche giocatori etichettate dal fornitore come {sorted(labels)}")
    c.player_pages = (players.get("paging") or {}).get("total")
    minutes = _non_null_share(rows, ("games", "minutes"))
    # soglia bassa: il campione è la prima pagina (20 giocatori) filtrata per girone
    st["player_stats_basic"] = YES if rows and minutes >= 0.5 else NO
    if rows and minutes < 0.5:
        c.notes.append(f"minuti presenti solo per il {minutes:.0%} dei giocatori del campione")
    adv = max((_non_null_share(rows, k) for k in ADVANCED_SEASON), default=0.0)
    st["player_stats_advanced"] = YES if adv >= 0.5 else NO
    if c.declared["injuries"]:
        inj = client.get("injuries", params)
        st["injuries"] = YES if inj.get("results") else NO
    else:
        st["injuries"] = DECL_NO
    c.status = st
    c.verified = True


def cell_value(c: Cell, t: str) -> str:
    if c.verified and t in c.status:
        return c.status[t]
    if t == "market_values":
        return NOT_OFFERED
    return DECL_YES if c.declared[t] else DECL_NO


def _has(c: Cell, t: str) -> bool:
    return cell_value(c, t) in (YES, DECL_YES)


def lenses(c: Cell) -> str:
    out = []
    if _has(c, "player_stats_basic"):
        out += ["A", "C"]
    if all(_has(c, t) for t in ("lineups", "substitutions", "events")):
        out.append("B")
    tag = "" if c.verified else " (dich.)"
    return ", ".join(sorted(out)) + tag if out else "nessuna"


def estimate_requests(c: Cell) -> int | None:
    """Richieste per importare la stagione: calendario, una richiesta per partita conclusa
    (solo se ci sono formazioni o eventi), pagine dei giocatori (contate solo sul girone
    usato per interrogare l'intera competizione), infortuni."""
    if not c.verified or c.finished is None or c.player_pages is None:
        return None
    details = c.finished if YES in (c.status.get("lineups"), c.status.get("events")) else 0
    pages = c.player_pages if c.players_league == c.league_id else 0
    return 1 + details + pages + int(c.declared["injuries"])


def write_report(
    cells: list[Cell],
    client: ApiFootballClient,
    plan: list[tuple[int, int]],
    status: dict[str, Any],
) -> None:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    sub = (status.get("response") or {}).get("subscription") or {}
    req = (status.get("response") or {}).get("requests") or {}
    lines = [
        "# Copertura dei dati — API-Football",
        "",
        (
            f"Generato da `scripts/coverage_check.py` il {now}. Piano del fornitore: "
            f"**{sub.get('plan', '?')}**, limite {req.get('limit_day', '?')} richieste al giorno."
        ),
        "",
    ]
    if plan and plan[0][1] >= plan[0][0]:
        lines += [
            (
                f"Il piano attuale consente solo le stagioni **{plan[0][0]}-{plan[0][1]}** "
                "(anno di inizio). Le altre sono marcate `piano`."
            ),
            "",
        ]
    verified = sum(c.verified for c in cells)
    lines += [
        (
            f"Celle verificate a campione: {verified} su {len(cells)}. Le altre mostrano la "
            "copertura dichiarata dal fornitore: rilancia lo script per completarle "
            "(la cache evita di ripetere le richieste già fatte)."
        ),
        "",
        (
            "**Legenda:** `sì` verificato presente · `no` verificato assente o vuoto · "
            "`dich. sì`/`dich. no` dichiarato dal fornitore, non ancora verificato · "
            "`piano` non accessibile con il piano attuale · `n.o.` non offerto dal fornitore."
        ),
        "",
        (
            "**Lenti calcolabili** (per la singola stagione): A e C richiedono le statistiche "
            "base (A con almeno 2 stagioni valide, C con almeno 3); B richiede formazioni, "
            "cambi ed eventi."
        ),
        "",
        "| Competizione | ID | Stagione | "
        + " | ".join(HEADERS[t] for t in DATA_TYPES)
        + " | Lenti | Richieste import | Note |",
        "|" + "---|" * (len(DATA_TYPES) + 6),
    ]
    for c in cells:
        est = estimate_requests(c)
        lines.append(
            f"| {c.name} | {c.league_id} | {c.label} | "
            + " | ".join(cell_value(c, t) for t in DATA_TYPES)
            + f" | {lenses(c)} | {est if est is not None else '-'} | {'; '.join(c.notes)} |"
        )
    total = sum(e for c in cells if (e := estimate_requests(c)) is not None)
    lines += [
        "",
        "## Note",
        "",
        (
            "- **Valori di mercato:** API-Football non ha un endpoint per i valori di mercato. "
            "Restano un segnale opzionale da file CSV forniti dal club."
        ),
        (
            "- **Ruolo specifico:** il fornitore indica solo portiere, difensore, centrocampista, "
            "attaccante. Il ruolo specifico (terzino, mezzala...) va dedotto dalla posizione in "
            "formazione, dove c'è, o da un CSV."
        ),
        (
            "- **Dettaglio partite:** formazioni, cambi ed eventi richiedono una richiesta "
            "per partita (il piano Free non accetta il parametro `ids`)."
        ),
        (
            "- **Statistiche dei giocatori:** il fornitore restituisce i giocatori dell'intera "
            "competizione (tutti i gironi) anche se si chiede un solo girone. Lo script "
            "interroga un girone e assegna ogni giocatore al girone della sua squadra."
        ),
        (
            f"- **Stima delle richieste** per importare le stagioni verificate: circa {total} "
            "(con il limite giornaliero attuale servono più giorni; la cache rende l'import "
            "riprendibile)."
        ),
        f"- Richieste reali usate in questa esecuzione: {client.used}.",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=85)
    ap.add_argument("--seasons", type=int, default=5)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    client = ApiFootballClient(api_key_from_env(), CACHE, budget=args.budget, refresh=args.refresh)
    try:
        status = client.get("status", ttl=timedelta(0))
    except BudgetExhausted:
        status = client.get("status")  # ultima risposta in cache
    cells = discover(client, args.seasons)
    plan: list[tuple[int, int]] = []
    try:
        run(client, cells, plan)
    except BudgetExhausted as exc:
        log.warning("verifica interrotta: %s", exc)
    write_report(cells, client, plan, status)
    log.info("scritto %s (%d richieste reali)", REPORT.relative_to(ROOT), client.used)
    return 0


if __name__ == "__main__":
    sys.exit(main())
