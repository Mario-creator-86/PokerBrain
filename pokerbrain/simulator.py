"""Simulator: o masa cu boti de arhetipuri diferite (nit, TAG, LAG, fish, maniac) si hero = Advisor.
Ruleaza maini complete prin motorul de reguli, actualizeaza profilurile jucatorilor din ce "vede"
si raporteaza rezultatele (bb/100, showdown-uri, distributia locurilor in turneu)."""
from __future__ import annotations
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .cards import FULL_DECK
from .evaluator import evaluate
from .rules import HandEngine, Seat, Action, ActionType, Street, HandRecord
from .ranges import hand_class
from .equity import hand_percentile, analyze_hand
from .advisor import Advisor, Situation, Opponent, Recommendation, quick_bucket
from .players import PlayerDB, update_stats_from_hand
from .math_tools import pot_odds, outs_to_equity


# ----------------------------------------------------------------------------
# Boti
# ----------------------------------------------------------------------------

@dataclass
class BotProfile:
    name: str
    open_pct: Dict[str, float]      # procent de open dupa grupa de pozitie
    limp_pct: float = 0.0           # cat la suta din mainile jucabile le da limp in loc de raise
    threebet_pct: float = 6.0
    call_open_pct: float = 14.0     # pana la ce percentila da call la open
    call_3bet_pct: float = 6.0
    fourbet_pct: float = 2.5
    cbet_freq: float = 0.6
    bluff_freq: float = 0.12        # pariaza fara mana
    bet_strength: float = 0.62      # forta minima (0..1) pentru pariu de valoare
    raise_strength: float = 0.86
    call_slack: float = 0.0         # cat de mult peste/sub pot odds accepta (negativ = calling station)
    fold_to_cbet: float = 0.5       # probabilitatea de a renunta cu maini slabe la c-bet
    bet_size: float = 0.66
    push_pct: float = 25.0          # procent de shove cu stack scurt

    @staticmethod
    def group(pos: str) -> str:
        return {"UTG": "EP", "UTG1": "EP", "UTG2": "EP", "LJ": "MP", "HJ": "MP", "CO": "LP", "BTN": "LP",
                "SB": "SB", "BB": "BB"}.get(pos, "MP")


PROFILES: Dict[str, BotProfile] = {
    "nit": BotProfile("nit", {"EP": 7, "MP": 9, "LP": 13, "SB": 12, "BB": 0}, threebet_pct=3, call_open_pct=7,
                      call_3bet_pct=3, fourbet_pct=1.5, cbet_freq=0.55, bluff_freq=0.03, bet_strength=0.7,
                      raise_strength=0.9, call_slack=0.12, fold_to_cbet=0.7, push_pct=12),
    "tag": BotProfile("tag", {"EP": 15, "MP": 19, "LP": 30, "SB": 28, "BB": 0}, threebet_pct=7, call_open_pct=16,
                      call_3bet_pct=7, fourbet_pct=2.5, cbet_freq=0.65, bluff_freq=0.12, bet_strength=0.6,
                      raise_strength=0.85, call_slack=0.03, fold_to_cbet=0.5, push_pct=25),
    "lag": BotProfile("lag", {"EP": 22, "MP": 28, "LP": 45, "SB": 40, "BB": 0}, threebet_pct=12, call_open_pct=22,
                      call_3bet_pct=10, fourbet_pct=4, cbet_freq=0.8, bluff_freq=0.25, bet_strength=0.55,
                      raise_strength=0.8, call_slack=-0.02, fold_to_cbet=0.4, push_pct=35),
    "fish": BotProfile("fish", {"EP": 35, "MP": 40, "LP": 50, "SB": 50, "BB": 0}, limp_pct=0.6, threebet_pct=3,
                       call_open_pct=45, call_3bet_pct=20, fourbet_pct=1.5, cbet_freq=0.4, bluff_freq=0.05,
                       bet_strength=0.7, raise_strength=0.92, call_slack=-0.15, fold_to_cbet=0.25, push_pct=30),
    "maniac": BotProfile("maniac", {"EP": 45, "MP": 55, "LP": 70, "SB": 65, "BB": 0}, threebet_pct=20,
                         call_open_pct=40, call_3bet_pct=20, fourbet_pct=8, cbet_freq=0.95, bluff_freq=0.45,
                         bet_strength=0.45, raise_strength=0.7, call_slack=-0.08, fold_to_cbet=0.25, bet_size=1.0,
                         push_pct=55),
}


