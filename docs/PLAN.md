# ProspectLens — Piano di lavoro (Fase 0)

Stato: **bozza da approvare**. Nessun codice viene scritto prima dell'approvazione.

Questo documento contiene le scelte tecniche, il piano per fasi, i rischi e le domande
aperte, ognuna con una proposta. Dove scrivo "da verificare", il dato non lo conosco con
certezza e non lo assumo.

---

## 1. Principi guida

1. **Prima i dati, poi i modelli.** La copertura reale di Serie C e Serie D decide quali
   lenti esistono. `coverage_check.py` gira prima di qualsiasi lavoro sull'import reale.
2. **Una sola fonte di verità per la configurazione.** Sport, ruoli, metriche, lenti,
   soglie e testi di aiuto stanno in `config/sports/football.yaml`. La pipeline li copia
   nel database (`metric_definition`, `goal_definition`) e l'API li espone al frontend.
   Nessun nome di metrica è scritto nel codice del motore.
3. **Tutto precalcolato.** L'API legge solo punteggi già pronti. La ricerca usa una vista
   materializzata con indici.
4. **Onestà sui numeri.** Ogni punteggio porta con sé affidabilità, dati usati, fonte e
   data. Se una lente non è calcolabile, l'interfaccia lo dice e non mostra un numero.
5. **Poche dipendenze.** Ogni libreria in più va giustificata. Dove una funzione si scrive
   in poche righe con numpy/scikit-learn, non aggiungo una libreria (vedi §3.4).

---

## 2. Struttura del repository

```
ProspectLens/
├── backend/                     # Python 3.12, un solo pacchetto
│   ├── pyproject.toml           # dipendenze, Ruff, mypy, pytest
│   ├── alembic/                 # migrazioni
│   └── prospectlens/
│       ├── api/                 # FastAPI: router, schemi Pydantic, auth
│       ├── db/                  # modelli SQLAlchemy, sessione, vista di ricerca
│       ├── config/              # caricamento e validazione YAML (Pydantic)
│       ├── providers/           # DataProvider, ApiFootball, CsvImport, Mock
│       ├── engine/              # motore delle metriche (funzioni pure su DataFrame)
│       ├── models/              # salto di categoria, lente C, backtest
│       ├── pipeline/            # job CLI: import, compute, refresh, alerts
│       └── reports/             # template HTML + WeasyPrint
├── web/                         # Next.js + TypeScript (strict)
│   ├── src/app/                 # App Router, pagine
│   ├── src/components/          # ui/ (shadcn), charts/, help/, lens/
│   ├── src/lib/api/             # client e tipi GENERATI da OpenAPI
│   ├── src/styles/tokens.css    # token di design (unico file)
│   └── messages/it.json         # testi next-intl
├── config/sports/football.yaml
├── scripts/coverage_check.py
├── docs/                        # PLAN, architecture, data-coverage, metrics,
│                                # model-report, privacy, deploy
├── docker-compose.yml
├── docker-compose.prod.yml      # + Caddy, HTTPS automatico
├── Makefile
├── .env.example
└── .github/                     # CI, Dependabot
```

### Comandi (Makefile)

| Comando | Effetto |
|---|---|
| `make up` | `docker compose up` (db, api, worker, web) |
| `make seed` | genera i dati mock e lancia la pipeline completa |
| `make test` | pytest + vitest |
| `make e2e` | Playwright + axe contro lo stack con dati mock |
| `make types` | rigenera `openapi.json` e i tipi TypeScript |
| `make lint` | Ruff, mypy, ESLint, Prettier |
| `make demo-reset` | ripristina i dati demo |

---

## 3. Scelte tecniche

### 3.1 Backend e pipeline

| Area | Scelta | Motivo |
|---|---|---|
| Gestione dipendenze Python | `uv` | veloce, lockfile, un solo strumento |
| Dataframe | **pandas** | compatibile senza conversioni con scikit-learn e LightGBM |
| ORM / migrazioni | SQLAlchemy 2 + Alembic | richiesti |
| Config | YAML validato con modelli Pydantic | un errore nel YAML ferma l'avvio con un messaggio chiaro |
| HTTP verso il fornitore | `httpx` + cache su disco (risposte JSON grezze) + retry con backoff | rispetto dei limiti, import incrementali, riproducibilità |
| Job | CLI unica (`prospectlens pipeline import|compute|refresh|alerts|all`) | eseguibile a mano, da cron o dal container worker |
| Pianificazione | il container worker esegue la pipeline a un orario configurato (`PIPELINE_CRON_HOUR`) con un ciclo minimo, senza scheduler esterni | nessuna dipendenza in più; in produzione si può usare il cron del server |
| Auth | sessioni in DB con cookie httpOnly, password con `argon2-cffi`, ruoli `platform_admin`, `org_admin`, `scout` | semplice, sicuro, nessun servizio esterno |
| Rate limiting | limitatore in memoria sul login e sugli inviti | basta per una sola istanza; documentato come limite |
| PDF | Jinja2 + WeasyPrint; grafici come SVG generati in Python (barre e radar sono poligoni) | nessuna libreria di grafici lato server |

