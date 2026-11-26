"""Range-uri preflop: parsare notatie standard, grila 169, expandare in combinatii ponderate."""
from __future__ import annotations
import itertools
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Tuple

from .cards import RANKS, RANK_VALUE, rank_of, suit_of

# Toate cele 169 clase de maini: "AA", "AKs", "AKo", ...
HAND_CLASSES: List[str] = []
for _i in range(12, -1, -1):
    for _j in range(_i, -1, -1):
        if _i == _j:
            HAND_CLASSES.append(RANKS[_i] * 2)
        else:
            HAND_CLASSES.append(RANKS[_i] + RANKS[_j] + "s")
            HAND_CLASSES.append(RANKS[_i] + RANKS[_j] + "o")

COMBOS_PER_CLASS = {h: (6 if len(h) == 2 else (4 if h[2] == "s" else 12)) for h in HAND_CLASSES}
TOTAL_COMBOS = 1326
_CLASS_INDEX = {h: i for i, h in enumerate(HAND_CLASSES)}


def hand_class(c1: int, c2: int) -> str:
    r1, r2 = rank_of(c1), rank_of(c2)
    if r1 < r2:
        r1, r2 = r2, r1
    if r1 == r2:
        return RANKS[r1] * 2
    return RANKS[r1] + RANKS[r2] + ("s" if suit_of(c1) == suit_of(c2) else "o")


def class_combos(h: str) -> List[Tuple[int, int]]:
    """Toate combinatiile concrete (c1, c2) ale unei clase."""
    r1 = RANK_VALUE[h[0]]
    r2 = RANK_VALUE[h[1]]
    out = []
    if r1 == r2:
        for s1, s2 in itertools.combinations(range(4), 2):
            out.append((r1 * 4 + s1, r1 * 4 + s2))
    elif h[2] == "s":
        for s in range(4):
            out.append((r1 * 4 + s, r2 * 4 + s))
    else:
        for s1 in range(4):
            for s2 in range(4):
                if s1 != s2:
                    out.append((r1 * 4 + s1, r2 * 4 + s2))
    return out


_TOKEN = re.compile(r"^([2-9TJQKA])([2-9TJQKA])([so]?)(\+?)(?:-([2-9TJQKA])([2-9TJQKA])([so]?))?$")


def _normalize_token(tok: str) -> str:
    tok = tok.strip().replace("10", "T")
    out = []
    for ch in tok:
        if ch in "so":
            out.append(ch)
        elif ch in "SO":
            out.append(ch.lower())
        else:
            out.append(ch.upper())
    return "".join(out)


def _expand_token(tok: str) -> List[str]:
    tok = _normalize_token(tok)
    if not tok:
        return []
    m = _TOKEN.match(tok)
    if not m:
        raise ValueError(f"token de range invalid: {tok!r}")
    a, b, suf, plus, a2, b2, suf2 = m.groups()
    ra, rb = RANK_VALUE[a], RANK_VALUE[b]
    if ra < rb:
        ra, rb = rb, ra
    out: List[str] = []

    def classes(hi: int, lo: int) -> List[str]:
        if hi == lo:
            return [RANKS[hi] * 2]
        base = RANKS[hi] + RANKS[lo]
        if suf == "s":
            return [base + "s"]
        if suf == "o":
            return [base + "o"]
        return [base + "s", base + "o"]

    if a2:  # interval, ex: QQ-88, A5s-A2s, KQo-K9o, T9s-54s
        ra2, rb2 = RANK_VALUE[a2], RANK_VALUE[b2]
        if ra2 < rb2:
            ra2, rb2 = rb2, ra2
        if ra == rb and ra2 == rb2:
            for r in range(min(ra, ra2), max(ra, ra2) + 1):
                out += classes(r, r)
        elif ra == ra2:
            for r in range(min(rb, rb2), max(rb, rb2) + 1):
                out += classes(ra, r)
        else:
            gap = ra - rb
            for hi in range(min(ra, ra2), max(ra, ra2) + 1):
                if hi - gap >= 0:
                    out += classes(hi, hi - gap)
    elif plus:
        if ra == rb:
            for r in range(ra, 13):
                out += classes(r, r)
        else:
            for lo in range(rb, ra):
                out += classes(ra, lo)
    else:
        out += classes(ra, rb)
    return out


