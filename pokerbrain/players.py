"""Istoricul si profilul jucatorilor: statistici (VPIP, PFR, 3-bet, c-bet, ...), clasificare in
arhetipuri, estimarea range-urilor pe baza statisticilor si exploatari concrete. Persistenta SQLite."""
from __future__ import annotations
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

from .ranges import Range
from .equity import top_range
from . import charts

# Valori medii de populatie folosite ca prior (shrinkage bayesian) cand avem putine maini.
PRIORS = {
    "vpip": 0.26, "pfr": 0.19, "threebet": 0.07, "fold_to_3bet": 0.55, "cbet": 0.60,
    "fold_to_cbet": 0.45, "steal": 0.35, "fold_to_steal": 0.65, "wtsd": 0.28, "wsd": 0.50,
    "fold_to_raise_post": 0.50, "fold_to_bet_post": 0.50, "limp": 0.08, "check_raise": 0.07,
    "fold_to_4bet": 0.55, "squeeze": 0.05, "call_open": 0.10,
}
PRIOR_WEIGHT = {"vpip": 15, "pfr": 15, "threebet": 40, "fold_to_3bet": 10, "cbet": 10, "fold_to_cbet": 10,
                "steal": 10, "fold_to_steal": 10, "wtsd": 12, "wsd": 8, "fold_to_raise_post": 8,
                "fold_to_bet_post": 10, "limp": 15, "check_raise": 15, "fold_to_4bet": 5, "squeeze": 30,
                "call_open": 20}

# evenimente -> (campul_oportunitati, campul_realizari)
EVENTS: Dict[str, Tuple[str, Optional[str]]] = {
    # preflop
    "vpip_opp": ("vpip_opp", None), "vpip": ("vpip_opp", "vpip_n"),
    "pfr_opp": ("pfr_opp", None), "pfr": ("pfr_opp", "pfr_n"),
    "limp": ("limp_opp", "limp_n"), "limp_opp": ("limp_opp", None),
    "call_open": ("call_open_opp", "call_open_n"), "call_open_opp": ("call_open_opp", None),
    "3bet_opp": ("threebet_opp", None), "3bet": ("threebet_opp", "threebet_n"),
    "fold_to_3bet_opp": ("fold_to_3bet_opp", None), "fold_to_3bet": ("fold_to_3bet_opp", "fold_to_3bet_n"),
    "fold_to_4bet_opp": ("fold_to_4bet_opp", None), "fold_to_4bet": ("fold_to_4bet_opp", "fold_to_4bet_n"),
    "squeeze_opp": ("squeeze_opp", None), "squeeze": ("squeeze_opp", "squeeze_n"),
    "steal_opp": ("steal_opp", None), "steal": ("steal_opp", "steal_n"),
    "fold_to_steal_opp": ("fold_to_steal_opp", None), "fold_to_steal": ("fold_to_steal_opp", "fold_to_steal_n"),
    # postflop
    "cbet_opp": ("cbet_opp", None), "cbet": ("cbet_opp", "cbet_n"),
    "fold_to_cbet_opp": ("fold_to_cbet_opp", None), "fold_to_cbet": ("fold_to_cbet_opp", "fold_to_cbet_n"),
    "fold_to_bet_post_opp": ("fold_to_bet_post_opp", None), "fold_to_bet_post": ("fold_to_bet_post_opp", "fold_to_bet_post_n"),
    "fold_to_raise_post_opp": ("fold_to_raise_post_opp", None), "fold_to_raise_post": ("fold_to_raise_post_opp", "fold_to_raise_post_n"),
    "check_raise_opp": ("check_raise_opp", None), "check_raise": ("check_raise_opp", "check_raise_n"),
    "bet_or_raise": ("aggr_actions", None), "call_post": ("passive_actions", None),
    "saw_flop": ("saw_flop", None), "wtsd": ("saw_flop", "wtsd_n"),
    "sd_opp": ("sd_opp", None), "wsd": ("sd_opp", "wsd_n"),
}


