# PokerBrain – asistent de decizie pentru Texas Hold'em No-Limit

Data: 2026-11-12. Document scris de Claude pe baza cererii utilizatorului; deciziile
marcate „(alegerea mea)” nu au fost confirmate explicit de utilizator.

## Intenție
Un program mic pentru desktop care urmărește o masă de poker (sau primește datele
manual), estimează range-urile adversarilor, calculează instant echitate, pot odds,
EV și recomandă cea mai bună acțiune în procente. Învață istoricul fiecărui jucător
pe care îl „vede” și își adaptează recomandările. Poate fi rulat în simulări.

## Avertisment important
Folosirea unui asistent în timp real pe un site de poker cu bani reali încalcă
termenii de utilizare ai practic tuturor operatorilor și poate duce la închiderea
contului și confiscarea fondurilor. Programul este construit ca instrument de studiu,
antrenament și simulare. Modulul de citire a ecranului este generic și necesită
calibrare manuală pe un layout.

## Scop
- Reguli complete NLHE: ordine de acțiune, blinds, ante, min-raise, all-in, side pots,
  showdown (motor `rules.py`), folosit și de simulator.
- Evaluator de mâini 5–7 cărți și echitate Monte Carlo mână-vs-range(uri), cu board.
- Range-uri: parser pentru notația standard (`22+, A2s+, KTo+, QQ-88, A5s-A2s`),
  grile 169, ponderi; charturi preflop pentru cash 6-max/9-max (open, 3-bet, call,
  4-bet) și pentru turnee după adâncimea stack-ului (push/fold, resteal).
- Matematică: pot odds, implied odds, MDF, alpha (break-even bluff), SPR, EV,
  fold equity, ICM (Malmuth-Harville), bubble factor, M-ratio, bankroll (reguli
  buy-in, risk of ruin, Kelly).
- Tracking jucători: VPIP, PFR, 3-bet, fold-to-3-bet, c-bet, fold-to-c-bet,
  AF, WTSD, W$SD, steal, fold-to-steal; clasificare în arhetipuri; range estimat
  pe baza statisticilor; exploatări concrete („dă raise des → 3-bet mai larg”).
- Advisor: pentru starea curentă a mâinii produce acțiune recomandată, mărime,
  echitate, echitate necesară, EV pe fiecare acțiune, încredere și motivație.
  Mod cash vs turneu (ICM, stack efectiv, bubble, ante).
- Simulator: masă cu boți (nit, TAG, LAG, calling station, maniac), hero = advisor,
  rezultate în bb/100 și, pentru turneu, distribuția locurilor.
- Watcher ecran: captură Pillow, profil de layout JSON cu regiuni, recunoaștere
  cărți prin template matching (șabloane capturate de utilizator), OCR text opțional
  (pytesseract dacă există), tool de calibrare.
- UI: Tkinter, fereastră compactă (~340x520), always-on-top, input rapid, panou
  recomandare, panou adversari, bankroll, buton simulare.

## Non-scop
- Nu include suport gata calibrat pentru un client de poker anume.
- Nu rezolvă GTO complet (nu e solver); folosește euristici profesioniste + echitate.

## Alegeri tehnice (alegerea mea)
- Python 3.14, biblioteci standard + numpy/Pillow (deja instalate). Fără Qt.
- SQLite pentru istoricul jucătorilor (`pokerbrain/data/players.db`).
- Teste `unittest`/`pytest` în `tests/`.