@dataclass
class Range:
    """Range ponderat: clasa de mana -> pondere 0..1."""
    weights: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def parse(cls, text: str) -> "Range":
        r = cls()
        if not text or not text.strip():
            return r
        for part in re.split(r"[,\s]+", text.strip()):
            if not part:
                continue
            w = 1.0
            if ":" in part:
                part, ws = part.split(":", 1)
                w = float(ws)
            for h in _expand_token(part):
                r.weights[h] = max(r.weights.get(h, 0.0), min(1.0, w))
        return r

    @classmethod
    def from_classes(cls, classes: Iterable[str], weight: float = 1.0) -> "Range":
        return cls({h: weight for h in classes})

    @classmethod
    def random_hand(cls) -> "Range":
        return cls({h: 1.0 for h in HAND_CLASSES})

    def copy(self) -> "Range":
        return Range(dict(self.weights))

    def contains(self, h: str) -> bool:
        return self.weights.get(h, 0.0) > 0

    def weight(self, h: str) -> float:
        return self.weights.get(h, 0.0)

    def combos(self) -> float:
        return sum(COMBOS_PER_CLASS[h] * w for h, w in self.weights.items())

    def percent(self) -> float:
        return 100.0 * self.combos() / TOTAL_COMBOS

    def union(self, other: "Range") -> "Range":
        r = self.copy()
        for h, w in other.weights.items():
            r.weights[h] = max(r.weights.get(h, 0.0), w)
        return r

    def minus(self, other: "Range") -> "Range":
        r = Range()
        for h, w in self.weights.items():
            nw = w - other.weights.get(h, 0.0)
            if nw > 1e-9:
                r.weights[h] = nw
        return r

    def scaled(self, factor: float) -> "Range":
        return Range({h: min(1.0, w * factor) for h, w in self.weights.items() if w * factor > 1e-9})

    def concrete_combos(self, dead: Sequence[int] = ()) -> List[Tuple[int, int, float]]:
        """Combinatii concrete (c1, c2, pondere) fara cartile moarte."""
        dead_set = set(dead)
        out = []
        for h, w in self.weights.items():
            if w <= 0:
                continue
            for c1, c2 in class_combos(h):
                if c1 not in dead_set and c2 not in dead_set:
                    out.append((c1, c2, w))
        return out

    def to_string(self) -> str:
        items = sorted(self.weights.items(), key=lambda kv: _CLASS_INDEX[kv[0]])
        parts = []
        for h, w in items:
            if w <= 0:
                continue
            parts.append(h if w >= 0.999 else f"{h}:{w:.2f}")
        return ",".join(parts)

    def grid(self) -> List[List[Tuple[str, float]]]:
        """Matricea 13x13 (deasupra diagonalei = suited, sub diagonala = offsuit)."""
        rows = []
        for i in range(12, -1, -1):
            row = []
            for j in range(12, -1, -1):
                if i == j:
                    h = RANKS[i] * 2
                elif i > j:
                    h = RANKS[i] + RANKS[j] + "s"
                else:
                    h = RANKS[j] + RANKS[i] + "o"
                row.append((h, self.weights.get(h, 0.0)))
            rows.append(row)
        return rows

    def __len__(self) -> int:
        return sum(1 for w in self.weights.values() if w > 0)

    def __repr__(self) -> str:
        return f"Range({self.percent():.1f}%)"


def top_percent(percent: float, ordering: Sequence[str]) -> Range:
    """Primele N% maini dupa o ordonare data (lista de clase, cea mai buna intai)."""
    target = TOTAL_COMBOS * percent / 100.0
    r = Range()
    acc = 0.0
    for h in ordering:
        n = COMBOS_PER_CLASS[h]
        if acc + n <= target:
            r.weights[h] = 1.0
            acc += n
        else:
            rest = target - acc
            if rest > 0.01:
                r.weights[h] = rest / n
            break
    return r