@dataclass
class PlayerStats:
    name: str
    hands: int = 0
    vpip_opp: int = 0
    vpip_n: int = 0
    pfr_opp: int = 0
    pfr_n: int = 0
    limp_opp: int = 0
    limp_n: int = 0
    call_open_opp: int = 0
    call_open_n: int = 0
    threebet_opp: int = 0
    threebet_n: int = 0
    fold_to_3bet_opp: int = 0
    fold_to_3bet_n: int = 0
    fold_to_4bet_opp: int = 0
    fold_to_4bet_n: int = 0
    squeeze_opp: int = 0
    squeeze_n: int = 0
    steal_opp: int = 0
    steal_n: int = 0
    fold_to_steal_opp: int = 0
    fold_to_steal_n: int = 0
    cbet_opp: int = 0
    cbet_n: int = 0
    fold_to_cbet_opp: int = 0
    fold_to_cbet_n: int = 0
    fold_to_bet_post_opp: int = 0
    fold_to_bet_post_n: int = 0
    fold_to_raise_post_opp: int = 0
    fold_to_raise_post_n: int = 0
    check_raise_opp: int = 0
    check_raise_n: int = 0
    aggr_actions: int = 0
    passive_actions: int = 0
    saw_flop: int = 0
    wtsd_n: int = 0
    sd_opp: int = 0
    wsd_n: int = 0
    net_bb: float = 0.0
    notes: str = ""
    last_seen: float = 0.0
    tags: List[str] = field(default_factory=list)

    # ------------------------------------------------------------ observare
    def observe(self, event: str, count: int = 1) -> None:
        """Inregistreaza un eveniment (vezi EVENTS). 'x' incrementeaza si oportunitatea si realizarea."""
        if event not in EVENTS:
            raise KeyError(f"eveniment necunoscut: {event}")
        opp, n = EVENTS[event]
        setattr(self, opp, getattr(self, opp) + count)
        if n:
            setattr(self, n, getattr(self, n) + count)
        self.last_seen = time.time()

    def new_hand(self) -> None:
        self.hands += 1
        self.last_seen = time.time()

    # ------------------------------------------------------------ statistici
    def _rate(self, key: str, n: int, opp: int) -> float:
        """Estimare cu shrinkage spre prior: (n + prior*w) / (opp + w)."""
        p, w = PRIORS[key], PRIOR_WEIGHT[key]
        return (n + p * w) / (opp + w)

    def _raw(self, n: int, opp: int) -> Optional[float]:
        return n / opp if opp else None

    @property
    def vpip(self) -> float:
        return self._rate("vpip", self.vpip_n, self.vpip_opp)

    @property
    def pfr(self) -> float:
        return min(self.vpip, self._rate("pfr", self.pfr_n, self.pfr_opp))

    @property
    def threebet(self) -> float:
        return self._rate("threebet", self.threebet_n, self.threebet_opp)

    @property
    def fold_to_3bet(self) -> float:
        return self._rate("fold_to_3bet", self.fold_to_3bet_n, self.fold_to_3bet_opp)

    @property
    def fold_to_4bet(self) -> float:
        return self._rate("fold_to_4bet", self.fold_to_4bet_n, self.fold_to_4bet_opp)

    @property
    def squeeze(self) -> float:
        return self._rate("squeeze", self.squeeze_n, self.squeeze_opp)

    @property
    def limp(self) -> float:
        return self._rate("limp", self.limp_n, self.limp_opp)

    @property
    def call_open(self) -> float:
        return self._rate("call_open", self.call_open_n, self.call_open_opp)

    @property
    def steal(self) -> float:
        return self._rate("steal", self.steal_n, self.steal_opp)

    @property
    def fold_to_steal(self) -> float:
        return self._rate("fold_to_steal", self.fold_to_steal_n, self.fold_to_steal_opp)

    @property
    def cbet(self) -> float:
        return self._rate("cbet", self.cbet_n, self.cbet_opp)

    @property
    def fold_to_cbet(self) -> float:
        return self._rate("fold_to_cbet", self.fold_to_cbet_n, self.fold_to_cbet_opp)

    @property
    def fold_to_bet_post(self) -> float:
        return self._rate("fold_to_bet_post", self.fold_to_bet_post_n, self.fold_to_bet_post_opp)

    @property
    def fold_to_raise_post(self) -> float:
        return self._rate("fold_to_raise_post", self.fold_to_raise_post_n, self.fold_to_raise_post_opp)

    @property
    def check_raise(self) -> float:
        return self._rate("check_raise", self.check_raise_n, self.check_raise_opp)

    @property
    def af(self) -> float:
        """Aggression factor postflop (bets+raises)/calls, prior 2.0."""
        return (self.aggr_actions + 2.0 * 3) / (self.passive_actions + 3)

    @property
    def wtsd(self) -> float:
        return self._rate("wtsd", self.wtsd_n, self.saw_flop)

    @property
    def wsd(self) -> float:
        return self._rate("wsd", self.wsd_n, self.sd_opp)

    @property
    def confidence(self) -> float:
        """0..1: cat de multa incredere avem in statistici (saturatie la ~200 maini)."""
        return min(1.0, self.hands / 200.0)

    def summary(self) -> str:
        return (f"{self.name}: {self.hands}h VPIP {100*self.vpip:.0f} PFR {100*self.pfr:.0f} "
                f"3B {100*self.threebet:.0f} F3B {100*self.fold_to_3bet:.0f} CB {100*self.cbet:.0f} "
                f"FCB {100*self.fold_to_cbet:.0f} AF {self.af:.1f} WTSD {100*self.wtsd:.0f} [{self.archetype()}]")

    # ------------------------------------------------------------ clasificare
    def archetype(self) -> str:
        if self.hands < 8:
            return "necunoscut"
        v, p, af = self.vpip, self.pfr, self.af
        gap = v - p
        if v >= 0.45 and p >= 0.30:
            return "maniac"
        if v >= 0.35 and gap >= 0.15 and af < 2.0:
            return "fish (loose-passive)"
        if v >= 0.28 and p >= 0.20:
            return "LAG"
        if v <= 0.16:
            return "nit"
        if 0.16 < v < 0.28 and p >= 0.6 * v:
            return "TAG"
        if gap >= 0.12:
            return "loose-passive"
        return "regular"

    def exploits(self) -> List[str]:
        """Exploatari concrete, in functie de statistici (doar cand avem suficiente date)."""
        out: List[str] = []
        c = self.confidence
        if self.hands < 8:
            return ["putine maini: joaca standard (ranges de populatie)"]
        if self.pfr >= 0.25 and self.pfr_opp >= 15:
            out.append(f"deschide des ({100*self.pfr:.0f}% PFR): 3-bet mai larg pentru valoare si ca bluff")
        if self.threebet >= 0.11 and self.threebet_opp >= 15:
            out.append(f"3-bet des ({100*self.threebet:.0f}%): 4-bet light si call mai larg vs 3-bet")
        if self.fold_to_3bet >= 0.65 and self.fold_to_3bet_opp >= 8:
            out.append(f"fold la 3-bet {100*self.fold_to_3bet:.0f}%: 3-bet bluff profitabil")
        if self.fold_to_3bet <= 0.40 and self.fold_to_3bet_opp >= 8:
            out.append(f"nu da fold la 3-bet ({100*self.fold_to_3bet:.0f}%): 3-bet doar cu valoare")
        if self.fold_to_cbet >= 0.60 and self.fold_to_cbet_opp >= 8:
            out.append(f"fold la c-bet {100*self.fold_to_cbet:.0f}%: c-bet aproape orice")
        if self.fold_to_cbet <= 0.35 and self.fold_to_cbet_opp >= 8:
            out.append(f"nu da fold la c-bet ({100*self.fold_to_cbet:.0f}%): c-bet doar cu valoare/draw-uri bune, value bet subtil")
        if self.cbet >= 0.75 and self.cbet_opp >= 8:
            out.append(f"c-bet {100*self.cbet:.0f}%: float si raise mai des pe flop")
        if self.fold_to_steal >= 0.75 and self.fold_to_steal_opp >= 8:
            out.append(f"fold la steal {100*self.fold_to_steal:.0f}%: fura blinds-urile cu orice")
        if self.fold_to_steal <= 0.50 and self.fold_to_steal_opp >= 8:
            out.append("apara blind-urile des: steal doar cu maini jucabile")
        if self.wtsd >= 0.36 and self.saw_flop >= 15:
            out.append(f"merge la showdown des ({100*self.wtsd:.0f}%): nu bluff-ui, value bet subtil")
        if self.wtsd <= 0.20 and self.saw_flop >= 15:
            out.append("renunta usor: pariaza pe mai multe strazi, bluff-urile functioneaza")
        if self.af >= 3.5 and (self.aggr_actions + self.passive_actions) >= 20:
            out.append("foarte agresiv postflop: call down mai larg, lasa-l sa bluff-uiasca")
        if self.af <= 1.0 and (self.aggr_actions + self.passive_actions) >= 20:
            out.append("pasiv postflop: raise-ul lui inseamna aproape mereu nuts")
        if self.limp >= 0.15 and self.limp_opp >= 12:
            out.append("da limp des: izoleaza cu raise larg")
        if not out:
            out.append("profil echilibrat: joaca aproape de GTO")
        return out

    # ------------------------------------------------------------ range-uri estimate
    def open_range(self, pos: str, n_players: int, stack_bb: float = 100.0) -> Range:
        """Range-ul de open-raise estimat: chart-ul pozitiei scalat cu PFR-ul relativ la populatie."""
        base = charts.open_range(pos, n_players, stack_bb)
        base_pct = base.percent()
        if base_pct <= 0:
            return base
        factor = self.pfr / PRIORS["pfr"]
        target = max(3.0, min(85.0, base_pct * factor))
        if abs(target - base_pct) < 1.5:
            return base
        return top_range(target)

    def three_bet_range(self, opener_pos: str, hero_pos: str) -> Range:
        base = charts.three_bet_range(opener_pos, hero_pos)
        factor = self.threebet / PRIORS["threebet"]
        target = max(2.0, min(40.0, base.percent() * factor))
        if abs(target - base.percent()) < 1.0:
            return base
        return top_range(target)

    def call_open_range(self, opener_pos: str, hero_pos: str) -> Range:
        base = charts.call_vs_open_range(opener_pos, hero_pos)
        gap = max(0.02, self.vpip - self.pfr)
        factor = gap / (PRIORS["vpip"] - PRIORS["pfr"])
        target = max(3.0, min(70.0, base.percent() * factor))
        if abs(target - base.percent()) < 1.5:
            return base
        # mainile de call sunt "mijlocul" range-ului: scoatem premium-urile (ar fi 3-bet)
        r = top_range(target + 4.0).minus(top_range(3.5))
        return r

    def shove_range(self, pos: str, stack_bb: float, n_players: int) -> Range:
        base = charts.push_range(pos, stack_bb, n_players)
        factor = 0.5 + 0.5 * (self.pfr / PRIORS["pfr"])
        return top_range(max(3.0, min(100.0, base.percent() * factor)))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PlayerStats":
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in fields})