def _quick_strength(hole: List[int], board: List[int], rng: random.Random, samples: int = 120) -> float:
    """Forta curenta: fractia de maini aleatoare pe care le batem acum (esantionat)."""
    dead = set(hole) | set(board)
    remaining = [c for c in FULL_DECK if c not in dead]
    hs = evaluate(hole + board)
    ahead = 0.0
    for _ in range(samples):
        a, b = rng.sample(remaining, 2)
        vs = evaluate([a, b] + board)
        if hs > vs:
            ahead += 1
        elif hs == vs:
            ahead += 0.5
    return ahead / samples


class Bot:
    def __init__(self, profile: BotProfile, rng: random.Random):
        self.p = profile
        self.rng = rng

    def act(self, eng: HandEngine, i: int, ctx: "HandContext") -> Action:
        seat = eng.seats[i]
        legal = eng.legal_actions(i)
        hc = hand_class(*seat.hole)
        pct = hand_percentile(hc)
        pos = ctx.positions[seat.name]
        stack_bb = seat.stack / eng.bb
        if eng.street == Street.PREFLOP:
            return self._preflop(eng, i, ctx, legal, pct, pos, stack_bb)
        return self._postflop(eng, i, ctx, legal)

    # ------------------------------------------------------------ preflop
    def _preflop(self, eng, i, ctx, legal, pct, pos, stack_bb) -> Action:
        p = self.p
        raises = ctx.preflop_raises
        to_call = legal.get("call", 0.0)
        g = BotProfile.group(pos)
        if stack_bb <= 12 and raises == 0:
            if pos == "BB" and to_call == 0:
                return Action(ActionType.CHECK)
            return Action(ActionType.ALLIN) if pct <= p.push_pct else self._fold_or_check(legal)
        if raises == 0:
            thr = p.open_pct.get(g, 15)
            if ctx.limpers:
                thr *= 0.8
            if pct <= thr:
                if p.limp_pct and self.rng.random() < p.limp_pct and pct > 4:
                    return Action(ActionType.CALL) if "call" in legal else Action(ActionType.CHECK)
                size = eng.bb * (2.5 + len(ctx.limpers))
                return Action(ActionType.RAISE, min(size, legal.get("max_raise", size)))
            if pos == "BB" and to_call == 0:
                return Action(ActionType.CHECK)
            if p.limp_pct and pct <= thr * 1.6 and "call" in legal and to_call <= eng.bb:
                return Action(ActionType.CALL)
            return self._fold_or_check(legal)
        if raises == 1:
            if ctx.opener == eng.seats[i].name:  # nu ar trebui, dar
                return Action(ActionType.CHECK) if "check" in legal else Action(ActionType.CALL)
            if pct <= p.threebet_pct or (self.rng.random() < p.bluff_freq * 0.4 and pct <= 30):
                if stack_bb <= 25:
                    return Action(ActionType.ALLIN)
                size = eng.current_bet * (3.0 if g == "LP" else 3.6) + eng.bb * len(ctx.callers)
                return Action(ActionType.RAISE, min(size, legal.get("max_raise", size)))
            if pct <= p.call_open_pct and "call" in legal and (to_call <= eng.seats[i].stack * 0.3):
                return Action(ActionType.CALL)
            return self._fold_or_check(legal)
        # facing 3bet+
        if pct <= p.fourbet_pct:
            if stack_bb <= 45 or raises >= 3:
                return Action(ActionType.ALLIN)
            size = eng.current_bet * 2.4
            return Action(ActionType.RAISE, min(size, legal.get("max_raise", size)))
        if pct <= p.call_3bet_pct and "call" in legal and to_call <= eng.seats[i].stack * 0.35:
            return Action(ActionType.CALL)
        return self._fold_or_check(legal)

    @staticmethod
    def _fold_or_check(legal) -> Action:
        return Action(ActionType.CHECK) if "check" in legal else Action(ActionType.FOLD)

    # ------------------------------------------------------------ postflop
    def _postflop(self, eng, i, ctx, legal) -> Action:
        p = self.p
        seat = eng.seats[i]
        board = list(eng.board)
        strength = _quick_strength(list(seat.hole), board, self.rng)
        bucket = quick_bucket(seat.hole[0], seat.hole[1], board)
        cards_to_come = 5 - len(board)
        outs = 0
        if cards_to_come and bucket in ("draw", "weak_draw"):
            outs = 9 if bucket == "draw" else 4
        draw_eq = outs_to_equity(outs, cards_to_come) if outs else 0.0
        to_call = legal.get("call", 0.0)
        pot = eng.pot
        if to_call > 0:
            po = pot_odds(to_call, pot)
            need = po + p.call_slack
            if strength >= p.raise_strength and "min_raise" in legal and self.rng.random() < 0.7:
                size = eng.current_bet * 3
                return Action(ActionType.RAISE, min(size, legal["max_raise"]))
            if strength >= need or draw_eq >= po * 0.9 or (strength > 0.4 and self.rng.random() < p.bluff_freq * 0.3):
                if to_call > seat.stack * 0.6 and strength < 0.75 and draw_eq < 0.3:
                    return Action(ActionType.FOLD)
                return Action(ActionType.CALL)
            # bluff raise ocazional
            if "min_raise" in legal and self.rng.random() < p.bluff_freq * 0.25 and bucket in ("draw", "weak_draw"):
                size = eng.current_bet * 2.8
                return Action(ActionType.RAISE, min(size, legal["max_raise"]))
            return Action(ActionType.FOLD)
        # nimeni nu a pariat
        is_cbet_spot = ctx.last_aggressor == seat.name and eng.street == Street.FLOP
        want_bet = strength >= p.bet_strength
        if is_cbet_spot and self.rng.random() < p.cbet_freq:
            want_bet = True
        if bucket == "draw" and self.rng.random() < 0.5 + p.bluff_freq:
            want_bet = True
        if not want_bet and self.rng.random() < p.bluff_freq * (0.5 if len(ctx.active_names(eng)) > 2 else 1.0):
            want_bet = True
        if want_bet and "min_raise" in legal:
            size = max(legal["min_raise"], pot * p.bet_size)
            if strength > 0.95 and self.rng.random() < 0.3:
                size = pot * 1.2
            return Action(ActionType.BET, min(size, legal["max_raise"]))
        return Action(ActionType.CHECK)


