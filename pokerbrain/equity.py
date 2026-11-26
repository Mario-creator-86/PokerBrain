"""Calcule de echitate: Monte Carlo si enumerare, mana vs maini concrete sau vs range-uri."""
from __future__ import annotations
import itertools
import json
import os
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .cards import FULL_DECK, rank_of, suit_of
from .evaluator import evaluate, category, STRAIGHT, FLUSH
from .ranges import Range, HAND_CLASSES, class_combos, hand_class, top_percent

Hand = Tuple[int, int]


@dataclass
class EquityResult:
    win: float
    tie: float
    iterations: int
    exact: bool = False

    @property
    def equity(self) -> float:
        return self.win + self.tie

    @property
    def percent(self) -> float:
        return 100.0 * self.equity

    def __repr__(self) -> str:
        return f"Equity({self.percent:.1f}% win={100*self.win:.1f} tie={100*self.tie:.1f} n={self.iterations}{' exact' if self.exact else ''})"


def _showdown(hero: Sequence[int], villains: Sequence[Sequence[int]], board: Sequence[int]) -> float:
    """1.0 castig, 0.0 pierdere, 1/n la egalitate (echitatea hero in acel runout)."""
    hs = evaluate(list(hero) + list(board))
    best = hs
    n_tied = 1
    for v in villains:
        vs = evaluate(list(v) + list(board))
        if vs > best:
            return 0.0
        if vs == best:
            n_tied += 1
    return 1.0 / n_tied if best == hs else 0.0


def equity_vs_hands(hero: Hand, villains: Sequence[Hand], board: Sequence[int] = (),
                    iterations: int = 5000, rng: Optional[random.Random] = None) -> EquityResult:
    """Echitatea hero vs maini concrete. Enumerare exacta cand sunt <= 2 carti de venit."""
    rng = rng or random.Random()
    dead = set(hero) | set(board)
    for v in villains:
        dead |= set(v)
    remaining = [c for c in FULL_DECK if c not in dead]
    to_come = 5 - len(board)
    if to_come <= 2 or (to_come == 3 and len(remaining) <= 48 and iterations >= 15000):
        total = 0.0
        n = 0
        for extra in itertools.combinations(remaining, to_come):
            total += _showdown(hero, villains, list(board) + list(extra))
            n += 1
        # separam win/tie aproximativ: recalculam win-only
        wins = 0.0
        for extra in itertools.combinations(remaining, to_come):
            full = list(board) + list(extra)
            hs = evaluate(list(hero) + full)
            if all(evaluate(list(v) + full) < hs for v in villains):
                wins += 1
        return EquityResult(wins / n, (total - wins) / n, n, exact=True)
    wins = ties = 0.0
    for _ in range(iterations):
        extra = rng.sample(remaining, to_come)
        full = list(board) + extra
        hs = evaluate(list(hero) + full)
        best_v = max(evaluate(list(v) + full) for v in villains)
        if hs > best_v:
            wins += 1
        elif hs == best_v:
            n_tied = 1 + sum(1 for v in villains if evaluate(list(v) + full) == hs)
            ties += 1.0 / n_tied
    return EquityResult(wins / iterations, ties / iterations, iterations)


def _sample_villain_hands(ranges_combos: List[List[Tuple[int, int, float]]],
                          weights: List[List[float]], rng: random.Random,
                          dead: set) -> Optional[List[Hand]]:
    """Trage o mana din fiecare range fara coliziuni; None daca esueaza."""
    taken = set(dead)
    out = []
    for combos, ws in zip(ranges_combos, weights):
        for _attempt in range(20):
            c1, c2, _w = rng.choices(combos, weights=ws, k=1)[0]
            if c1 not in taken and c2 not in taken:
                taken.add(c1)
                taken.add(c2)
                out.append((c1, c2))
                break
        else:
            return None
    return out