# ----------------------------------------------------------------------------
# Baza de date
# ----------------------------------------------------------------------------

class PlayerDB:
    """Stocare SQLite a profilurilor. Cache in memorie; `save()` scrie modificarile."""

    def __init__(self, path: Optional[str] = None):
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "data", "players.db")
        self.path = path
        self._cache: Dict[str, PlayerStats] = {}
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("CREATE TABLE IF NOT EXISTS players (name TEXT PRIMARY KEY, data TEXT, updated REAL)")
        self.conn.commit()

    def get(self, name: str) -> PlayerStats:
        key = name.strip()
        if key in self._cache:
            return self._cache[key]
        row = self.conn.execute("SELECT data FROM players WHERE name=?", (key,)).fetchone()
        if row:
            st = PlayerStats.from_dict(json.loads(row[0]))
        else:
            st = PlayerStats(name=key)
        self._cache[key] = st
        return st

    def names(self) -> List[str]:
        rows = self.conn.execute("SELECT name FROM players ORDER BY updated DESC").fetchall()
        return [r[0] for r in rows]

    def save(self, name: Optional[str] = None) -> None:
        items = [(name, self._cache[name])] if name else list(self._cache.items())
        for n, st in items:
            self.conn.execute("INSERT OR REPLACE INTO players (name, data, updated) VALUES (?, ?, ?)",
                              (n, json.dumps(st.to_dict()), time.time()))
        self.conn.commit()

    def delete(self, name: str) -> None:
        self._cache.pop(name, None)
        self.conn.execute("DELETE FROM players WHERE name=?", (name,))
        self.conn.commit()

    def close(self) -> None:
        self.save()
        self.conn.close()


