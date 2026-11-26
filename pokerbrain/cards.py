"""Reprezentarea cartilor. O carte este un int 0..51: rank = c // 4 (0=2 .. 12=A), suit = c % 4."""
from __future__ import annotations
import random
from typing import Iterable, List, Sequence

RANKS = "23456789TJQKA"
SUITS = "cdhs"
SUIT_SYMBOLS = {"c": "♣", "d": "♦", "h": "♥", "s": "♠"}
RANK_VALUE = {r: i for i, r in enumerate(RANKS)}
SUIT_VALUE = {s: i for i, s in enumerate(SUITS)}
_SYMBOL_TO_SUIT = {v: k for k, v in SUIT_SYMBOLS.items()}


def card(text: str) -> int:
    """'As' -> 51, 'Td' -> 33. Accepta si simboluri unicode si litere mici."""
    t = text.strip().replace("10", "T")
    if len(t) != 2:
        raise ValueError(f"carte invalida: {text!r}")
    r, s = t[0].upper(), t[1].lower()
    s = _SYMBOL_TO_SUIT.get(s, s)
    if r not in RANK_VALUE or s not in SUIT_VALUE:
        raise ValueError(f"carte invalida: {text!r}")
    return RANK_VALUE[r] * 4 + SUIT_VALUE[s]


def cards(text: str) -> List[int]:
    """'As Kd' sau 'AsKd' sau 'As,Kd' -> [51, 47]."""
    t = text.replace(",", " ").replace("10", "T").strip()
    if not t:
        return []
    if " " in t:
        parts = t.split()
    else:
        parts = [t[i:i + 2] for i in range(0, len(t), 2)]
    out = [card(p) for p in parts]
    if len(set(out)) != len(out):
        raise ValueError(f"carti duplicate in {text!r}")
    return out


def rank_of(c: int) -> int:
    return c // 4


def suit_of(c: int) -> int:
    return c % 4


def card_str(c: int, pretty: bool = False) -> str:
    r, s = RANKS[c // 4], SUITS[c % 4]
    return r + (SUIT_SYMBOLS[s] if pretty else s)


def cards_str(cs: Iterable[int], pretty: bool = False) -> str:
    return " ".join(card_str(c, pretty) for c in cs)


FULL_DECK = tuple(range(52))


class Deck:
    def __init__(self, rng: random.Random | None = None, dead: Sequence[int] = ()):
        self.rng = rng or random.Random()
        dead_set = set(dead)
        self.cards = [c for c in FULL_DECK if c not in dead_set]
        self.rng.shuffle(self.cards)

    def draw(self, n: int = 1) -> List[int]:
        out = self.cards[-n:]
        del self.cards[-n:]
        return out

    def remove(self, cs: Iterable[int]) -> None:
        s = set(cs)
        self.cards = [c for c in self.cards if c not in s]

    def __len__(self) -> int:
        return len(self.cards)