def equity_vs_ranges(hero: Hand, villain_ranges: Sequence[Range], board: Sequence[int] = (),
                     iterations: int = 3000, rng: Optional[random.Random] = None) -> EquityResult:
    """Echitatea hero vs unul sau mai multe range-uri ponderate, Monte Carlo."""
    rng = rng or random.Random()
    dead = set(hero) | set(board)
    ranges_combos = []
    weights = []
    for r in villain_ranges:
        combos = r.concrete_combos(dead=list(dead))
        if not combos:
            combos = Range.random_hand().concrete_combos(dead=list(dead))
        ranges_combos.append(combos)
        weights.append([w for _, _, w in combos])
    remaining_all = [c for c in FULL_DECK if c not in dead]
    to_come = 5 - len(board)
    wins = ties = 0.0
    n = 0
    for _ in range(iterations):
        vh = _sample_villain_hands(ranges_combos, weights, rng, dead)
        if vh is None:
            continue
        used = dead.union(*[set(h) for h in vh])
        if to_come:
            pool = [c for c in remaining_all if c not in used]
            extra = rng.sample(pool, to_come)
        else:
            extra = []
        full = list(board) + extra
        hs = evaluate(list(hero) + full)
        vscores = [evaluate(list(v) + full) for v in vh]
        best_v = max(vscores)
        if hs > best_v:
            wins += 1
        elif hs == best_v:
            ties += 1.0 / (1 + sum(1 for s in vscores if s == hs))
        n += 1
    if n == 0:
        return EquityResult(0.0, 0.0, 0)
    return EquityResult(wins / n, ties / n, n)


def range_vs_range_equity(r1: Range, r2: Range, board: Sequence[int] = (), iterations: int = 3000,
                          rng: Optional[random.Random] = None) -> float:
    """Echitatea medie a range-ului r1 vs r2."""
    rng = rng or random.Random()
    dead = set(board)
    c1 = r1.concrete_combos(list(dead))
    c2 = r2.concrete_combos(list(dead))
    if not c1 or not c2:
        return 0.5
    w1 = [w for _, _, w in c1]
    w2 = [w for _, _, w in c2]
    remaining = [c for c in FULL_DECK if c not in dead]
    to_come = 5 - len(board)
    total = 0.0
    n = 0
    for _ in range(iterations):
        a1, a2, _ = rng.choices(c1, weights=w1, k=1)[0]
        b1, b2, _ = rng.choices(c2, weights=w2, k=1)[0]
        if len({a1, a2, b1, b2}) < 4:
            continue
        pool = [c for c in remaining if c not in (a1, a2, b1, b2)]
        full = list(board) + (rng.sample(pool, to_come) if to_come else [])
        total += _showdown((a1, a2), [(b1, b2)], full)
        n += 1
    return total / n if n else 0.5


# ----------------------------------------------------------------------------
# Analiza mainii pe board: forta, draw-uri, outs
# ----------------------------------------------------------------------------

@dataclass
class HandAnalysis:
    made_category: int
    made_name: str
    flush_draw: bool = False
    backdoor_flush: bool = False
    oesd: bool = False          # open-ended straight draw (8 outs)
    gutshot: bool = False       # 4 outs
    overcards: int = 0          # cate carti din mana sunt peste board
    outs: int = 0               # outs estimate spre o mana mai buna decat top pair
    top_pair: bool = False
    overpair: bool = False
    set_or_better: bool = False
    nut_flush_draw: bool = False
    strength_rank: float = 0.0  # 0..1 cat la suta din mainile posibile batem pe board-ul curent
    notes: List[str] = field(default_factory=list)


def _straight_outs(hand: Sequence[int], board: Sequence[int]) -> Tuple[int, bool, bool]:
    """Returneaza (outs_chinta, oesd, gutshot) pe baza cartilor curente."""
    known = list(hand) + list(board)
    if len(board) >= 5:
        return 0, False, False
    cur = evaluate(known) if len(known) >= 5 else -1
    if cur >= 0 and category(cur) >= STRAIGHT:
        return 0, False, False
    dead = set(known)
    outs_ranks = set()
    for c in FULL_DECK:
        if c in dead:
            continue
        sc = evaluate(known + [c]) if len(known) + 1 >= 5 else -1
        if sc >= 0 and category(sc) == STRAIGHT:
            # verificam ca folosim macar o carte din mana (altfel e chinta pe board)
            bsc = evaluate(list(board) + [c]) if len(board) + 1 >= 5 else -1
            if not (bsc >= 0 and category(bsc) == STRAIGHT):
                outs_ranks.add(rank_of(c))
    n = len(outs_ranks)
    return n * 4, n >= 2, n == 1