# ----------------------------------------------------------------------------
# Extragerea statisticilor dintr-o mana jucata (HandRecord din rules.py)
# ----------------------------------------------------------------------------

def update_stats_from_hand(db: PlayerDB, record, seat_positions: Dict[str, str], results: Dict[str, float],
                           bb: float = 1.0) -> None:
    """Parcurge actiunile unei maini si actualizeaza statisticile fiecarui jucator."""
    from .rules import Street, ActionType
    names = list(seat_positions)
    for n in names:
        db.get(n).new_hand()
        db.get(n).net_bb += results.get(n, 0.0) / bb

    pre = [(p, a) for s, p, a, _ in record.actions if s == Street.PREFLOP]
    raises = 0
    opener = None
    three_bettor = None
    voluntarily = set()
    folded_pre = set()
    callers_pre = set()
    limped = set()
    acted = set()
    for p, a in pre:
        st = db.get(p)
        pos = seat_positions.get(p, "")
        is_blind_check = a.type == ActionType.CHECK and pos == "BB" and raises == 0
        if p not in acted:
            st.observe("vpip_opp")
            st.observe("pfr_opp")
            if raises == 0:
                st.observe("limp_opp")
            if raises == 1 and opener != p:
                st.observe("3bet_opp")
                st.observe("call_open_opp")
            if raises == 2 and opener == p:
                st.observe("fold_to_3bet_opp")
            if raises == 3 and three_bettor == p:
                st.observe("fold_to_4bet_opp")
            if raises == 1 and callers_pre and p not in callers_pre and opener != p:
                st.observe("squeeze_opp")
            if raises == 0 and pos in ("CO", "BTN", "SB") and not voluntarily and not limped:
                st.observe("steal_opp")
            if raises == 1 and pos in ("SB", "BB") and opener is not None and \
                    seat_positions.get(opener) in ("CO", "BTN", "SB") and not callers_pre:
                st.observe("fold_to_steal_opp")
        acted.add(p)
        if a.type in (ActionType.RAISE, ActionType.BET, ActionType.ALLIN):
            if p not in voluntarily:
                st.observe("vpip")
                st.observe("pfr")
            voluntarily.add(p)
            if raises == 0:
                opener = p
                if pos in ("CO", "BTN", "SB") and not limped:
                    st.observe("steal")
            elif raises == 1:
                three_bettor = p
                st.observe("3bet")
                if callers_pre:
                    st.observe("squeeze")
            raises += 1
        elif a.type == ActionType.CALL:
            if p not in voluntarily and not (pos == "BB" and raises == 0 and a.amount == 0):
                st.observe("vpip")
            voluntarily.add(p)
            if raises == 0:
                limped.add(p)
                st.observe("limp")
            elif raises == 1:
                callers_pre.add(p)
                st.observe("call_open")
        elif a.type == ActionType.FOLD:
            folded_pre.add(p)
            if raises == 2 and opener == p:
                st.observe("fold_to_3bet")
            if raises == 3 and three_bettor == p:
                st.observe("fold_to_4bet")
            if raises == 1 and pos in ("SB", "BB") and opener is not None and \
                    seat_positions.get(opener) in ("CO", "BTN", "SB") and not callers_pre:
                st.observe("fold_to_steal")
        elif is_blind_check:
            pass

    # postflop
    in_hand = [n for n in names if n not in folded_pre and any(p == n for p, _ in pre) or
               (n not in folded_pre and seat_positions.get(n) in ("SB", "BB"))]
    in_hand = [n for n in in_hand if n not in folded_pre]
    post = [(s, p, a) for s, p, a, _ in record.actions if s != Street.PREFLOP]
    if post or record.went_to_showdown:
        for n in in_hand:
            db.get(n).observe("saw_flop")
    last_aggressor = opener if raises >= 1 else None
    if three_bettor:
        last_aggressor = three_bettor
    street_seen = None
    bettor_this_street = None          # ultimul care a pariat/ridicat pe strada curenta
    checked_this_street = set()        # cine a dat check pe strada curenta (pentru check-raise)
    cbet_pending = last_aggressor      # agresorul preflop are oportunitate de c-bet pe flop
    flop_bet_was_cbet = False
    for s, p, a in post:
        st = db.get(p)
        if s != street_seen:
            street_seen = s
            bettor_this_street = None
            checked_this_street = set()
            if s != Street.FLOP:
                cbet_pending = None
                flop_bet_was_cbet = False
        if a.type in (ActionType.BET, ActionType.RAISE, ActionType.ALLIN):
            st.observe("bet_or_raise")
            if bettor_this_street is None:
                if s == Street.FLOP and p == cbet_pending:
                    st.observe("cbet")
                    flop_bet_was_cbet = True
                    cbet_pending = None
                if p in checked_this_street:
                    st.observe("check_raise_opp")
            else:
                db.get(bettor_this_street).observe("fold_to_raise_post_opp")
                if p in checked_this_street:
                    st.observe("check_raise")
            bettor_this_street = p
        elif a.type == ActionType.CALL:
            st.observe("call_post")
            if s == Street.FLOP and flop_bet_was_cbet:
                st.observe("fold_to_cbet_opp")
            else:
                st.observe("fold_to_bet_post_opp")
        elif a.type == ActionType.FOLD:
            if s == Street.FLOP and flop_bet_was_cbet:
                st.observe("fold_to_cbet")
            else:
                st.observe("fold_to_bet_post")
        elif a.type == ActionType.CHECK:
            if s == Street.FLOP and p == cbet_pending and bettor_this_street is None:
                st.observe("cbet_opp")
                cbet_pending = None
            if bettor_this_street is None:
                checked_this_street.add(p)
    for n in record.went_to_showdown:
        st = db.get(n)
        st.observe("wtsd")
        st.observe("sd_opp")
        if record.winners.get(n, 0) > 0:
            st.observe("wsd")