# ----------------------------------------------------------------------------
# Context pentru o mana (derivat din HandRecord), folosit de boti si de hero
# ----------------------------------------------------------------------------

class HandContext:
    def __init__(self, eng: HandEngine):
        self.eng = eng
        self.positions: Dict[str, str] = {s.name: eng.position_of(i) for i, s in enumerate(eng.seats)
                                          if s.in_hand or s.hole}

    @property
    def preflop_actions(self):
        return [(p, a) for s, p, a, _ in self.eng.record.actions if s == Street.PREFLOP]

    @property
    def preflop_raises(self) -> int:
        return sum(1 for _, a in self.preflop_actions if a.type in (ActionType.RAISE, ActionType.BET, ActionType.ALLIN))

    @property
    def opener(self) -> Optional[str]:
        for p, a in self.preflop_actions:
            if a.type in (ActionType.RAISE, ActionType.BET, ActionType.ALLIN):
                return p
        return None

    @property
    def three_bettor(self) -> Optional[str]:
        n = 0
        for p, a in self.preflop_actions:
            if a.type in (ActionType.RAISE, ActionType.BET, ActionType.ALLIN):
                n += 1
                if n == 2:
                    return p
        return None

    @property
    def limpers(self) -> List[str]:
        out = []
        raises = 0
        for p, a in self.preflop_actions:
            if a.type in (ActionType.RAISE, ActionType.BET, ActionType.ALLIN):
                raises += 1
            elif a.type == ActionType.CALL and raises == 0:
                out.append(p)
        return out

    @property
    def callers(self) -> List[str]:
        out = []
        raises = 0
        for p, a in self.preflop_actions:
            if a.type in (ActionType.RAISE, ActionType.BET, ActionType.ALLIN):
                raises += 1
            elif a.type == ActionType.CALL and raises == 1:
                out.append(p)
        return out

    @property
    def last_aggressor(self) -> Optional[str]:
        """Ultimul agresor de pe strada ANTERIOARA celei curente (pentru c-bet)."""
        cur = self.eng.street
        prev = None
        for s, p, a, _ in self.eng.record.actions:
            if s.value < cur.value and a.type in (ActionType.RAISE, ActionType.BET, ActionType.ALLIN):
                prev = p
        return prev

    def active_names(self, eng) -> List[str]:
        return [s.name for s in eng.seats if s.in_hand]

    def street_actions(self, street: Street) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for s, p, a, _ in self.eng.record.actions:
            if s == street:
                out.setdefault(p, []).append(a.type.value)
        return out


