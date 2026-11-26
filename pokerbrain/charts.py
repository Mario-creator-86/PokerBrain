"""Charturi preflop: open-raise, 3-bet, call, 4-bet pentru cash 6-max / 9-max si
range-uri de push/fold, resteal pentru turnee, dupa pozitie si adancimea stack-ului.

Range-urile sunt aproximari ale strategiilor moderne (GTO-ish cu ajustari practice).
Pozitii: UTG, UTG1, UTG2, LJ, HJ, CO, BTN, SB, BB.
"""
from __future__ import annotations
from typing import Dict, List, Optional

from .ranges import Range
from .equity import top_range

POSITIONS_9 = ["UTG", "UTG1", "UTG2", "LJ", "HJ", "CO", "BTN", "SB", "BB"]
POSITIONS_6 = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]

# ------------------------------------------------------------------ CASH 100bb
# open-raise (RFI)
OPEN_6MAX: Dict[str, str] = {
    "UTG": "22+, A2s+, K8s+, Q9s+, J9s+, T9s, 98s, 87s, 76s, ATo+, KJo+, QJo",
    "HJ":  "22+, A2s+, K6s+, Q8s+, J8s+, T8s+, 97s+, 86s+, 75s+, 65s, A9o+, KTo+, QTo+, JTo",
    "CO":  "22+, A2s+, K4s+, Q6s+, J7s+, T7s+, 96s+, 86s+, 75s+, 64s+, 54s, A7o+, A5o, K9o+, Q9o+, J9o+, T9o",
    "BTN": "22+, A2s+, K2s+, Q4s+, J6s+, T6s+, 95s+, 85s+, 74s+, 63s+, 53s+, 43s, A2o+, K7o+, Q8o+, J8o+, T8o+, 98o",
    "SB":  "22+, A2s+, K5s+, Q7s+, J7s+, T7s+, 97s+, 86s+, 75s+, 65s, 54s, A8o+, A5o, K9o+, Q9o+, J9o+, T9o",
}
OPEN_9MAX: Dict[str, str] = {
    "UTG":  "55+, A9s+, A5s-A4s, KTs+, QTs+, JTs, T9s, AJo+, KQo",
    "UTG1": "44+, A8s+, A5s-A4s, KTs+, QTs+, JTs, T9s, 98s, ATo+, KQo",
    "UTG2": "33+, A7s+, A5s-A2s, K9s+, QTs+, J9s+, T9s, 98s, 87s, ATo+, KJo+, QJo",
    "LJ":   OPEN_6MAX["UTG"],
    "HJ":   OPEN_6MAX["HJ"],
    "CO":   OPEN_6MAX["CO"],
    "BTN":  OPEN_6MAX["BTN"],
    "SB":   OPEN_6MAX["SB"],
}

# 3-bet vs open, in functie de pozitia deschizatorului (grupata) si a noastra
# value + bluff-uri. "IP" = suntem in pozitie (CO/BTN), "OOP" = blinds
THREE_BET: Dict[str, str] = {
    "vs_EP_IP":  "QQ+, AKs, AKo, AQs, A5s-A4s:0.5, KQs:0.3",
    "vs_EP_OOP": "QQ+, AKs, AKo, AQs:0.5, A5s-A4s:0.5",
    "vs_MP_IP":  "JJ+, AKs, AKo, AQs, AJs:0.5, KQs:0.5, A5s-A2s:0.6, 76s:0.3, 65s:0.3",
    "vs_MP_OOP": "JJ+, AKs, AKo, AQs, A5s-A3s:0.6, KJs:0.3, 76s:0.3",
    "vs_LP_IP":  "TT+, AQs+, AKo, AQo:0.5, AJs, ATs:0.5, KQs, KJs:0.5, A5s-A2s, 87s:0.4, 76s:0.4, 65s:0.4",
    "vs_LP_OOP": "TT+, AQs+, AKo, AQo:0.6, AJs, KQs, A5s-A2s, K9s:0.3, Q9s:0.3, J9s:0.3, T9s:0.4, 98s:0.4, 87s:0.4",
    "vs_SB_BB":  "99+, ATs+, AJo+, KQs, KJs, KQo:0.5, QJs, A5s-A2s, T9s:0.5, 98s:0.5, 87s:0.5, 76s:0.5, K9s:0.4, Q9s:0.4",
}