def analyze_hand(hand: Sequence[int], board: Sequence[int]) -> HandAnalysis:
    hand = list(hand)
    board = list(board)
    if len(board) < 3:
        hc = hand_class(hand[0], hand[1])
        a = HandAnalysis(made_category=0, made_name="preflop")
        a.notes.append(f"preflop {hc}")
        return a
    score = evaluate(hand + board)
    a = HandAnalysis(made_category=category(score), made_name=_name(score))
    hr = sorted((rank_of(c) for c in hand), reverse=True)
    br = sorted((rank_of(c) for c in board), reverse=True)
    board_max = br[0]
    board_ranks = set(br)
    # pereche / overpair / top pair / set
    if hr[0] == hr[1]:
        if hr[0] > board_max:
            a.overpair = True
        if hr[0] in board_ranks:
            a.set_or_better = True
    else:
        if hr[0] == board_max and hr[0] in board_ranks:
            a.top_pair = True
        if hr[1] == board_max and hr[1] in board_ranks:
            a.top_pair = True
    if a.made_category >= 3 and not a.set_or_better:
        a.set_or_better = True  # trips / better

    a.overcards = sum(1 for r in hr if r > board_max)

    # flush draw
    if len(board) < 5:
        suits = [suit_of(c) for c in hand + board]
        for s in range(4):
            n = suits.count(s)
            hand_in_suit = sum(1 for c in hand if suit_of(c) == s)
            if n == 4 and hand_in_suit >= 1 and a.made_category < FLUSH:
                a.flush_draw = True
                if hand_in_suit == 2 or any(rank_of(c) == 12 and suit_of(c) == s for c in hand):
                    hand_suit_ranks = [rank_of(c) for c in hand if suit_of(c) == s]
                    board_suit_ranks = [rank_of(c) for c in board if suit_of(c) == s]
                    higher_missing = [r for r in range(12, -1, -1)
                                      if r not in hand_suit_ranks and r not in board_suit_ranks]
                    if hand_suit_ranks and (not higher_missing or max(hand_suit_ranks) > higher_missing[0]):
                        a.nut_flush_draw = True
            elif n == 3 and hand_in_suit == 2 and len(board) == 3:
                a.backdoor_flush = True

    so, oesd, gut = _straight_outs(hand, board)
    a.oesd, a.gutshot = oesd, gut
    outs = so + (9 if a.flush_draw else 0)
    if a.flush_draw and so:
        outs -= 2 if oesd else 1  # suprapunere aproximativa
    if a.backdoor_flush:
        outs += 1
    if a.made_category == 0 and a.overcards == 2:
        outs += 6 if not a.flush_draw else 3
    a.outs = max(0, min(outs, 21))
    if a.flush_draw:
        a.notes.append("flush draw" + (" (nut)" if a.nut_flush_draw else ""))
    if a.oesd:
        a.notes.append("OESD")
    elif a.gutshot:
        a.notes.append("gutshot")
    if a.overpair:
        a.notes.append("overpair")
    elif a.top_pair:
        a.notes.append("top pair")
    if a.set_or_better and a.made_category >= 3:
        a.notes.append(a.made_name)
    if a.overcards == 2 and a.made_category == 0:
        a.notes.append("2 overcards")
    a.strength_rank = hand_strength_vs_random(hand, board)
    return a


def hand_strength_vs_random(hand: Sequence[int], board: Sequence[int]) -> float:
    """Procentul de maini aleatoare (2 carti) pe care le batem ACUM pe board (fara carti de venit)."""
    if len(board) < 3:
        return 0.5
    dead = set(hand) | set(board)
    remaining = [c for c in FULL_DECK if c not in dead]
    hs = evaluate(list(hand) + list(board))
    ahead = behind = tied = 0
    for a, b in itertools.combinations(remaining, 2):
        vs = evaluate([a, b] + list(board))
        if hs > vs:
            ahead += 1
        elif hs < vs:
            behind += 1
        else:
            tied += 1
    total = ahead + behind + tied
    return (ahead + tied / 2) / total if total else 0.5