**Immagini Docker:** un solo `Dockerfile` per il backend, usato da due servizi (`api` e
`worker`) con comandi diversi; uno per `web`; Postgres ufficiale. Sono container separati
come richiesto, ma senza duplicare l'immagine Python.

### 3.2 Database e ricerca

- PostgreSQL 16. Tutte le entità della specifica, con `sport_id` su `competition`,
  `player`, `metric_definition` e sulle definizioni delle lenti.
- Tabelle aggiunte rispetto alla specifica: `competition_rule` (regole under per
  competizione e stagione), `league_strength` (coefficienti stimati e di default),
  `goal_definition` (copia delle lenti dal YAML), `session`, `invite`, `feedback`,
  `attachment`, `data_source` (fonte e data di ogni import).
- **Vista materializzata `player_search`**: una riga per giocatore e stagione, con tutti
  i campi filtrabili, i punteggi delle tre lenti, affidabilità e stagioni osservate.
  Indici B-tree sui filtri principali e sulle colonne di ordinamento delle lenti.
  `REFRESH MATERIALIZED VIEW CONCURRENTLY` alla fine della pipeline.
- **Lente personalizzata:** la somma pesata dei tre punteggi si calcola in SQL al momento
  della query, sulle colonne precalcolate. Su decine di migliaia di righe resta molto
  sotto il secondo. Verifico con un test di carico sui dati mock.

### 3.3 Frontend

| Area | Scelta |
|---|---|
| Framework | Next.js (App Router, ultima versione stabile al momento della Fase 5), TypeScript `strict`, nessun file `.js` scritto a mano |
| UI | Tailwind + shadcn/ui (Radix) + Lucide, token in `src/styles/tokens.css` |
| Tabelle | TanStack Table, paginazione e ordinamento lato server |
| Grafici | Recharts |
| Testi | next-intl, `messages/it.json`. I testi di metriche e lenti arrivano dall'API (YAML) |
| Contratto | `openapi-typescript` + `openapi-fetch`. La CI rigenera i tipi e fallisce se `git diff` non è vuoto |
| Stato nei filtri | parametri dell'URL (lente, pesi, filtri), quindi link condivisibili e salvabili |
| Tour guidato | `driver.js` (libreria piccola, MIT), stato "tour visto" salvato sull'utente |
| Test | Vitest (componenti), Playwright + `@axe-core/playwright` (flusso e accessibilità) |

### 3.4 Analisi e modelli