# ----------------------------------------------------------------------------
# Hero: Advisor -> actiune
# ----------------------------------------------------------------------------

def build_situation(eng: HandEngine, i: int, ctx: HandContext, db: Optional[PlayerDB], mode: str = "cash",
                    payouts: Optional[List[float]] = None, iterations: int = 600,
                    rng: Optional[random.Random] = None) -> Situation:
    seat = eng.seats[i]
    bb = eng.bb
    legal = eng.legal_actions(i)
    pre = ctx.preflop_actions
    raises = ctx.preflop_raises
    opener = ctx.opener
    opps: List[Opponent] = []
    names_in_hand_at_start = list(ctx.positions)
    n_players = len(names_in_hand_at_start)
    for j, s in enumerate(eng.seats):
        if j == i or not (s.in_hand or s.hole):
            continue
        if not s.in_hand:
            continue
        o = Opponent(name=s.name, position=ctx.positions.get(s.name, "BTN"), stack_bb=s.stack / bb,
                     stats=db.get(s.name) if db else None, bet_bb=s.bet_this_street / bb)
        # actiunea preflop
        pa = "none"
        rcount = 0
        for p, a in pre:
            if a.type in (ActionType.RAISE, ActionType.BET, ActionType.ALLIN):
                rcount += 1
                if p == s.name:
                    pa = {1: "open", 2: "3bet", 3: "4bet"}.get(rcount, "4bet")
                    if a.type == ActionType.ALLIN or s.all_in:
                        pa = "allin"
            elif p == s.name and a.type == ActionType.CALL:
                pa = "call" if rcount >= 1 else "limp"
            elif p == s.name and a.type == ActionType.CHECK and pa == "none":
                pa = "check"
        o.preflop_action = pa
        # actiuni postflop pe strazile anterioare
        post_actions: List[str] = []
        for st in (Street.FLOP, Street.TURN, Street.RIVER):
            if st.value < eng.street.value:
                acts = ctx.street_actions(st).get(s.name, [])
                if acts:
                    post_actions.append("raise" if "raise" in acts else ("bet" if "bet" in acts or "allin" in acts else acts[-1]))
        o.postflop_actions = post_actions
        cur_acts = ctx.street_actions(eng.street).get(s.name, [])
        if eng.street == Street.PREFLOP:
            o.last_action = {"open": "raise", "3bet": "3bet", "4bet": "4bet", "allin": "allin", "call": "call",
                             "limp": "limp", "check": "check"}.get(pa, "none")
        else:
            o.last_action = ("allin" if "allin" in cur_acts else "raise" if "raise" in cur_acts else
                             "bet" if "bet" in cur_acts else cur_acts[-1] if cur_acts else "none")
        opps.append(o)

    # starea preflop
    if eng.street == Street.PREFLOP:
        if raises == 0:
            state = "limped" if ctx.limpers else "unopened"
        elif raises == 1:
            state = "hero_opened" if opener == seat.name else "facing_open"
        elif raises == 2:
            state = "facing_3bet"
        else:
            state = "facing_4bet"
        aggressor_seat = next((s for s in eng.seats if s.in_hand and s.bet_this_street >= eng.current_bet - 1e-9 and s.name != seat.name), None)
        if aggressor_seat is not None and aggressor_seat.all_in and raises >= 1:
            state = "facing_shove"
    else:
        state = "postflop"
    hero_was_aggressor = ctx.last_aggressor == seat.name
    sit = Situation(
        hero_cards=(seat.hole[0], seat.hole[1]), board=list(eng.board), hero_position=ctx.positions.get(seat.name, "BTN"),
        n_players=n_players, hero_stack_bb=seat.stack / bb, pot_bb=eng.pot / bb, to_call_bb=legal.get("call", 0.0) / bb,
        hero_bet_bb=seat.bet_this_street / bb, opponents=opps, mode=mode, ante_bb=eng.ante / bb,
        hero_was_aggressor=hero_was_aggressor, preflop_state=state, n_limpers=len(ctx.limpers),
        n_callers=len([c for c in ctx.callers if c != seat.name]), payouts=payouts or [],
        all_stacks_bb=[s.stack / bb for s in eng.seats if s.stack > 0 or s.in_hand] if mode == "mtt" else [],
        iterations=iterations, seed=rng.randrange(1 << 30) if rng else None,
    )
    if mode == "mtt":
        # hero primul in lista de stack-uri (conventia din Advisor._icm_factor)
        others = [s.stack / bb + s.total_invested / bb for j, s in enumerate(eng.seats) if j != i and (s.stack > 0 or s.in_hand)]
        sit.all_stacks_bb = [seat.stack / bb + seat.total_invested / bb] + others
        sit.players_left = len(sit.all_stacks_bb)
        sit.itm_places = len(payouts or [])
    return sit


