# Motore delle metriche

Come ProspectLens trasforma le statistiche grezze in Livello, Indice talento e punteggi
delle tre lenti. Codice in `backend/prospectlens/engine/`, parametri in
`config/sports/football.yaml` (sezioni `metrics`, `thresholds`, `age_curves`,
`league_strength_defaults`, `goals`, `engine`). Nessun nome di metrica è scritto nel
codice: per un altro sport basta un altro file YAML.

Notazione: una *riga* è un giocatore in una squadra, competizione (girone) e stagione.
Un *gruppo* è l'insieme delle righe con stessa competizione, stagione e macro-ruolo.
La *popolazione di riferimento* di un gruppo sono le righe con almeno
`min_minutes_sample` minuti (default 450).

## 1. Per 90 minuti e shrinkage

Per ogni metrica `per90` applicabile al ruolo e disponibile nella competizione:

```
grezzo  = totale / (minuti / 90)
media   = Σ totale / Σ (minuti / 90)            sulla popolazione di riferimento
stima   = (totale + K × media) / (minuti / 90 + K)
```

K è `shrinkage_k` della metrica (default `default_shrinkage_k` = 10, in partite intere).
Con pochi minuti la stima resta vicina alla media del ruolo nella lega; con molti minuti
coincide quasi con il dato grezzo. Si mostrano sempre entrambi.

Per le metriche `ratio` (es. precisione passaggi) K è in tentativi:
`stima = (riusciti + K × media) / (tentati + K)`.

Sotto `min_minutes_sample` il giocatore resta visibile ma l'affidabilità è bassa.

Un dato che vale 0 per tutti i giocatori di una competizione e stagione (almeno 30
righe) è considerato non rilevato dal fornitore e trattato come mancante. Esempio: gli
assist della Serie C su API-Football.

**Minuti e partite della squadra** si contano sulla sola stagione regolare (partite con
giornata). Se le statistiche dei giocatori includono i playoff, il totale della squadra
sale fino a quanto giocato dai suoi giocatori, così quote minuti e presenze non superano 1.

## 2. Percentili e Livello nella lega

- **Percentile** di una metrica: posizione della stima nel gruppo (0-100, ranghi medi per
  i pareggi), con il segno della metrica (per le ammonizioni, meno è meglio).
- **z-score** della metrica nel gruppo (media 0, deviazione standard 1 sulla popolazione di
  riferimento).
- **Livello nella lega** (`z_within`): media pesata (`weight` della metrica) degli z-score
  disponibili, poi ristandardizzata nel gruppo. Se le metriche disponibili sono meno di
  `min_metrics_for_level` (default 2) il Livello non viene calcolato. Esempio: un
  portiere con le sole statistiche base ha una sola metrica, le ammonizioni.

### Portieri

Nelle serie minori il fornitore non dà parate, tiri subiti o gol subiti dei portieri:
solo minuti, presenze e cartellini (verificato sulla Serie C, novembre 2026). Per i
portieri il motore usa:

| Metrica | Da dove | Tipo di segnale |
|---|---|---|
| Gol subiti in campo per 90 | formazioni, cambi ed eventi: gol avversari tra ingresso e uscita | prestazione (dipende molto dalla difesa) |
| Titolarità | minuti / minuti della squadra (dai risultati) | uso da parte dell'allenatore |
| Gol evitati per 90 | solo da CSV (es. Wyscout, gol attesi contro − gol subiti) | prestazione |
| Parate per 90 | statistiche avanzate (Serie A e B) | prestazione |
| Ammonizioni | statistiche base | disciplina |

Ogni metrica ha un tipo di segnale (`signal` nel YAML). **Se il Livello di un giocatore
contiene meno di `min_performance_metrics` metriche di prestazione (default 2),
l'affidabilità è bassa.** Due casi tipici: un portiere di Serie C senza dettaglio delle
partite (nessuna metrica di prestazione) e un giocatore di movimento di Serie C sul piano
Free, che ha solo i gol. `data_used` elenca le metriche usate (`level_metrics`). Per valutare davvero un portiere di serie
minore servono il dettaglio delle partite (gol subiti in campo) o un export CSV con i
gol evitati.

