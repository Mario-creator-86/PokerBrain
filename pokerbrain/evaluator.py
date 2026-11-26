"""Evaluator rapid pentru maini de 5-7 carti.

Scorul este un int: categoria << 20 | kickeri (4 biti fiecare, cel mai important la stanga).
Scor mai mare = mana mai buna. Categorii: 0 high card .. 8 straight flush.
"""
from __future__ import annotations
from typing import Sequence

HIGH_CARD, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)
CATEGORY_NAMES = [
    "carte mare", "pereche", "doua perechi", "trei de un fel", "chinta",
    "culoare", "full", "careu", "chinta de culoare",
]

# straight lookup: pentru fiecare masca de 13 biti -> rank-ul cartii de sus (sau -1)
_STRAIGHT_TOP = [-1] * 8192
for _mask in range(8192):
    _top = -1
    for _s in range(12, 3, -1):
        _need = 0b11111 << (_s - 4)
        if _mask & _need == _need:
            _top = _s
            break
    if _top == -1 and (_mask & 0b1000000001111) == 0b1000000001111:  # A2345
        _top = 3
    _STRAIGHT_TOP[_mask] = _top

_POPCOUNT = [bin(i).count("1") for i in range(8192)]


def _top_ranks(mask: int, k: int) -> int:
    """Impacheteaza cele mai mari k rank-uri din masca in 4 biti fiecare."""
    out = 0
    cnt = 0
    r = 12
    while cnt < k and r >= 0:
        if mask >> r & 1:
            out = (out << 4) | r
            cnt += 1
        r -= 1
    return out << (4 * (k - cnt))


def evaluate(cs: Sequence[int]) -> int:
    """Evalueaza 5..7 carti (int 0..51). Returneaza scorul."""
    suit_masks = [0, 0, 0, 0]
    rank_count = [0] * 13
    rank_mask = 0
    for c in cs:
        r = c >> 2
        suit_masks[c & 3] |= 1 << r
        rank_count[r] += 1
        rank_mask |= 1 << r

    # flush / straight flush
    for sm in suit_masks:
        if _POPCOUNT[sm] >= 5:
            top = _STRAIGHT_TOP[sm]
            if top >= 0:
                return (STRAIGHT_FLUSH << 20) | (top << 16)
            return (FLUSH << 20) | _top_ranks(sm, 5)

    quads = trips = -1
    pairs = []
    for r in range(12, -1, -1):
        n = rank_count[r]
        if n == 4:
            quads = r
        elif n == 3:
            if trips == -1:
                trips = r
            else:
                pairs.append(r)  # al doilea set conteaza ca pereche pentru full
        elif n == 2:
            pairs.append(r)

    if quads >= 0:
        kick_mask = rank_mask & ~(1 << quads)
        return (QUADS << 20) | (quads << 16) | (_top_ranks(kick_mask, 1) << 12)
    if trips >= 0 and pairs:
        return (FULL_HOUSE << 20) | (trips << 16) | (pairs[0] << 12)
    top = _STRAIGHT_TOP[rank_mask]
    if top >= 0:
        return (STRAIGHT << 20) | (top << 16)
    if trips >= 0:
        kick_mask = rank_mask & ~(1 << trips)
        return (TRIPS << 20) | (trips << 16) | (_top_ranks(kick_mask, 2) << 8)
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        kick_mask = rank_mask & ~(1 << p1) & ~(1 << p2)
        return (TWO_PAIR << 20) | (p1 << 16) | (p2 << 12) | (_top_ranks(kick_mask, 1) << 8)
    if len(pairs) == 1:
        p = pairs[0]
        kick_mask = rank_mask & ~(1 << p)
        return (PAIR << 20) | (p << 16) | (_top_ranks(kick_mask, 3) << 4)
    return (HIGH_CARD << 20) | _top_ranks(rank_mask, 5)


def category(score: int) -> int:
    return score >> 20


def describe(score: int) -> str:
    return CATEGORY_NAMES[score >> 20]
