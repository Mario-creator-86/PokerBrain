# PokerBrain – asistent de decizie pentru Texas Hold'em No-Limit

Program mic pentru desktop (Python + Tkinter, fereastră compactă always-on-top) care:

- cunoaște regulile complete NLHE (motor propriu de mână: blinds, ante, ordine, min-raise, all-in, side pots, showdown);
- stăpânește range-urile: notație standard (`22+, A2s+, KTo+, QQ-88, A5s-A2s`), charturi preflop pentru cash 6-max / 9-max (open, 3-bet, call, 4-bet) și pentru turnee (push/fold, resteal) după stack;
- calculează instant echitate (Monte Carlo + enumerare exactă pe turn/river), pot odds, implied odds, MDF, alpha, SPR, EV pe fiecare acțiune, ICM / bubble factor, M-ratio, bankroll (buy-in-uri, risk of ruin);
- păstrează istoricul jucătorilor (SQLite) cu VPIP, PFR, 3-bet, fold-to-3-bet, c-bet, fold-to-c-bet, steal, AF, WTSD etc., îi clasifică (nit / TAG / LAG / fish / maniac) și **își adaptează recomandările** (ex: adversarul deschide des și dă fold la 3-bet → propune 3-bet mai larg);
- explică fiecare decizie: ce costă în bb, în bani, ca procent din stack și din bankroll;
- poate fi pus în simulări: masă de cash sau turneu SNG cu boți de arhetipuri diferite, hero = advisor;
- poate citi masa de pe ecran (modul „watcher”, generic, necesită calibrare).

## Avertisment

Folosirea unui asistent în timp real pe un site de poker cu bani reali încalcă termenii de utilizare ai
practic tuturor operatorilor și poate duce la închiderea contului și confiscarea fondurilor. Programul
este gândit ca instrument de **studiu, antrenament și simulare**. Nu include suport calibrat pentru
niciun client de poker anume.

## Instalare și pornire

Necesită Python 3.11+ cu `numpy` și `Pillow`. Pentru citirea sumelor de pe ecran (OCR) mai trebuie
`pytesseract` și binarul Tesseract; programul îl găsește singur în locațiile uzuale de instalare
(nu trebuie pus în PATH).

```bash
python -m pip install -r requirements.txt
```

```bash
winget install --id UB-Mannheim.TesseractOCR -e
```

```bash
python -m pokerbrain
```

Alte comenzi:

```bash
python -m pokerbrain advise AhKh --board "Qh 7h 2c" --pos BTN --pot 14 --call 4 --villain "v:BB:100:call:bet:4"
```

```bash
python -m pokerbrain sim --bots nit,tag,lag,fish,maniac --hands 1000
```

```bash
python -m pokerbrain sim --mtt --bots fish,tag,lag,nit,maniac --hands 20
```

```bash
python -m pokerbrain ranges
```

```bash
python -m pokerbrain calibrate
```

Teste:

```bash
python -m pytest tests -q
```

## Fereastra principală

Toate sumele se introduc în **big blinds**. Cărțile se scriu `As Kd`, `AsKd` sau `10h`.

1. Alege **Cash / Turneu**, numărul de locuri, poziția ta, valoarea unui BB în bani și bankroll-ul.
2. Completează mâna, board-ul (gol preflop), potul total (inclusiv pariurile de pe stradă), cât ai de plătit, stack-ul.
3. Alege starea preflop (nimeni n-a deschis / open în față / 3-bet în față / all-in în față ...) și numărul de limperi / calleri.
4. Pentru fiecare adversar relevant: bifează-l, nume (istoricul se leagă de nume), poziție, stack, acțiunea preflop și ultima acțiune pe strada curentă, pariul lui.
5. **Enter** sau „Analizează”. Vei vedea acțiunea recomandată și mărimea, echitatea vs range-ul estimat, echitatea necesară (pot odds, ajustată ICM în turneu), EV-ul fiecărei acțiuni, încrederea, motivele, range-ul estimat al adversarului și exploatările disponibile.

Scurtături: `Enter` analizează, `Ctrl+N` mână nouă, `Esc` șterge board-ul.

**Observ**: înregistrează manual un eveniment pentru un adversar (a dat 3-bet, fold la c-bet, a mers la showdown ...). `+mână` adaugă o mână jucată tuturor adversarilor bifați. Fereastra **Jucători** arată statisticile, arhetipul, exploatările și range-urile estimate pentru fiecare nume din baza de date.

## Simulare

Butonul **Simulare** (sau `python -m pokerbrain sim`) rulează mâini între advisor și boți:

| bot | stil |
|-----|------|
| nit | foarte strâns, pasiv, fold la presiune |
| tag | solid, apropiat de un regular bun |
| lag | larg și agresiv, 3-bet des, multe bluff-uri |
| fish | loose-passive, limp, call cu orice |
| maniac | hiper-agresiv, c-bet aproape mereu |