def recommendation_to_action(rec: Recommendation, eng: HandEngine, i: int) -> Action:
    legal = eng.legal_actions(i)
    bb = eng.bb
    a = rec.action
    if a == "fold":
        return Action(ActionType.CHECK) if "check" in legal else Action(ActionType.FOLD)
    if a == "check":
        return Action(ActionType.CHECK) if "check" in legal else Action(ActionType.CALL)
    if a == "call":
        return Action(ActionType.CALL) if "call" in legal else Action(ActionType.CHECK)
    if a == "allin":
        return Action(ActionType.ALLIN) if "min_raise" in legal else (Action(ActionType.CALL) if "call" in legal else Action(ActionType.CHECK))
    if a in ("bet", "raise"):
        if "min_raise" not in legal:
            return Action(ActionType.CALL) if "call" in legal else Action(ActionType.CHECK)
        total = rec.size_bb * bb
        total = max(legal["min_raise"], min(legal["max_raise"], total))
        return Action(ActionType.RAISE, total)
    return Action(ActionType.CHECK) if "check" in legal else Action(ActionType.FOLD)


class HeroAgent:
    def __init__(self, advisor: Advisor, db: Optional[PlayerDB], mode: str = "cash", payouts: Optional[List[float]] = None,
                 rng: Optional[random.Random] = None, log: Optional[Callable[[str], None]] = None):
        self.advisor = advisor
        self.db = db
        self.mode = mode
        self.payouts = payouts
        self.rng = rng or random.Random()
        self.log = log
        self.decisions = 0

    def act(self, eng: HandEngine, i: int, ctx: HandContext) -> Action:
        sit = build_situation(eng, i, ctx, self.db, self.mode, self.payouts, self.advisor.iterations, self.rng)
        rec = self.advisor.recommend(sit)
        self.decisions += 1
        act = recommendation_to_action(rec, eng, i)
        if self.log:
            self.log(f"  hero {sit.street} {rec.headline()} eq={100*rec.equity:.0f}% -> {act}")
        return act


# ----------------------------------------------------------------------------
# Masa / sesiune
# ----------------------------------------------------------------------------