# call vs open (flat), IP vs OOP (BB)
CALL_VS_OPEN: Dict[str, str] = {
    "vs_EP_IP":  "JJ-22, AQs-ATs, KQs, KJs, QJs, JTs, T9s, 98s, 87s, 76s, AQo, AJo:0.5, KQo:0.5",
    "vs_MP_IP":  "JJ-22, AJs-A9s, KQs-KTs, QJs, QTs, JTs, T9s, 98s, 87s, 76s, 65s, AQo, AJo, KQo",
    "vs_LP_IP":  "99-22, AJs-A6s, KJs-K9s, QJs-Q9s, JTs, J9s, T9s, T8s, 98s, 87s, 76s, 65s, 54s, AJo, ATo, KQo, KJo",
    "vs_EP_BB":  "JJ-22, AQs-A2s, KQs-K8s, QJs-Q9s, JTs, J9s, T9s, T8s, 98s, 97s, 87s, 76s, 65s, 54s, AQo, AJo, ATo, KQo, KJo, QJo",
    "vs_MP_BB":  "JJ-22, AQs-A2s, KQs-K6s, QJs-Q8s, JTs-J8s, T9s-T7s, 98s-96s, 87s-85s, 76s-75s, 65s-64s, 54s, 43s, AQo-A8o, KQo-KTo, QJo, QTo, JTo",
    "vs_LP_BB":  "99-22, AJs-A2s, KQs-K2s, QJs-Q4s, JTs-J6s, T9s-T6s, 98s-95s, 87s-85s, 76s-74s, 65s-63s, 54s-53s, 43s, AJo-A5o, KQo-K8o, QJo-Q9o, JTo-J9o, T9o, 98o",
    "vs_SB_BB":  "99-22, AJs-A2s, KQs-K2s, QJs-Q2s, JTs-J5s, T9s-T5s, 98s-95s, 87s-84s, 76s-74s, 65s-63s, 54s-52s, 43s, AJo-A2o, KQo-K7o, QJo-Q8o, JTo-J8o, T9o, T8o, 98o, 87o",
}

# 4-bet vs 3-bet (deschizator)
FOUR_BET: Dict[str, str] = {
    "EP": "KK+, AKs, AKo:0.5, QQ:0.5, A5s:0.4",
    "MP": "QQ+, AKs, AKo, A5s:0.5, A4s:0.3",
    "LP": "JJ+, AKs, AKo, AQs:0.4, A5s-A4s:0.6, KQs:0.2",
}
# call vs 3-bet (deschizator, dupa pozitie)
CALL_VS_3BET: Dict[str, str] = {
    "EP": "JJ-99, AQs, AJs:0.5, KQs, AQo:0.5",
    "MP": "JJ-77, AQs-ATs, KQs, KJs, QJs, JTs, AQo, AJo:0.3",
    "LP": "TT-55, AQs-A9s, KQs-KTs, QJs, QTs, JTs, T9s, 98s, 87s, AQo, AJo, KQo",
}

POSITION_GROUP = {"UTG": "EP", "UTG1": "EP", "UTG2": "EP", "LJ": "MP", "HJ": "MP", "CO": "LP", "BTN": "LP",
                  "SB": "SB", "BB": "BB"}


def group_of(pos: str) -> str:
    return POSITION_GROUP.get(pos, "MP")


def positions_for(n_players: int) -> List[str]:
    if n_players <= 6:
        return POSITIONS_6[-n_players:] if n_players < 6 else POSITIONS_6
    return POSITIONS_9[-n_players:]


def open_range(pos: str, n_players: int = 6, stack_bb: float = 100.0) -> Range:
    """Range de open-raise. Pentru stack-uri scurte (<=15bb) foloseste push/fold."""
    if stack_bb <= 15:
        return push_range(pos, stack_bb, n_players)
    table = OPEN_6MAX if n_players <= 6 else OPEN_9MAX
    key = pos if pos in table else ("UTG" if pos != "BB" else "BB")
    if pos == "BB":
        return Range()
    r = Range.parse(table[key])
    if stack_bb < 40:
        # stack-uri medii: eliminam mainile speculative slabe, pastram mainile cu valoare all-in
        r = r.minus(Range.parse("K2s-K5s, Q4s-Q8s, J6s-J8s, T6s-T7s, 95s-96s, 85s, 74s-75s, 63s-64s, 53s-54s, 43s, Q8o-Q9o, J8o-J9o, T8o-T9o, 98o, K7o-K9o, A2o-A5o"))
    return r


def three_bet_range(opener_pos: str, hero_pos: str) -> Range:
    g = group_of(opener_pos)
    if g in ("SB", "BB"):
        return Range.parse(THREE_BET["vs_SB_BB"])
    ip = hero_pos in ("CO", "BTN")
    key = f"vs_{g}_{'IP' if ip else 'OOP'}"
    return Range.parse(THREE_BET[key])