def _name(score: int) -> str:
    from .evaluator import describe
    return describe(score)


# ----------------------------------------------------------------------------
# Ordonarea celor 169 de maini (dupa echitatea vs un range de call de ~25%),
# folosita pentru range-uri "top X%" si push/fold.
# ----------------------------------------------------------------------------

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_ORDER_FILE = os.path.join(_DATA_DIR, "hand_order.json")
_ORDER_CACHE: Optional[List[str]] = None

# Ordonare de rezerva (standard, aproximativa) daca fisierul lipseste.
_FALLBACK_ORDER = (
    "AA KK QQ JJ TT AKs AQs AJs AKo ATs 99 AQo KQs KJs AJo KTs A9s ATo KQo 88 QJs A8s QTs KJo A7s "
    "A5s A9o A4s A6s A3s KTo QJo A2s 77 K9s JTs QTo A8o Q9s J9s K8s T9s A7o K7s 66 A5o A6o K6s A4o "
    "Q8s K5s A3o T8s J8s K4s 98s K9o A2o Q9o J9o K3s T9o 55 K2s Q7s 97s J7s T7s 87s Q6s 44 K8o Q5s 86s "
    "T8o J8o 98o 76s Q4s 96s 33 K7o Q3s J6s T6s 75s 65s Q2s K6o 22 J5s 85s K5o 97o 87o 54s J4s T5s 95s "
    "Q8o K4o 64s T7o J7o 74s J3s K3o 53s 84s T4s 94s K2o J2s 43s Q7o 63s T3s 86o 76o 93s 73s Q6o 52s "
    "T2s 92s 42s 83s Q5o 65o 96o 75o 82s 32s 72s 62s Q4o 54o 85o J6o T6o 95o Q3o 64o J5o 74o Q2o J4o "
    "53o T5o 84o 94o 43o J3o T4o 63o 73o 93o J2o T3o 52o 83o 42o T2o 92o 82o 32o 72o 62o"
).split()


def hand_ordering() -> List[str]:
    """Lista celor 169 de clase, de la cea mai puternica la cea mai slaba."""
    global _ORDER_CACHE
    if _ORDER_CACHE is not None:
        return _ORDER_CACHE
    if os.path.exists(_ORDER_FILE):
        try:
            with open(_ORDER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) == 169:
                _ORDER_CACHE = data
                return data
        except (OSError, ValueError):
            pass
    _ORDER_CACHE = list(_FALLBACK_ORDER)
    return _ORDER_CACHE


def compute_hand_ordering(iterations: int = 1500, seed: int = 7) -> List[str]:
    """Recalculeaza ordonarea celor 169 de maini dupa echitatea vs top 25% (din ordonarea de rezerva)."""
    rng = random.Random(seed)
    calling = top_percent(25.0, _FALLBACK_ORDER)
    results: Dict[str, float] = {}
    for h in HAND_CLASSES:
        c1, c2 = class_combos(h)[0]
        eq_r = equity_vs_ranges((c1, c2), [calling], (), iterations, rng).equity
        eq_rand = equity_vs_ranges((c1, c2), [Range.random_hand()], (), iterations // 2, rng).equity
        results[h] = 0.6 * eq_r + 0.4 * eq_rand
    order = sorted(HAND_CLASSES, key=lambda h: -results[h])
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_ORDER_FILE, "w", encoding="utf-8") as f:
        json.dump(order, f)
    global _ORDER_CACHE
    _ORDER_CACHE = order
    return order


def top_range(percent: float) -> Range:
    return top_percent(percent, hand_ordering())


def hand_percentile(h: str) -> float:
    """Pozitia mainii in ordonare, ca procent din combinatii (0 = cea mai buna)."""
    order = hand_ordering()
    acc = 0.0
    from .ranges import COMBOS_PER_CLASS
    for x in order:
        if x == h:
            return 100.0 * acc / 1326
        acc += COMBOS_PER_CLASS[x]
    return 100.0