| Componente | Scelta | Nota |
|---|---|---|
| Shrinkage, percentili, per 90 | numpy/pandas | formule della specifica, K da YAML |
| Forza delle leghe | minimi quadrati sui giocatori che cambiano competizione, con prior verso i coefficienti di default (ridge verso il prior) | ancoraggio: Serie B = 0 |
| Pendenza lente A | minimi quadrati pesati per minuti + shrinkage verso la crescita attesa per età e ruolo | |
| Ridge lente B | `sklearn.linear_model.Ridge` su segmenti di partita (stint tra un cambio e l'altro) | intervallo di incertezza con bootstrap sulle partite |
| Sopravvivenza lente C | **modello a tempo discreto con regressione logistica** (scikit-learn) | gestisce la censura in modo corretto e rende **inutile `lifelines`**: una dipendenza in meno |
| Salto di categoria | regressione logistica regolarizzata vs LightGBM, validazione temporale | |
| Spiegazioni | coefficienti standardizzati (logistica) o `pred_contrib=True` di LightGBM (valori SHAP nativi) | **niente pacchetto `shap`** |

---

## 4. Definizioni del motore (sintesi)

Le formule complete andranno in `docs/metrics.md` nella Fase 3. Qui la sintesi, per
verificare che abbiamo capito la stessa cosa.

**Livello e Indice talento.** Due grandezze distinte (deciso, domanda 9):
- **Livello**: media pesata per ruolo degli z-score delle metriche per 90 con shrinkage,
  calcolati nella stessa competizione, stagione e macro-ruolo, più l'offset di forza
  della lega. È confrontabile tra leghe e stagioni. Lo usano le lenti A e C.
- **Indice talento (0-100)**: percentile del Livello rispetto al livello atteso per età
  e ruolo. È il numero mostrato in interfaccia come "talento per la sua età".

**Lente A — Crescita rapida.** Pendenza del Livello su stagioni consecutive valide
(minuti ≥ soglia), con shrinkage verso la crescita attesa per età e ruolo. Il segnale è
il residuo (pendenza − crescita attesa). Bonus "salto di contesto" se il giocatore
sale di forza lega senza perdere livello. Con dati per partita, lo stesso calcolo gira
anche su mezze stagioni (andata e ritorno). Sotto 2 osservazioni valide: "storico
insufficiente", nessun punteggio.

**Lente B — Impatto.**
- On/off punti a partita: per ogni partita, quota di minuti giocati; punti medi pesati
  per la quota "in campo" contro la quota "fuori".
- On/off differenza reti per 90: dai minuti dei gol e dai minuti di ingresso e uscita.
- Ridge: righe = segmenti di partita, regressori = compagni in campo, controlli = forza
  dell'avversario e casa/trasferta, peso = durata del segmento. Il confronto principale
  è dentro la squadra.
- Decisività: punti che la squadra avrebbe perso togliendo quel gol (o assist, con peso
  configurabile).
- Disattivata se la competizione non ha formazioni e sostituzioni.

**Lente C — Longevità.** Stagioni consecutive sopra soglia, costanza (deviazione
standard del Livello), disponibilità (quota di partite giocate). Probabilità di restare
sopra soglia per N stagioni = prodotto delle probabilità stagione per stagione stimate
dal modello a tempo discreto. Chi esce dai dati smette di contribuire: è censurato, non
è un fallimento e non viene scartato.

**Salto di categoria.** Obiettivo: ≥ 900 minuti (configurabile) in una competizione di
livello superiore entro due stagioni. Chi sparisce dai dati conta come esito negativo,
come richiesto, e il report riporta quanti casi sono.

**Regole under.** La quota minuti di un giocatore si confronta con la mediana dei nati
nello stesso anno, nella stessa competizione e stagione. Le regole (età e obblighi per
competizione e stagione) le inserisce l'amministratore. **Non le invento:** nei dati mock
userò valori fittizi marcati come tali.

---

## 5. Dati

### 5.1 Fonti

- **ApiFootballProvider.** Il fornitore espone un endpoint `/leagues` con un oggetto
  `coverage` per stagione (formazioni, eventi, statistiche dei giocatori, infortuni,
  ecc.). `coverage_check.py` lo legge, poi verifica a campione alcune partite e
  alcune rose, perché il flag dichiarato non garantisce che i dati ci siano davvero.
  Gli ID competizione si cercano per nome e paese via API.
- **CsvImportProvider.** Mappatura delle colonne in un file YAML per formato (per
  esempio `config/csv/wyscout.yaml`). Valore di mercato e infortuni sono letti solo se
  presenti nel file.
- **MockProvider.** Generatore con seme fisso e un "talento vero" latente per ogni
  giocatore, che segue curve d'età per ruolo. Così le lenti e i backtest hanno un segnale
  da trovare.
  - 5 stagioni; Serie A (solo rose e minuti, serve a misurare il salto di categoria dalla
    B), Serie B, Serie C (3 gironi), Serie D (9 gironi).
  - Partite con risultato, formazioni, sostituzioni, eventi gol e assist.
  - Casi costruiti apposta: forte crescita, alto impatto on/off, costante per 5 stagioni,
    una sola stagione, pochi minuti, competizione senza formazioni (per vedere la lente B
    disattivata).
  - Dimensione regolabile: piccola per i test, completa per la demo.

### 5.2 Volumi della demo (stima sui dati mock)

Circa 280 squadre, circa 7.000 giocatori per stagione, circa 4.500 partite per stagione,
circa 1 milione di presenze in 5 stagioni. Postgres li gestisce senza problemi; lo
verifico in Fase 1.

---

## 6. Piano per fasi

Ogni fase si chiude con test verdi, un commit e un riepilogo (fatto, mancante, rischi).

| Fase | Contenuto | Uscita verificabile |
|---|---|---|
| 1 | Repo, Docker, Postgres, modelli e migrazioni, YAML + validazione, `DataProvider`, `MockProvider`, `make seed`, CI di base (lint + pytest) | `docker compose up` e `make seed` popolano il DB; test sul generatore |
| 2 | `coverage_check.py` → `docs/data-coverage.md` (colonna "lenti calcolabili"), `ApiFootballProvider` con cache e backoff, `CsvImportProvider` | report di copertura reale (serve la tua chiave API, anche gratuita) |
| 3 | Motore: per 90, shrinkage, percentili, forza leghe, under, età e curve, on/off, ridge, decisività, traiettoria, longevità, affidabilità; `docs/metrics.md` | unit test per ogni funzione elencata nella specifica |
| 4 | API: auth e organizzazioni, ricerca con lente e filtri, profilo, shortlist, note, confronto, config/glossario; vista `player_search`; generazione tipi TS in CI | test API; ricerca < 1 s sui dati mock completi |
| 5 | Frontend: token e componenti base, legende e tooltip dal YAML, selettore lenti, ricerca, profilo, shortlist con annulla, confronto, glossario, tour; Vitest + Playwright + axe | test E2E del flusso "terzino in crescita in Serie D → shortlist" |
| 6 | Modello salto di categoria, backtest delle tre lenti, `docs/model-report.md` | report con AUC, Brier, calibrazione, top-20, stabilità lente B |
| 7 | Ricerche salvate, avvisi in piattaforma, PDF, area amministratore | test API e E2E dedicati |
| 8 | Immagini di produzione, `docker-compose.prod.yml` con Caddy, `docs/deploy.md` (costi verificati), modalità demo, feedback in app, `docs/privacy.md`, Dependabot, protocollo del test di usabilità | stack prod avviabile su un server pulito |

**Nota sul report dei modelli (Fase 6).** Sui dati mock i backtest verificano solo che la
pipeline funzioni: il segnale l'ho messo io nel generatore. Il report lo dirà in modo
esplicito. Una validazione vera richiede dati reali di più stagioni.

### Rimandato o escluso (dichiarato)

- Email per gli avvisi: fase successiva, come da specifica.
- Foto dei giocatori: solo avatar con iniziali.
- Basket: nessun codice, solo un modello dati e una configurazione che lo permettono.
- Telefono: profilo e shortlist in sola lettura; ricerca ottimizzata per desktop e tablet.

---

## 7. Rischi principali

| Rischio | Impatto | Mitigazione |
|---|---|---|
| Copertura di Serie D (e in parte Serie C) povera: niente formazioni o statistiche avanzate | lente B assente in D; Livello basato solo su gol, assist, minuti, cartellini | Fase 2 prima di tutto; lente disattivata con messaggio; import CSV dai club |
| Limiti del piano gratuito del fornitore (ultimo limite noto: 100 richieste al giorno; da riconfermare) | import di 5 stagioni di C e D impossibile o lentissimo | cache, import incrementale; stima delle richieste nel report di copertura; **nessun piano a pagamento senza tuo ok** |
| Licenza dei dati: mostrare dati del fornitore a terzi | blocco della demo con dati reali | demo solo con dati mock finché la licenza non è verificata |
| Campioni piccoli: on/off e ridge molto rumorosi | lente B poco stabile | shrinkage forte, intervalli, affidabilità bassa dichiarata, test di stabilità nel report |
| Storico breve con tetto 25 anni | lente C poco informativa | domanda 1 |
| Regole under reali non disponibili come dato | correzione under incompleta | inserimento da area amministratore |
| WeasyPrint richiede librerie di sistema | immagine più pesante | installate solo nell'immagine backend |
| Ampiezza del progetto | tempi lunghi | fasi con uscite verificabili; priorità al flusso principale |

---

## 8. Domande aperte

Per ognuna c'è una proposta. Basta rispondere "ok" o indicare la modifica.

**1. Tetto di età per la lente C.**
Proposta: 25 anni per le lenti A e B; **28 anni** per la lente C. In ogni caso importo i
giocatori di tutte le età, perché servono per forza delle leghe, curve d'età e
regressione dei compagni. Il tetto vale solo come filtro di ricerca.

**2. Esito della crescita (lente A).**
Proposta: il punteggio si basa sulla **crescita del Livello**, perché è disponibile per
tutti. Il **salto di categoria** si usa nel backtest come seconda verifica. Il valore di
mercato resta solo un segnale opzionale, **spento di default**, attivo solo con almeno 2
rilevazioni datate da fonte lecita.

**3. Target della lente B e dati disponibili.**
Proposta: **differenza reti per 90** come target della ridge, perché i gol sono eventi
più frequenti dei punti e danno meno rumore. Punti a partita on/off come indicatore
secondario, più facile da leggere. La disponibilità di formazioni e sostituzioni per
Serie C e D la misura `coverage_check.py`: oggi non lo so e non lo assumo.

**4. Soglie della lente C.**
Proposta: medio ≥ 50° percentile, alto ≥ 70° percentile del Livello nel ruolo. Stagione
valida con almeno **900 minuti**. Orizzonte N = 3 stagioni.

**5. Lente senza dati sufficienti.**
Proposta, regola mista:
- **disattivata** se manca un tipo di dato necessario (lente B senza formazioni; lente A
  con meno di 2 stagioni valide);
- **mostrata con affidabilità bassa** se i dati ci sono ma sono pochi (minuti sotto
  soglia, pochi cambi in rosa).

**6. Hosting e budget.** ✅ **Deciso:** prima versione **gratuita**; in seguito pochi
euro al mese.
Conseguenze sul progetto:
- Stesso `docker-compose.prod.yml` per gratuito e a pagamento: si cambia solo il
  server, non il codice.
- Postgres dentro lo stack (nessun database gestito a pagamento).
- Dati demo in versione ridotta (meno gironi di Serie D), per stare nella RAM di
  un'istanza gratuita. Obiettivo: stack completo sotto 1 GB di RAM, misurato in Fase 8.
- In `docs/deploy.md` (Fase 8) confronto le opzioni gratuite: VM "always free" di un
  cloud provider, free tier di un PaaS, PC locale esposto con un tunnel gratuito.
  Limiti e condizioni dei piani gratuiti cambiano spesso: li verifico sulle pagine
  ufficiali al momento e riporto la fonte e la data. **Non attivo nulla, nemmeno
  gratis, senza tuo ok** (alcuni richiedono una carta di credito per la verifica).

**7. Dati per i tester.**
Proposta: **solo dati mock** finché non abbiamo verificato per iscritto che la licenza del
fornitore consente di mostrare i dati a terzi, e finché `docs/privacy.md` non è completo.

**8. Stile.**
Proposta: tema **chiaro di default** (proiettore in riunione), scuro disponibile. Palette
neutra grigio ardesia con un accento **verde petrolio**. Scala dei percentili su una
sola tinta (blu, dal chiaro allo scuro), leggibile anche dai daltonici. Affidabilità
sempre con icona e testo. Nessun logo: il nome "ProspectLens" in testo. Hai un marchio o
colori da usare?

**9. (nuova) Indice talento corretto per età o no?** ✅ **Deciso:** due grandezze
separate, come in §4.
La specifica chiede un Indice talento "corretto per lega ed età", ma la lente C usa i
percentili dell'Indice talento per decidere se un giocatore è "medio" o "alto". Un
indice corretto per età farebbe sembrare "alto" un diciottenne nella media della lega. Il **Livello** (corretto per lega, non per età)
serve alle soglie della lente C e alla pendenza della lente A. L'**Indice talento**
(corretto anche per età) è il numero mostrato in interfaccia.

**10. (nuova) Piano del fornitore dati.**
Proposta: eseguo `coverage_check.py` con il **piano gratuito**. Se il report mostra che
serve un piano a pagamento per importare C e D, ti porto la stima di richieste e costo
e decidi tu. Ti serve una chiave API (anche gratuita) per la Fase 2.

**11. (nuova) Competizioni da importare.**
Proposta: **Serie A e Serie B** (servono per misurare il salto di categoria e la forza
delle leghe), **Serie C e Serie D** (il bacino di scouting), **Primavera 1** solo se il
report di copertura mostra dati utilizzabili. Campionati esteri minori: dopo l'MVP.

**12. (nuova) Riferimenti all'assistente nei commit.**
Il `.gitignore` esclude `CLAUDE.md` e gli altri file degli assistenti di codice. Vuoi
anche che i messaggi di commit non contengano la riga `Co-Authored-By` che cita
l'assistente?