@dataclass
class SimReport:
    hands: int = 0
    hero_net_bb: float = 0.0
    per_hand: List[float] = field(default_factory=list)
    bot_net_bb: Dict[str, float] = field(default_factory=dict)
    seconds: float = 0.0
    showdowns: int = 0
    showdowns_won: int = 0
    hands_won: int = 0
    vpip_hands: int = 0
    finishes: List[int] = field(default_factory=list)   # turneu: locurile hero

    @property
    def bb_per_100(self) -> float:
        return 100.0 * self.hero_net_bb / self.hands if self.hands else 0.0

    @property
    def std_bb_per_100(self) -> float:
        if len(self.per_hand) < 2:
            return 0.0
        return statistics.pstdev(self.per_hand) * 10.0

    def summary(self) -> str:
        lines = [f"{self.hands} maini in {self.seconds:.1f}s"]
        if self.per_hand:
            lines.append(f"hero: {self.hero_net_bb:+.1f}bb  ({self.bb_per_100:+.1f} bb/100, sd {self.std_bb_per_100:.0f})")
            lines.append(f"maini castigate {self.hands_won}  showdown {self.showdowns_won}/{self.showdowns}  "
                         f"VPIP {100*self.vpip_hands/max(1,self.hands):.0f}%")
        for n, v in sorted(self.bot_net_bb.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {n}: {v:+.1f}bb")
        if self.finishes:
            n = len(self.finishes)
            lines.append(f"turnee: {n}, loc mediu {statistics.mean(self.finishes):.2f}, "
                         f"castigate {sum(1 for f in self.finishes if f == 1)}")
        return "\n".join(lines)


class Table:
    """Masa de cash game: stack-urile se reseteaza la `buyin_bb` la fiecare mana (hero si boti)."""

    def __init__(self, bots: List[str], advisor: Optional[Advisor] = None, db: Optional[PlayerDB] = None,
                 buyin_bb: float = 100.0, sb: float = 0.5, bb: float = 1.0, seed: int = 1,
                 hero_name: str = "hero", log: Optional[Callable[[str], None]] = None, mode: str = "cash"):
        self.rng = random.Random(seed)
        self.db = db if db is not None else PlayerDB(":memory:")
        self.advisor = advisor or Advisor(iterations=500)
        self.hero_name = hero_name
        self.buyin_bb = buyin_bb
        self.sb, self.bb = sb, bb
        self.log = log
        self.mode = mode
        self.hero = HeroAgent(self.advisor, self.db, mode, rng=self.rng, log=log)
        self.players: List[Tuple[str, Optional[Bot]]] = [(hero_name, None)]
        counts: Dict[str, int] = {}
        for b in bots:
            counts[b] = counts.get(b, 0) + 1
            name = f"{b}{counts[b]}"
            self.players.append((name, Bot(PROFILES[b], self.rng)))
        self.seats = [Seat(n, buyin_bb * bb) for n, _ in self.players]
        self.button = 0

    def play_hand(self, report: SimReport) -> HandRecord:
        for s in self.seats:
            s.stack = self.buyin_bb * self.bb
            s.sitting_out = False
        self.button = (self.button + 1) % len(self.seats)
        eng = HandEngine(self.seats, self.button, self.sb, self.bb, rng=self.rng)
        ctx = HandContext(eng)
        hero_idx = next(i for i, s in enumerate(self.seats) if s.name == self.hero_name)
        if self.log:
            self.log(f"--- mana {report.hands + 1}: hero {ctx.positions.get(self.hero_name)} "
                     f"{[s.hole for s in self.seats][hero_idx]}")
        steps = 0
        while not eng.finished and steps < 300:
            i = eng.to_act
            name, bot = self.players[i]
            if bot is None:
                act = self.hero.act(eng, i, ctx)
            else:
                act = bot.act(eng, i, ctx)
            eng.act(act)
            steps += 1
        res = eng.results
        report.hands += 1
        net = res.get(self.hero_name, 0.0) / self.bb
        report.hero_net_bb += net
        report.per_hand.append(net)
        if net > 0:
            report.hands_won += 1
        if self.hero_name in eng.record.went_to_showdown:
            report.showdowns += 1
            if eng.record.winners.get(self.hero_name, 0) > 0:
                report.showdowns_won += 1
        if any(p == self.hero_name and a.type in (ActionType.CALL, ActionType.RAISE, ActionType.BET, ActionType.ALLIN)
               for s, p, a, _ in eng.record.actions if s == Street.PREFLOP):
            report.vpip_hands += 1
        for n, _ in self.players[1:]:
            report.bot_net_bb[n] = report.bot_net_bb.get(n, 0.0) + res.get(n, 0.0) / self.bb
        update_stats_from_hand(self.db, eng.record, ctx.positions, res, self.bb)
        return eng.record

    def run(self, n_hands: int, progress: Optional[Callable[[int, SimReport], None]] = None) -> SimReport:
        report = SimReport()
        t = time.perf_counter()
        for k in range(n_hands):
            self.play_hand(report)
            if progress and (k + 1) % 25 == 0:
                progress(k + 1, report)
        report.seconds = time.perf_counter() - t
        return report


class Tournament:
    """Turneu SNG simplu: blind-urile cresc la fiecare `level_hands` maini, pana ramane un jucator."""

    def __init__(self, bots: List[str], advisor: Optional[Advisor] = None, db: Optional[PlayerDB] = None,
                 start_bb: float = 50.0, level_hands: int = 12, seed: int = 1, payouts: Optional[List[float]] = None,
                 log: Optional[Callable[[str], None]] = None):
        self.rng = random.Random(seed)
        self.db = db if db is not None else PlayerDB(":memory:")
        self.advisor = advisor or Advisor(iterations=400)
        self.payouts = payouts or [50, 30, 20]
        self.start_bb = start_bb
        self.level_hands = level_hands
        self.log = log
        self.hero = HeroAgent(self.advisor, self.db, "mtt", self.payouts, rng=self.rng, log=log)
        self.players: List[Tuple[str, Optional[Bot]]] = [("hero", None)]
        counts: Dict[str, int] = {}
        for b in bots:
            counts[b] = counts.get(b, 0) + 1
            self.players.append((f"{b}{counts[b]}", Bot(PROFILES[b], self.rng)))
        self.levels = [(10, 20, 0), (15, 30, 0), (25, 50, 0), (50, 100, 10), (75, 150, 15), (100, 200, 25),
                       (150, 300, 40), (200, 400, 50), (300, 600, 75), (400, 800, 100), (600, 1200, 150), (1000, 2000, 300)]

    def run_one(self, report: SimReport) -> int:
        chips = self.start_bb * 20
        seats = [Seat(n, chips) for n, _ in self.players]
        button = self.rng.randrange(len(seats))
        hands = 0
        finish_order: List[str] = []
        while True:
            alive = [s for s in seats if s.stack > 0]
            if len(alive) <= 1:
                break
            level = self.levels[min(len(self.levels) - 1, hands // self.level_hands)]
            sb, bb, ante = level
            for s in seats:
                s.sitting_out = s.stack <= 0
            # butonul se muta la urmatorul jucator viu
            for _ in range(len(seats)):
                button = (button + 1) % len(seats)
                if seats[button].stack > 0:
                    break
            eng = HandEngine(seats, button, sb, bb, ante=ante, rng=self.rng)
            if eng.finished:
                break
            ctx = HandContext(eng)
            steps = 0
            while not eng.finished and steps < 300:
                i = eng.to_act
                name, bot = self.players[i]
                act = self.hero.act(eng, i, ctx) if bot is None else bot.act(eng, i, ctx)
                eng.act(act)
                steps += 1
            update_stats_from_hand(self.db, eng.record, ctx.positions, eng.results, bb)
            hands += 1
            for s in seats:
                if s.stack <= 0 and s.name not in finish_order and not s.sitting_out:
                    finish_order.append(s.name)
            if hands > 3000:
                break
        alive = [s for s in seats if s.stack > 0]
        for s in alive:
            finish_order.append(s.name)
        # locul = numarul de jucatori - pozitia in ordinea eliminarii
        n = len(self.players)
        place = n - finish_order.index("hero") if "hero" in finish_order else n
        report.finishes.append(place)
        report.hands += hands
        return place

    def run(self, n_tournaments: int, progress: Optional[Callable[[int, SimReport], None]] = None) -> SimReport:
        report = SimReport()
        t = time.perf_counter()
        for k in range(n_tournaments):
            self.run_one(report)
            if progress:
                progress(k + 1, report)
        report.seconds = time.perf_counter() - t
        return report