## 3. Forza delle competizioni

Ogni competizione/girone ha un coefficiente `off` in unità di Livello. Per ogni giocatore
che passa dalla competizione c0 (stagione t) alla c1 (stagione t+1):

```
off[c1] − off[c0] ≈ z_within(t) − z_within(t+1) + crescita_attesa(età, ruolo)
```

Si risolve ai minimi quadrati pesati (peso = minuti minimi tra le due stagioni / 900),
aggiungendo per ogni competizione un'equazione-prior `off[c] = default(livello)` con
peso `league_strength_prior_weight`. Il prior fissa la scala (Serie B = 0) e copre i
gironi senza passaggi. I coefficienti fissati dall'amministratore (`source = admin`)
non vengono ricalcolati.

**Livello** = `z_within + off[competizione]`, confrontabile tra leghe e stagioni. Se un
giocatore gioca in più competizioni nella stessa stagione, conta la media pesata per i
minuti.

*Limite noto:* chi sale di categoria spesso ha avuto una stagione sopra il suo vero
valore (regressione verso la media). Così il divario tra leghe può risultare un po'
sovrastimato.

## 4. Età, curve d'età, regole under

- **Curva d'età** per macro-ruolo: quadratica `Livello ~ età + età²` pesata per minuti
  sulle stagioni valide. Sotto `age_curve_min_rows` (default 100) si usa la curva di
  default del YAML (`age_curves`), centrata sulla media del ruolo. Ne derivano il
  *livello atteso* e la *crescita attesa* (derivata) per età e ruolo.
- **Indice talento** (0-100): percentile, tra le stagioni valide dello stesso macro-ruolo
  e stagione, del residuo `Livello − livello atteso per l'età`. Indica il talento per
  l'età. Il **Livello** resta separato (decisione della domanda 9 del piano).
- **Età relativa**: età meno età media del macro-ruolo nella competizione e stagione.
- **Quota minuti rispetto ai coetanei** (regole under): `quota = minuti / minuti della
  squadra`; `quota / mediana delle quote dei nati nello stesso anno, nella stessa
  competizione e stagione`. Un under che gioca perché il regolamento lo impone viene
  confrontato con gli altri under, non con tutta la rosa.
- **Precocità** (18-21 anni): percentile della quota minuti tra i nati nello stesso anno
  in tutte le competizioni della stagione.

## 5. Lente A — Crescita rapida

Per la stagione T si usano le stagioni valide (minuti ≥ `valid_season_minutes`, default
900) nelle ultime `window_seasons` (default 4). Ne servono almeno `min_valid_seasons`
(2), altrimenti: *storico insufficiente*.

1. Pendenza del Livello sugli anni, minimi quadrati pesati per minuti; errore standard
   con una varianza residua minima `noise_floor_sd²`.
2. Shrinkage bayesiano verso la crescita attesa g(età, ruolo):
   `pendenza* = (p/se² + g/τ²) / (1/se² + 1/τ²)`, τ = `prior_sd`.
3. **Crescita oltre l'atteso** = `pendenza* − g`.
4. **Salto di contesto**: somma degli aumenti di coefficiente di lega (> 0,05) tra
   stagioni consecutive in cui il Livello non cala più di `jump_tolerance`.
5. `grezzo = crescita oltre l'atteso + jump_weight × salto`; intervallo
   `grezzo ± 1,645 × se*`.
6. **Punteggio** 0-100: percentile del grezzo tra i giocatori con lo stesso macro-ruolo
   nella stessa stagione; gli estremi dell'intervallo si convertono con la stessa scala.

Affidabilità: bassa con 2 stagioni, media con 3 o più, alta con 3 o più e statistiche
avanzate. Il segnale del valore di mercato (opzionale) non è ancora usato.

## 6. Lente B — Impatto sui risultati

Disponibile solo se la competizione ha formazioni, cambi ed eventi; altrimenti *non
disponibile*. Ogni partita è divisa in **segmenti** tra un cambio e l'altro.