Raportul arată bb/100, deviația standard, showdown-uri, și profilurile pe care hero le-a învățat din ce a
văzut (acestea sunt exact profilurile folosite apoi la adaptare). Varianta e mare sub ~1000 de mâini.

## Watcher (citirea ecranului)

**Important: unii clienți de poker își protejează fereastra împotriva capturii de ecran** (Windows
„display affinity”, `WDA_EXCLUDEFROMCAPTURE`). În capturi, în locul mesei apare ce e în spatele ei
(tapetul). Este o măsură anti-asistență a operatorului; PokerBrain o detectează și o raportează
(„captura blocată de aplicație”), dar nu o ocolește. Pentru astfel de clienți folosește introducerea
manuală din fereastra principală. Watcher-ul merge cu replayere, instrumente de antrenament și
clienți care nu blochează captura.

1. Deschide masa de poker (sau un replayer) pe ecran.
2. „Calibrare” → alege fereastra mesei din lista „Fereastra” (↻ reîmprospătează) și apasă „Captură”. Poți folosi și un screenshot făcut de tine cu „Încarcă imagine” (PrtSc = tot ecranul, Alt+PrtSc = fereastra activă; marginile invizibile ale ferestrei sunt decupate automat). Fereastra se capturează direct (prin PrintWindow, chiar dacă e acoperită; altfel este adusă în față), iar regiunile se salvează relativ la fereastră, deci profilul merge și dacă muți masa. Fără fereastră aleasă se capturează tot ecranul, cu ferestrele PokerBrain ascunse („Captură în 3s” îți lasă timp să aduci masa în față), iar regiunile sunt în pixeli absoluți. „Zoom pe masă” + dreptunghi te lasă să lucrezi mărit (rotița face zoom în jurul cursorului, „Vedere completă” revine). Apoi, pentru fiecare regiune din listă (cărțile hero, cele 5 de pe board, pot, de plătit, stack, nume/stack/pariu/buton dealer pentru fiecare loc) alege numele și desenează dreptunghiul. Salvează profilul.
3. Șabloane de cărți: selectează `hero_card_1`, apasă „Șablon carte” și scrie ce carte se vede (`As`, `Td` ...). Repetă până ai cât mai multe din cele 52 (plus `empty` pentru locul gol). Recunoașterea se face prin potrivire de șablon (distanță cosinus) + semnătură de culoare.
4. Textul (pot, stack-uri, nume) se citește cu Tesseract (vezi instalarea mai sus). Regiunile sunt mărite 4x, binarizate cu prag Otsu și încadrate cu margine albă înainte de OCR; pe sume în stil de client de poker precizia e ~96%. Fără Tesseract aceste câmpuri se completează manual, iar watcher-ul completează doar cărțile.
5. Pornește „Watcher” din fereastra principală: la fiecare schimbare a mesei câmpurile se actualizează și analiza se reface automat.

Profilurile și șabloanele sunt în `pokerbrain/data/layouts/`.

## Structura codului

| fișier | rol |
|--------|-----|
| `pokerbrain/cards.py` | cărți, pachet |
| `pokerbrain/evaluator.py` | evaluator 5–7 cărți (măști de biți) |
| `pokerbrain/ranges.py` | parser de range-uri, grila 169, combinații ponderate |
| `pokerbrain/equity.py` | echitate Monte Carlo / exactă, analiză de draw-uri, ordonarea celor 169 de mâini |
| `pokerbrain/charts.py` | charturi preflop cash și turneu |
| `pokerbrain/math_tools.py` | pot odds, MDF, alpha, EV, ICM, bubble factor, M, bankroll |
| `pokerbrain/rules.py` | motorul de mână NLHE (reguli complete) |
| `pokerbrain/players.py` | statistici, arhetipuri, exploatări, range-uri estimate, SQLite |
| `pokerbrain/advisor.py` | motorul de decizie |
| `pokerbrain/simulator.py` | boți, masă cash, turneu SNG, agentul hero |
| `pokerbrain/watcher/` | captură, layout, recunoaștere cărți/OCR, calibrare |
| `pokerbrain/ui/app.py` | fereastra Tkinter |
| `tests/` | 57 de teste (reguli, evaluator, echitate, charturi, advisor, simulator, watcher) |

Documentul de design: `docs/superpowers/specs/2026-11-12-poker-advisor-design.md`.

## Limitări cunoscute

- Nu este un solver GTO; range-urile postflop sunt estimate euristic (clasificare pe buckets: made hand / draw / air), iar EV-urile sunt aproximări cu un singur nivel de privire înainte.
- Ordonarea celor 169 de mâini (`pokerbrain/data/hand_order.json`) este calculată după echitatea all-in vs un range de call; este potrivită pentru push/fold, mai puțin pentru joc deep.
- Watcher-ul nu vine cu șabloane: trebuie capturate pe layout-ul tău. OCR-ul a fost verificat doar pe text sintetic, nu pe un client real.