def call_vs_open_range(opener_pos: str, hero_pos: str) -> Range:
    g = group_of(opener_pos)
    if g in ("SB", "BB"):
        return Range.parse(CALL_VS_OPEN["vs_SB_BB"])
    if hero_pos == "BB":
        return Range.parse(CALL_VS_OPEN[f"vs_{g}_BB"])
    if hero_pos == "SB":
        # din SB preferam 3-bet sau fold; flat doar cu maini foarte bune pentru call
        return Range.parse(CALL_VS_OPEN[f"vs_{g}_IP"]).scaled(0.4)
    return Range.parse(CALL_VS_OPEN[f"vs_{g}_IP"])


def four_bet_range(opener_pos: str) -> Range:
    g = group_of(opener_pos)
    if g in ("SB", "BB"):
        g = "LP"
    return Range.parse(FOUR_BET.get(g, FOUR_BET["MP"]))


def call_vs_3bet_range(opener_pos: str) -> Range:
    g = group_of(opener_pos)
    if g in ("SB", "BB"):
        g = "LP"
    return Range.parse(CALL_VS_3BET.get(g, CALL_VS_3BET["MP"]))


# ------------------------------------------------------------------ TURNEE
# Procente de push (open-shove) dupa pozitie si stack efectiv in bb (fara ante; cu ante +~20%).
PUSH_PERCENT: Dict[str, Dict[int, float]] = {
    #        15bb  12bb  10bb   8bb   6bb   4bb
    "EP":  {15: 9,  12: 12, 10: 15, 8: 20, 6: 30, 4: 55},
    "MP":  {15: 12, 12: 16, 10: 20, 8: 27, 6: 38, 4: 62},
    "LP":  {15: 20, 12: 26, 10: 32, 8: 42, 6: 55, 4: 80},
    "SB":  {15: 28, 12: 36, 10: 44, 8: 55, 6: 70, 4: 100},
    "BB":  {15: 0,  12: 0,  10: 0,  8: 0,  6: 0,  4: 0},
}
# Procente de call vs un shove, in functie de stack-ul efectiv si de range-ul estimat al shover-ului
# (calculate la rulare din echitate), aici doar praguri de referinta pentru BB vs SB shove
CALL_SHOVE_PERCENT_BB_VS_SB: Dict[int, float] = {15: 18, 12: 24, 10: 30, 8: 38, 6: 50, 4: 70}


def _interp(table: Dict[int, float], stack_bb: float) -> float:
    keys = sorted(table)
    if stack_bb <= keys[0]:
        return table[keys[0]]
    if stack_bb >= keys[-1]:
        return table[keys[-1]]
    for a, b in zip(keys, keys[1:]):
        if a <= stack_bb <= b:
            t = (stack_bb - a) / (b - a)
            return table[a] + t * (table[b] - table[a])
    return table[keys[-1]]


def push_range(pos: str, stack_bb: float, n_players: int = 9, ante: bool = False) -> Range:
    """Range de open-shove pentru stack-uri scurte (<= 15bb)."""
    g = group_of(pos)
    if g == "BB":
        return Range()
    pct = _interp(PUSH_PERCENT[g], max(4.0, min(15.0, stack_bb)))
    if ante:
        pct *= 1.2
    if n_players <= 6 and g in ("EP", "MP"):
        pct *= 1.15  # mai putini jucatori in spate
    return top_range(min(100.0, pct))


def call_shove_range(stack_bb: float, shover_range_pct: float, pot_odds_needed: float) -> Range:
    """Range de call vs shove: aproximare liniara: mai larg cand shover-ul e larg si odds-urile bune."""
    base = _interp(CALL_SHOVE_PERCENT_BB_VS_SB, max(4.0, min(15.0, stack_bb)))
    factor = (shover_range_pct / 40.0) * (0.4 / max(0.2, pot_odds_needed))
    return top_range(max(2.0, min(100.0, base * factor)))


def resteal_range(opener_pos: str, stack_bb: float) -> Range:
    """3-bet shove (resteal) 12-25bb vs open din pozitii tarzii."""
    g = group_of(opener_pos)
    base = {"EP": 6, "MP": 9, "LP": 14, "SB": 18}.get(g, 9)
    if stack_bb < 15:
        base *= 1.3
    elif stack_bb > 22:
        base *= 0.8
    return top_range(base)


def describe_chart(r: Range) -> str:
    return f"{r.percent():.1f}% ({r.combos():.0f} combinatii): {r.to_string()}"