- **On/off differenza reti per 90** = (gol fatti − subiti per 90 con il giocatore in
  campo) − (lo stesso senza di lui, nelle partite della sua squadra).
- **On/off punti a partita**: punti pesati per la quota di minuti giocata in ogni
  partita, contro quelli pesati per la quota non giocata.
- **Shrinkage** degli on/off verso 0: `× h / (h + K)`, con `h = n_on·n_off / (n_on + n_off)`
  in partite intere e K = `onoff_shrinkage_k`.
- **Impatto corretto (ridge)**, per squadra e stagione: per ogni segmento,
  `differenza reti per 90 ~ Σ compagni in campo + forza avversario + casa`, pesato per la
  durata, con penalità `ridge_alpha`. Il coefficiente del giocatore è il suo effetto al
  netto dei compagni. La forza dell'avversario è la sua differenza reti media nella
  stagione. Intervallo 5-95% con `bootstrap` ricampionamenti delle partite.
- **Decisività**: per ogni gol, punti che la squadra avrebbe perso senza quel gol (1-0 → 2,
  2-2 → 1, 3-0 → 0); l'assist vale `assist_weight` volte tanto.
- **Punteggio**: percentile dell'impatto corretto (macro-ruolo, stagione). Accanto si
  mostra la posizione dentro la squadra (`rank_in_team`), che è il confronto più affidabile.

Affidabilità: bassa sotto `valid_season_minutes` in campo o `min_off_minutes` fuori;
media sopra; alta con il doppio dei minuti in campo e il triplo di quelli fuori. È la
lente più rumorosa: la stabilità tra stagioni sarà misurata nella Fase 6.

## 7. Lente C — Longevità

Soglie dal YAML: medio = 50° percentile del Livello nel macro-ruolo e stagione (tutte le
leghe), alto = 70°. Una stagione conta "sopra soglia" se è valida e sopra il 50°.

- **Stagioni consecutive sopra soglia** (anche sopra il 70°); una stagione mancante
  interrompe la serie.
- **Costanza**: deviazione standard del Livello tra le stagioni valide.
- **Disponibilità**: media di presenze / partite della squadra (proxy degli infortuni).
- **Probabilità di restare sopra soglia** nelle prossime N stagioni (`horizon_seasons`,
  default 3): regressione logistica a tempo discreto. Ogni riga (giocatore, stagione t)
  predice se in t+1 sarà sopra soglia, da età, età², percentile, sopra soglia ora,
  serie, costanza, disponibilità, ruolo. La probabilità su N stagioni è il prodotto dei
  passi, aggiornando età e serie. **Censura:** se il giocatore non compare in t+1 la riga
  è esclusa dall'addestramento, non conta né come successo né come fallimento. Lo stesso
  vale per l'ultima stagione disponibile. Se invece compare con pochi minuti, conta come
  "non sopra soglia".
- **Punteggio** = 100 × probabilità; intervallo 5-95% con bootstrap sui giocatori.

Affidabilità: bassa con meno di 3 stagioni osservate, media con 3, alta con 4 o più e
disponibilità ≥ 70%. Accanto al punteggio si mostra sempre il numero di stagioni osservate.

*Limiti noti:* chi esce dai dati spesso è sceso di categoria, quindi l'esclusione può
gonfiare le probabilità. In questa fase il modello si addestra su tutte le stagioni
disponibili; la validazione temporale (addestra sul passato, verifica sul futuro)
arriva nella Fase 6.

## 8. Affidabilità e dati usati

Ogni punteggio salva `reliability` (alta, media, bassa) e `data_used`: tipi di dato della
competizione, numero di metriche nel Livello, fonte, data dell'import, minuti. L'interfaccia
mostra sempre entrambi.

## Esecuzione

```sh
docker compose exec api prospectlens compute   # manuale
```

Il calcolo parte anche alla fine di `seed`, `import-api` e `import-csv`. Il container
`worker` lo esegue ogni giorno all'ora `PIPELINE_HOUR` (UTC, default 5). Sui dati demo
(5 stagioni, circa 19.000 giocatori-stagione) richiede circa 2 minuti.
