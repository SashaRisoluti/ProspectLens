# Copertura dei dati — API-Football

Generato da `scripts/coverage_check.py` il 2026-11-18 21:02 UTC. Piano del fornitore: **Free**, limite 100 richieste al giorno.

Il piano attuale consente solo le stagioni **2022-2024** (anno di inizio). Le altre sono marcate `piano`.

Celle verificate a campione: 52 su 80. Le altre mostrano la copertura dichiarata dal fornitore: rilancia lo script per completarle (la cache evita di ripetere le richieste già fatte).

**Legenda:** `sì` verificato presente · `no` verificato assente o vuoto · `dich. sì`/`dich. no` dichiarato dal fornitore, non ancora verificato · `piano` non accessibile con il piano attuale · `n.o.` non offerto dal fornitore.

**Lenti calcolabili** (per la singola stagione): A e C richiedono le statistiche base (A con almeno 2 stagioni valide, C con almeno 3); B richiede formazioni, cambi ed eventi.

| Competizione | ID | Stagione | Risultati | Formazioni | Cambi | Eventi | Stat. base | Stat. avanzate | Infortuni | Valori mercato | Lenti | Richieste import (base + dettaglio partite) | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Serie A | 135 | 2021-22 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie A | 135 | 2022-23 | sì | sì | sì | sì | sì | sì | sì | n.o. | A, B, C | 62 + 381 | statistiche anche per singola partita |
| Serie A | 135 | 2023-24 | sì | sì | sì | sì | sì | sì | sì | n.o. | A, B, C | 62 + 380 | statistiche anche per singola partita |
| Serie A | 135 | 2024-25 | sì | sì | sì | sì | sì | sì | sì | n.o. | A, B, C | 62 + 380 | statistiche anche per singola partita |
| Serie A | 135 | 2025-26 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie B | 136 | 2021-22 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie B | 136 | 2022-23 | sì | sì | sì | sì | sì | sì | dich. no | n.o. | A, B, C | 61 + 390 | statistiche anche per singola partita |
| Serie B | 136 | 2023-24 | sì | sì | sì | sì | sì | sì | dich. no | n.o. | A, B, C | 61 + 390 | statistiche anche per singola partita |
| Serie B | 136 | 2024-25 | sì | sì | sì | sì | sì | sì | dich. no | n.o. | A, B, C | 61 + 389 | statistiche anche per singola partita |
| Serie B | 136 | 2025-26 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie C - Girone A | 138 | 2021-22 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie C - Girone A | 138 | 2022-23 | sì | sì | sì | sì | sì | no | dich. no | n.o. | A, B, C | 61 + 380 | statistiche giocatori etichettate dal fornitore come ['Serie C - Supercoppa Lega Finals'] |
| Serie C - Girone A | 138 | 2023-24 | sì | sì | sì | sì | sì | no | dich. no | n.o. | A, B, C | 61 + 380 | statistiche giocatori etichettate dal fornitore come ['Serie C - Supercoppa Lega Finals'] |
| Serie C - Girone A | 138 | 2024-25 | sì | sì | sì | sì | sì | no | dich. no | n.o. | A, B, C | 61 + 380 | statistiche giocatori etichettate dal fornitore come ['Serie C - Supercoppa Lega Finals'] |
| Serie C - Girone A | 138 | 2025-26 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie C - Girone B | 942 | 2021-22 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie C - Girone B | 942 | 2022-23 | sì | sì | sì | sì | sì | no | dich. no | n.o. | A, B, C | 61 + 380 | statistiche giocatori etichettate dal fornitore come ['Serie C - Supercoppa Lega Finals'] |
| Serie C - Girone B | 942 | 2023-24 | dich. sì | dich. sì | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, B, C (dich.) | - |  |
| Serie C - Girone B | 942 | 2024-25 | sì | sì | sì | sì | sì | no | dich. no | n.o. | A, B, C | 61 + 380 | statistiche giocatori etichettate dal fornitore come ['Serie C - Supercoppa Lega Finals'] |
| Serie C - Girone B | 942 | 2025-26 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie C - Girone C | 943 | 2021-22 | dich. sì | dich. sì | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, B, C (dich.) | - |  |
| Serie C - Girone C | 943 | 2022-23 | dich. sì | dich. sì | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, B, C (dich.) | - |  |
| Serie C - Girone C | 943 | 2023-24 | dich. sì | dich. sì | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, B, C (dich.) | - |  |
| Serie C - Girone C | 943 | 2024-25 | sì | sì | sì | sì | sì | no | dich. no | n.o. | A, B, C | 61 + 362 | statistiche giocatori etichettate dal fornitore come ['Serie C - Supercoppa Lega Finals'] |
| Serie C - Girone C | 943 | 2025-26 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie D - Girone A | 426 | 2021-22 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie D - Girone A | 426 | 2022-23 | sì | no | no | no | no | no | dich. no | n.o. | nessuna | 61 + 0 | eventi presenti ma i gol non tornano con il risultato |
| Serie D - Girone A | 426 | 2023-24 | sì | no | no | sì | no | no | dich. no | n.o. | nessuna | 61 + 380 | statistiche giocatori etichettate dal fornitore come ['Serie D - Championship Round']; minuti presenti solo per il 0% dei giocatori del campione |
| Serie D - Girone A | 426 | 2024-25 | sì | no | no | sì | no | no | dich. no | n.o. | nessuna | 61 + 369 | statistiche giocatori etichettate dal fornitore come ['Serie D - Promotion - Play-offs']; minuti presenti solo per il 0% dei giocatori del campione |
| Serie D - Girone A | 426 | 2025-26 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie D - Girone B | 427 | 2021-22 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone B | 427 | 2022-23 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone B | 427 | 2023-24 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone B | 427 | 2024-25 | sì | no | no | sì | no | no | dich. no | n.o. | nessuna | 61 + 380 |  |
| Serie D - Girone B | 427 | 2025-26 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie D - Girone C | 428 | 2021-22 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone C | 428 | 2022-23 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone C | 428 | 2023-24 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone C | 428 | 2024-25 | sì | no | no | sì | no | no | dich. no | n.o. | nessuna | 61 + 380 | statistiche giocatori etichettate dal fornitore come ['Serie D - Promotion - Play-offs']; minuti presenti solo per il 0% dei giocatori del campione |
| Serie D - Girone C | 428 | 2025-26 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie D - Girone D | 429 | 2021-22 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone D | 429 | 2022-23 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone D | 429 | 2023-24 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone D | 429 | 2024-25 | sì | no | no | sì | no | no | dich. no | n.o. | nessuna | 55 + 306 | statistiche giocatori etichettate dal fornitore come ['Serie D - Promotion - Play-offs']; minuti presenti solo per il 0% dei giocatori del campione |
| Serie D - Girone D | 429 | 2025-26 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie D - Girone E | 430 | 2021-22 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone E | 430 | 2022-23 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone E | 430 | 2023-24 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone E | 430 | 2024-25 | sì | no | no | sì | no | no | dich. no | n.o. | nessuna | 55 + 306 | statistiche giocatori etichettate dal fornitore come ['Serie D - Promotion - Play-offs']; minuti presenti solo per il 0% dei giocatori del campione |
| Serie D - Girone E | 430 | 2025-26 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie D - Girone F | 431 | 2021-22 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone F | 431 | 2022-23 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone F | 431 | 2023-24 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone F | 431 | 2024-25 | sì | no | no | sì | no | no | dich. no | n.o. | nessuna | 55 + 306 | statistiche giocatori etichettate dal fornitore come ['Serie D - Promotion - Play-offs']; minuti presenti solo per il 0% dei giocatori del campione |
| Serie D - Girone F | 431 | 2025-26 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie D - Girone G | 432 | 2021-22 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone G | 432 | 2022-23 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone G | 432 | 2023-24 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone G | 432 | 2024-25 | sì | no | no | sì | no | no | dich. no | n.o. | nessuna | 55 + 306 | statistiche giocatori etichettate dal fornitore come ['Serie D - Promotion - Play-offs']; minuti presenti solo per il 0% dei giocatori del campione |
| Serie D - Girone G | 432 | 2025-26 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie D - Girone H | 433 | 2021-22 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone H | 433 | 2022-23 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone H | 433 | 2023-24 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone H | 433 | 2024-25 | sì | no | no | sì | no | no | dich. no | n.o. | nessuna | 55 + 306 | statistiche giocatori etichettate dal fornitore come ['Serie D - Promotion - Play-offs']; minuti presenti solo per il 0% dei giocatori del campione |
| Serie D - Girone H | 433 | 2025-26 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Serie D - Girone I | 434 | 2021-22 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone I | 434 | 2022-23 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone I | 434 | 2023-24 | dich. sì | dich. no | dich. sì | dich. sì | dich. sì | dich. no | dich. no | n.o. | A, C (dich.) | - |  |
| Serie D - Girone I | 434 | 2024-25 | sì | no | no | no | no | no | dich. no | n.o. | nessuna | 55 + 0 | statistiche giocatori etichettate dal fornitore come ['Serie D - Promotion - Play-offs']; minuti presenti solo per il 0% dei giocatori del campione |
| Serie D - Girone I | 434 | 2025-26 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Campionato Primavera - 1 | 705 | 2021-22 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Campionato Primavera - 1 | 705 | 2022-23 | sì | sì | sì | sì | sì | no | dich. no | n.o. | A, B, C | 55 + 311 |  |
| Campionato Primavera - 1 | 705 | 2023-24 | sì | sì | sì | sì | sì | no | dich. no | n.o. | A, B, C | 55 + 311 |  |
| Campionato Primavera - 1 | 705 | 2024-25 | sì | sì | sì | sì | sì | no | dich. no | n.o. | A, B, C | 61 + 386 |  |
| Campionato Primavera - 1 | 705 | 2025-26 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Campionato Primavera - 2 | 706 | 2021-22 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |
| Campionato Primavera - 2 | 706 | 2022-23 | sì | no | no | no | no | no | dich. no | n.o. | nessuna | 97 + 0 |  |
| Campionato Primavera - 2 | 706 | 2023-24 | sì | no | no | sì | no | no | dich. no | n.o. | nessuna | 97 + 490 | minuti presenti solo per il 0% dei giocatori del campione |
| Campionato Primavera - 2 | 706 | 2024-25 | sì | no | no | no | no | no | dich. no | n.o. | nessuna | 97 + 0 | minuti presenti solo per il 0% dei giocatori del campione |
| Campionato Primavera - 2 | 706 | 2025-26 | piano | piano | piano | piano | piano | piano | piano | n.o. | nessuna | - |  |

## Note

- **Valori di mercato:** API-Football non ha un endpoint per i valori di mercato. Restano un segnale opzionale da file CSV forniti dal club.
- **Ruolo specifico:** il fornitore indica solo portiere, difensore, centrocampista, attaccante. Il ruolo specifico (terzino, mezzala...) va dedotto dalla posizione in formazione, dove c'è, o da un CSV.
- **Dettaglio partite:** formazioni, cambi ed eventi richiedono una richiesta per partita (il piano Free non accetta il parametro `ids`).
- **Statistiche dei giocatori:** il piano Free limita l'elenco giocatori a 3 pagine (60 giocatori), quindi l'import le scarica squadra per squadra (circa 3 richieste a squadra). Il fornitore etichetta le statistiche della Serie C come 'Serie C - Supercoppa Lega Finals': l'import le riconosce dal nome.
- **Stima delle richieste** per le stagioni verificate: circa 1832 per l'import base (risultati e statistiche stagionali) e altre 9109 per il dettaglio delle partite (formazioni ed eventi, necessario per la lente B). Con il limite giornaliero l'import richiede più giorni; la cache lo rende riprendibile.
- Richieste reali usate in questa esecuzione: 0.
