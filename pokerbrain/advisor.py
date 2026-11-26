"""Motorul de decizie: primeste situatia curenta a mainii si produce o recomandare cu procente
(echitate, echitate necesara, EV pe actiune), marimea pariului, incredere si motivatie.

Trateaza cash si turneu (ICM / bubble factor / stack-uri scurte), foloseste profilurile jucatorilor
pentru a estima range-uri si pentru exploatari."""
from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .cards import cards_str
from .evaluator import evaluate, category, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, PAIR
from .ranges import Range, hand_class, class_combos
from .equity import (equity_vs_ranges, analyze_hand, HandAnalysis, top_range, hand_percentile)
from .players import PlayerStats, PRIORS
from . import charts
from .math_tools import (pot_odds, mdf, alpha, bluff_ev, call_ev, spr, icm_required_equity, bubble_factor,
                         outs_to_equity, decision_cost, m_ratio, m_zone, stack_depth_label)


@dataclass
class Opponent:
    name: str = "villain"
    position: str = "BTN"
    stack_bb: float = 100.0
    stats: Optional[PlayerStats] = None
    # ultima actiune pe strada curenta: 'none','check','call','bet','raise','3bet','4bet','allin','limp'
    last_action: str = "none"
    bet_bb: float = 0.0          # suma totala pusa de el pe strada curenta
    preflop_action: str = "none"  # 'open','call','3bet','4bet','limp','allin','check','none'
    postflop_actions: List[str] = field(default_factory=list)  # istoricul pe strazile anterioare: 'bet','check','call','raise'
    in_hand: bool = True

    def stats_or_default(self) -> PlayerStats:
        return self.stats or PlayerStats(name=self.name)


@dataclass
class Situation:
    hero_cards: Tuple[int, int]
    board: List[int] = field(default_factory=list)
    hero_position: str = "BTN"
    n_players: int = 6                 # jucatori la masa (pentru pozitii / charturi)
    hero_stack_bb: float = 100.0
    pot_bb: float = 1.5                # potul total actual, inclusiv pariurile de pe strada curenta
    to_call_bb: float = 0.0            # cat avem de platit
    hero_bet_bb: float = 0.0           # cat am pus deja pe strada curenta
    opponents: List[Opponent] = field(default_factory=list)
    mode: str = "cash"                 # 'cash' sau 'mtt'
    bb_money: float = 1.0              # valoarea unui big blind in bani
    bankroll: float = 0.0
    ante_bb: float = 0.0
    hero_was_aggressor: bool = False   # am fost ultimul agresor pe strada anterioara (c-bet)
    preflop_state: str = "unopened"    # 'unopened','limped','facing_open','facing_3bet','facing_4bet','facing_shove','hero_opened'
    n_limpers: int = 0
    n_callers: int = 0                 # cati au dat call la open inainte de noi
    # turneu
    payouts: List[float] = field(default_factory=list)
    all_stacks_bb: List[float] = field(default_factory=list)   # stack-urile tuturor din turneu (sau masa)
    players_left: int = 0
    itm_places: int = 0
    iterations: int = 1500
    seed: Optional[int] = None

    @property
    def street(self) -> str:
        return {0: "preflop", 3: "flop", 4: "turn", 5: "river"}.get(len(self.board), "preflop")

    def active_opponents(self) -> List[Opponent]:
        return [o for o in self.opponents if o.in_hand]

    def main_villain(self) -> Optional[Opponent]:
        act = self.active_opponents()
        if not act:
            return None
        # agresorul (cel cu cel mai mare pariu), altfel cel mai apropiat
        act_sorted = sorted(act, key=lambda o: (-o.bet_bb, o.last_action in ("bet", "raise", "3bet", "4bet", "allin")))
        return act_sorted[0]

    def effective_stack_bb(self) -> float:
        v = self.main_villain()
        if v is None:
            return self.hero_stack_bb
        return min(self.hero_stack_bb, max(o.stack_bb for o in self.active_opponents()))


@dataclass
class Recommendation:
    action: str                      # 'fold','check','call','bet','raise','allin'
    size_bb: float = 0.0             # pentru bet/raise: suma TOTALA (raise-to) in bb
    equity: float = 0.0              # echitatea vs range-ul estimat (0..1)
    required_equity: float = 0.0     # echitatea necesara (pot odds, ajustata ICM)
    ev_bb: Dict[str, float] = field(default_factory=dict)   # EV estimat pe actiune (in bb)
    confidence: float = 0.5
    reasons: List[str] = field(default_factory=list)
    villain_range: Optional[Range] = None
    villain_range_pct: float = 0.0
    analysis: Optional[HandAnalysis] = None
    costs: Dict[str, float] = field(default_factory=dict)
    alternatives: List[Tuple[str, float]] = field(default_factory=list)
    hand_class: str = ""
    exploits: List[str] = field(default_factory=list)

    def headline(self) -> str:
        a = self.action.upper()
        if self.action in ("bet", "raise") and self.size_bb > 0:
            a += f" {self.size_bb:.1f}bb"
        return a

    def summary(self) -> str:
        lines = [f"{self.headline()}  (incredere {100*self.confidence:.0f}%)",
                 f"echitate {100*self.equity:.1f}%  necesar {100*self.required_equity:.1f}%"]
        if self.ev_bb:
            lines.append("EV: " + "  ".join(f"{k} {v:+.2f}bb" for k, v in sorted(self.ev_bb.items(), key=lambda kv: -kv[1])))
        lines += self.reasons
        return "\n".join(lines)


# ----------------------------------------------------------------------------
# Estimarea range-urilor adversarilor
# ----------------------------------------------------------------------------

def preflop_range_for(opp: Opponent, sit: Situation) -> Range:
    """Range-ul estimat al adversarului dupa actiunea sa preflop si statistici."""
    st = opp.stats_or_default()
    n = sit.n_players
    stack = min(opp.stack_bb, sit.hero_stack_bb)
    a = opp.preflop_action
    if a == "allin":
        if stack <= 20:
            r = st.shove_range(opp.position, stack, n)
        else:
            r = Range.parse("TT+, AQs+, AKo")
    elif a == "4bet":
        r = charts.four_bet_range(opp.position)
        if st.threebet > 0.12:
            r = r.union(top_range(5.0))
    elif a == "3bet":
        r = st.three_bet_range(sit.hero_position, opp.position)
    elif a == "open":
        r = st.open_range(opp.position, n, stack)
    elif a == "call":
        if sit.preflop_state in ("hero_opened",) or sit.hero_was_aggressor:
            r = st.call_open_range(sit.hero_position, opp.position)
        else:
            r = st.call_open_range("CO", opp.position)
    elif a == "limp":
        pct = max(10.0, min(60.0, 100 * (st.vpip - st.pfr) * 1.6))
        r = top_range(pct + 8).minus(top_range(4.0))
    elif a == "check":  # BB check in pot limpat
        r = Range.random_hand().minus(top_range(6.0))
    else:
        # inca nu a actionat: range aleator ponderat cu VPIP-ul
        r = top_range(max(15.0, min(100.0, 100 * st.vpip * 1.3)))
    if not r.weights:
        r = Range.random_hand()
    return r


_WINDOWS = [0b11111 << s for s in range(0, 9)] + [0b1000000001111]  # ferestre de chinta (inclusiv roata)


def quick_bucket(c1: int, c2: int, board: Sequence[int]) -> str:
    """Clasificare rapida a unei combinatii pe board: strong / top / mid / draw / weak_draw / air."""
    cat = category(evaluate([c1, c2] + list(board)))
    r1, r2 = c1 >> 2, c2 >> 2
    board_ranks = [b >> 2 for b in board]
    bmax = max(board_ranks)
    if cat >= TWO_PAIR:
        # doua perechi doar pe board (hero fara pereche) nu e "strong"
        board_cat = category(evaluate(list(board))) if len(board) >= 5 else -1
        if board_cat >= cat and r1 not in board_ranks and r2 not in board_ranks and r1 != r2:
            return "air"
        return "strong"
    if cat == PAIR:
        if r1 == r2:
            return "top" if r1 >= bmax else "mid"
        if (r1 == bmax or r2 == bmax) and bmax in board_ranks:
            return "top"
        if r1 in board_ranks or r2 in board_ranks:
            return "mid"
        return "air"  # pereche doar pe board
    if len(board) >= 5:
        return "air"
    # draw-uri
    suits = [c & 3 for c in (c1, c2)] + [b & 3 for b in board]
    fd = False
    bd = False
    for s in range(4):
        n = suits.count(s)
        hole = (c1 & 3 == s) + (c2 & 3 == s)
        if n == 4 and hole >= 1:
            fd = True
        elif n == 3 and hole == 2 and len(board) == 3:
            bd = True
    mask = (1 << r1) | (1 << r2)
    for b in board_ranks:
        mask |= 1 << b
    hole_mask = (1 << r1) | (1 << r2)
    sd = 0
    for w in _WINDOWS:
        have = mask & w
        if bin(have).count("1") == 4 and have & hole_mask:
            sd += 1
    oesd = sd >= 2
    gut = sd == 1
    if fd or oesd:
        return "draw"
    if gut or bd or (r1 > bmax and r2 > bmax):
        return "weak_draw"
    return "air"


_BUCKET_MULT = {
    "bet":   {"strong": 1.0, "top": 0.85, "mid": 0.35, "draw": 0.75, "weak_draw": 0.35, "air": None},
    "raise": {"strong": 1.0, "top": 0.70, "mid": 0.20, "draw": 0.70, "weak_draw": 0.25, "air": None},
    "call":  {"strong": 0.7, "top": 1.0, "mid": 0.8, "draw": 1.0, "weak_draw": 0.6, "air": 0.12},
    "check": {"strong": 0.45, "top": 0.75, "mid": 0.95, "draw": 0.9, "weak_draw": 1.0, "air": 1.0},
}


def narrow_range_postflop(r: Range, board: Sequence[int], actions: Sequence[str],
                          st: Optional[PlayerStats] = None) -> Range:
    """Ingusteaza range-ul dupa actiunile postflop: pariurile pastreaza mainile tari + draw-uri,
    check/call pastreaza mainile medii si draw-urile. Ponderile se aplica pe clasa (media combinatiilor)."""
    if not board or not actions:
        return r
    af = st.af if st else 2.0
    bluffiness = max(0.1, min(0.6, 0.15 + 0.08 * (af - 2.0)))
    out: Dict[str, float] = {}
    board = list(board)
    bset = set(board)
    acts = [a for a in actions if a in _BUCKET_MULT]
    if not acts:
        return r
    for h, w in r.weights.items():
        if w <= 0:
            continue
        combos = [c for c in class_combos(h) if c[0] not in bset and c[1] not in bset]
        if not combos:
            continue
        total = 0.0
        for c1, c2 in combos:
            bucket = quick_bucket(c1, c2, board)
            m = 1.0
            for act in acts:
                v = _BUCKET_MULT[act][bucket]
                m *= bluffiness if v is None else v
            total += m
        out[h] = w * total / len(combos)
    nr = Range(out)
    if nr.combos() < 4:
        return r
    return nr


# ----------------------------------------------------------------------------
# Advisor
# ----------------------------------------------------------------------------

class Advisor:
    def __init__(self, iterations: int = 1500):
        self.iterations = iterations

    # ------------------------------------------------------------ public
    def recommend(self, sit: Situation) -> Recommendation:
        rng = random.Random(sit.seed)
        hc = hand_class(*sit.hero_cards)
        if sit.street == "preflop":
            rec = self._preflop(sit, rng)
        else:
            rec = self._postflop(sit, rng)
        rec.hand_class = hc
        self._attach_costs(rec, sit)
        v = sit.main_villain()
        if v and v.stats:
            rec.exploits = v.stats.exploits()[:3]
        return rec

    # ------------------------------------------------------------ helpers
    def _attach_costs(self, rec: Recommendation, sit: Situation) -> None:
        amount = 0.0
        if rec.action == "call":
            amount = sit.to_call_bb
        elif rec.action in ("bet", "raise"):
            amount = max(0.0, rec.size_bb - sit.hero_bet_bb)
        elif rec.action == "allin":
            amount = sit.hero_stack_bb
        rec.costs = decision_cost(amount, sit.bb_money, sit.hero_stack_bb + sit.hero_bet_bb, sit.bankroll)
        if amount > 0:
            c = rec.costs
            txt = f"cost: {c['bb']:.1f}bb = {c['money']:.2f} ({c['pct_stack']:.0f}% din stack"
            if sit.bankroll > 0:
                txt += f", {c['pct_bankroll']:.2f}% din bankroll"
            rec.reasons.append(txt + ")")

    def _icm_factor(self, sit: Situation) -> float:
        """Bubble factor: 1.0 in cash; in turneu din ICM daca avem stack-urile, altfel euristic."""
        if sit.mode != "mtt":
            return 1.0
        v = sit.main_villain()
        if sit.payouts and sit.all_stacks_bb and len(sit.all_stacks_bb) >= 2:
            stacks = list(sit.all_stacks_bb)
            hero_i = 0
            vil_i = 1
            if v is not None:
                # cautam stack-ul cel mai apropiat de al villain-ului
                vil_i = min(range(len(stacks)), key=lambda i: abs(stacks[i] - v.stack_bb) if i != hero_i else 1e9)
            try:
                return min(3.0, bubble_factor(stacks, sit.payouts, hero_i, vil_i))
            except Exception:
                pass
        # euristic: cat de aproape de bani
        if sit.players_left and sit.itm_places:
            ratio = sit.players_left / max(1, sit.itm_places)
            if ratio <= 1.0:
                return 1.35  # in bani, scara de plati
            if ratio <= 1.25:
                return 1.6   # bubble
            if ratio <= 2.0:
                return 1.3
            return 1.1
        return 1.15

    def _equity(self, sit: Situation, ranges: List[Range], rng: random.Random) -> float:
        if not ranges:
            ranges = [Range.random_hand()]
        res = equity_vs_ranges(sit.hero_cards, ranges, sit.board, self.iterations, rng)
        return res.equity

    @staticmethod
    def _conf(margin: float, scale: float = 0.12) -> float:
        return max(0.5, min(0.97, 0.5 + abs(margin) / scale * 0.47))

    # ------------------------------------------------------------ preflop
    def _preflop(self, sit: Situation, rng: random.Random) -> Recommendation:
        hc = hand_class(*sit.hero_cards)
        pos = sit.hero_position
        n = sit.n_players
        eff = sit.effective_stack_bb()
        opps = sit.active_opponents()
        villain = sit.main_villain()
        vst = villain.stats_or_default() if villain else PlayerStats("villain")
        bf = self._icm_factor(sit)
        reasons: List[str] = []
        depth = stack_depth_label(eff)
        reasons.append(f"{hc} din {pos}, stack efectiv {eff:.0f}bb ({depth}), {sit.mode}")
        if sit.mode == "mtt" and sit.ante_bb > 0:
            m = m_ratio(sit.hero_stack_bb, 0.5, 1.0, sit.ante_bb, n)
            reasons.append(f"M = {m:.1f}: zona {m_zone(m)}")
        pct = hand_percentile(hc)

        # ---- stack scurt: push / fold
        if eff <= 15 and sit.preflop_state in ("unopened", "limped"):
            pr = charts.push_range(pos, eff, n, ante=sit.ante_bb > 0)
            # ajustare: blind-urile dau fold des -> push mai larg
            if villain and vst.fold_to_steal > 0.72:
                pr = top_range(min(100.0, pr.percent() * 1.2))
            if bf > 1.3:
                pr = top_range(max(2.0, pr.percent() / (bf ** 0.7)))
            in_range = pr.contains(hc)
            if sit.n_limpers:
                in_range = top_range(pr.percent() * 0.8).contains(hc)
            if pos == "BB" and not sit.n_limpers:
                return Recommendation("check", reasons=reasons + ["BB fara actiune: check"], confidence=0.9)
            eq = self._equity(sit, [vst.call_open_range(pos, villain.position) if villain else top_range(25)], rng)
            rec = Recommendation("allin" if in_range else "fold", size_bb=sit.hero_stack_bb if in_range else 0,
                                 equity=eq, required_equity=0.0, reasons=reasons)
            rec.reasons.append(f"push/fold: range de shove {pr.percent():.0f}% din {pos} la {eff:.0f}bb"
                               + (f", ICM x{bf:.2f}" if bf > 1.05 else ""))
            rec.reasons.append(f"{hc} este top {pct:.0f}% -> {'in' if in_range else 'afara din'} range")
            rec.villain_range = pr
            rec.villain_range_pct = pr.percent()
            rec.confidence = self._conf(pr.percent() - pct, 15)
            rec.ev_bb = {"allin": round((eq - 0.5) * 2 * min(eff, 15) + 1.5 * 0.6, 2) if in_range else -0.3, "fold": 0.0}
            return rec

        # ---- facem fata unui all-in
        if sit.preflop_state == "facing_shove" or (villain and villain.preflop_action == "allin"):
            vr = preflop_range_for(villain, sit) if villain else top_range(30)
            others = [preflop_range_for(o, sit) for o in opps if o is not villain and o.last_action in ("call", "allin")]
            eq = self._equity(sit, [vr] + others, rng)
            po = pot_odds(sit.to_call_bb, sit.pot_bb)
            req = icm_required_equity(po, bf)
            rec = Recommendation("call" if eq > req + 0.01 else "fold", equity=eq, required_equity=req, reasons=reasons)
            rec.villain_range, rec.villain_range_pct = vr, vr.percent()
            rec.ev_bb = {"call": round(call_ev(eq, sit.to_call_bb, sit.pot_bb), 2), "fold": 0.0}
            rec.reasons.append(f"vs shove: range estimat {vr.percent():.0f}% (PFR {100*vst.pfr:.0f}%), pot odds {100*po:.0f}%"
                               + (f", ICM -> necesar {100*req:.0f}%" if bf > 1.05 else ""))
            rec.confidence = self._conf(eq - req, 0.10)
            return rec

        # ---- nimeni nu a deschis (sau doar limp-uri)
        if sit.preflop_state in ("unopened", "limped"):
            if pos == "BB" and sit.n_limpers == 0:
                return Recommendation("check", reasons=reasons + ["nimeni nu a ridicat: check"], confidence=0.95)
            orange = charts.open_range(pos, n, eff)
            steal_bonus = 1.0
            if pos in ("CO", "BTN", "SB") and opps:
                blinds = [o for o in opps if o.position in ("SB", "BB")]
                if blinds:
                    avg_fts = sum(o.stats_or_default().fold_to_steal for o in blinds) / len(blinds)
                    steal_bonus = 0.8 + 0.5 * (avg_fts - 0.5)  # 0.8..1.05 .. 1.3
                    if abs(steal_bonus - 1.0) > 0.08:
                        reasons.append(f"blinds dau fold la steal {100*avg_fts:.0f}% -> range de open x{steal_bonus:.2f}")
            if sit.n_limpers:
                # izolare: mai strans vs multi limperi, mai larg vs un fish
                limper_fish = villain is not None and vst.archetype().startswith("fish")
                steal_bonus *= (1.15 if limper_fish else 0.85) * (0.9 ** max(0, sit.n_limpers - 1))
            if bf > 1.3:
                steal_bonus /= bf ** 0.5
            if abs(steal_bonus - 1.0) > 0.03:
                orange = top_range(max(3.0, min(90.0, orange.percent() * steal_bonus)))
            in_range = orange.contains(hc) and orange.weight(hc) >= 0.5
            size = 2.5 if n <= 6 else 2.2
            if pos == "SB":
                size = 3.0
            if eff < 30:
                size = 2.2
            size += 1.0 * sit.n_limpers
            if sit.n_limpers and eff <= 25:
                size = min(size, sit.hero_stack_bb)
            eq = self._equity(sit, [top_range(35)] if opps else [Range.random_hand()], rng)
            if in_range:
                action = "raise"
                if sit.n_limpers and eff <= 12:
                    action = "allin"
            else:
                action = "fold" if pos != "BB" else "check"
            rec = Recommendation(action, size_bb=size if action == "raise" else (sit.hero_stack_bb if action == "allin" else 0),
                                 equity=eq, required_equity=0.0, reasons=reasons)
            rec.villain_range, rec.villain_range_pct = orange, orange.percent()
            rec.reasons.append(f"range de open din {pos}: {orange.percent():.0f}%; {hc} este top {pct:.0f}% "
                               f"-> {'DESCHIDE' if in_range else 'fold'}")
            if sit.n_limpers:
                rec.reasons.append(f"{sit.n_limpers} limper(i): izoleaza cu {size:.1f}bb")
            rec.confidence = self._conf(orange.percent() - pct, 12)
            rec.ev_bb = {"raise": round(0.08 * (orange.percent() - pct) / 10 + 0.1, 2) if in_range else -0.2, "fold": 0.0}
            return rec

        # ---- facem fata unui open (sau open + calleri)
        if sit.preflop_state == "facing_open" and villain:
            opener_pos = villain.position
            vr = preflop_range_for(villain, sit)
            three = vst.three_bet_range(opener_pos, pos)
            call_r = vst.call_open_range(opener_pos, pos)
            # exploatari
            adj: List[str] = []
            if vst.fold_to_3bet > 0.62 and vst.fold_to_3bet_opp >= 6:
                three = top_range(min(30.0, three.percent() * 1.35)).union(three)
                adj.append(f"da fold la 3-bet {100*vst.fold_to_3bet:.0f}% -> 3-bet mai larg")
            elif vst.fold_to_3bet < 0.40 and vst.fold_to_3bet_opp >= 6:
                three = three.minus(Range.parse("A5s-A2s, 76s, 65s, 87s, K9s, Q9s, J9s, T9s, 98s, KJs, KQs:0.3"))
                adj.append("nu da fold la 3-bet -> 3-bet doar valoare, call mai larg")
                call_r = call_r.union(Range.parse("KQs, KJs, AJs, ATs, A5s-A2s, 76s, 65s, 87s, 98s, T9s"))
            if vst.pfr > 0.28 and vst.pfr_opp >= 12:
                three = three.union(Range.parse("TT, 99, AJs, ATs, KQs, AQo, AJo:0.5, KQo:0.5"))
                adj.append(f"deschide larg ({100*vst.pfr:.0f}%) -> 3-bet pentru valoare mai larg")
            if sit.n_callers >= 1:
                # squeeze: mai mult valoare, mai putin bluff; call mai larg (multiway, odds)
                three = three.minus(Range.parse("A5s-A2s, 76s, 65s, 87s, K9s, Q9s, J9s, T9s, 98s"))
                call_r = call_r.union(Range.parse("22+, A2s+, K9s+, Q9s+, J9s+, T8s+, 97s+, 86s+, 75s+, 65s, 54s"))
                adj.append(f"{sit.n_callers} caller(i): squeeze doar cu valoare, call larg cu maini speculative")
            if eff < 35:
                call_r = call_r.minus(Range.parse("22-55, 54s, 65s, 75s, 76s, 86s, 97s, J9s, Q9s, K9s, T8s"))
                adj.append("stack sub 35bb: fara call-uri speculative (set-mining neprofitabil)")
                if eff <= 25:
                    three = top_range(min(20.0, charts.resteal_range(opener_pos, eff).percent())).union(Range.parse("QQ+, AK"))
                    adj.append("stack <= 25bb: 3-bet = all-in (resteal)")
            if bf > 1.25:
                three = three.minus(Range.parse("A5s-A2s, 76s, 65s, 87s, 98s, T9s, K9s, Q9s, J9s, KJs:0.5"))
                call_r = top_range(max(3.0, call_r.percent() / bf ** 0.6))
                adj.append(f"presiune ICM x{bf:.2f}: evita all-in-urile marginale")
            eq = self._equity(sit, [vr], rng)
            po = pot_odds(sit.to_call_bb, sit.pot_bb)
            req = icm_required_equity(po, bf)
            ip = pos in ("CO", "BTN") or (opener_pos in ("SB",) and pos == "BB")
            raise_to = (3.0 if ip else 3.6) * villain.bet_bb + villain.bet_bb * 0.0 + (1.0 * sit.n_callers)
            if eff <= 25:
                raise_to = sit.hero_stack_bb
            raise_to = min(raise_to, sit.hero_stack_bb + sit.hero_bet_bb)
            if three.contains(hc) and three.weight(hc) >= 0.5:
                action, size = ("allin" if raise_to >= sit.hero_stack_bb else "raise"), raise_to
                why = f"{hc} in range-ul de 3-bet ({three.percent():.0f}%)"
            elif call_r.contains(hc) and call_r.weight(hc) >= 0.5 and eq >= req * 0.9:
                action, size = "call", 0.0
                why = f"{hc} in range-ul de call ({call_r.percent():.0f}%), echitate {100*eq:.0f}% vs necesar {100*req:.0f}%"
            elif eq > req + 0.12 and pos == "BB":
                action, size = "call", 0.0
                why = f"BB: pot odds bune ({100*po:.0f}%), echitate {100*eq:.0f}%"
            else:
                action, size = "fold", 0.0
                why = f"{hc} nu e in range-ul de 3-bet/call vs open din {opener_pos} (range estimat {vr.percent():.0f}%)"
            rec = Recommendation(action, size_bb=size, equity=eq, required_equity=req, reasons=reasons)
            rec.villain_range, rec.villain_range_pct = vr, vr.percent()
            rec.reasons.append(f"range-ul lui {villain.name}: {vr.percent():.0f}% (PFR {100*vst.pfr:.0f}%, {vst.archetype()})")
            rec.reasons.append(why)
            rec.reasons += adj
            fe = vst.fold_to_3bet
            rec.ev_bb = {
                "call": round(call_ev(eq, sit.to_call_bb, sit.pot_bb) * 0.9, 2),
                "3bet": round(bluff_ev(raise_to - sit.hero_bet_bb, sit.pot_bb, fe, max(0.0, eq - 0.08)) * 0.5, 2),
                "fold": 0.0,
            }
            rec.confidence = self._conf(eq - req, 0.12) if action != "fold" else self._conf(req - eq + 0.05, 0.15)
            return rec

        # ---- am deschis si primim 3-bet / 4-bet
        if sit.preflop_state in ("facing_3bet", "facing_4bet") and villain:
            vr = preflop_range_for(villain, sit)
            eq = self._equity(sit, [vr], rng)
            po = pot_odds(sit.to_call_bb, sit.pot_bb)
            req = icm_required_equity(po, bf)
            if sit.preflop_state == "facing_3bet":
                four = charts.four_bet_range(pos)
                call_r = charts.call_vs_3bet_range(pos)
                adj = []
                if vst.threebet > 0.11 and vst.threebet_opp >= 10:
                    four = four.union(Range.parse("JJ, TT:0.5, AQs, AQo:0.5, A5s-A4s, KQs:0.5"))
                    call_r = call_r.union(Range.parse("99-66, AJs, ATs, KQs, KJs, QJs, JTs, T9s, 98s, AQo, AJo"))
                    adj.append(f"3-bet des ({100*vst.threebet:.0f}%) -> 4-bet light si call mai larg")
                if vst.fold_to_4bet > 0.6 and vst.fold_to_4bet_opp >= 4:
                    four = four.union(Range.parse("A5s-A2s, KJs, QJs, AJo:0.5"))
                    adj.append("da fold la 4-bet des -> 4-bet bluff")
                if eff <= 40:
                    four = four.union(Range.parse("JJ, TT, AQs")) if eff <= 30 else four
                    call_r = call_r.minus(Range.parse("22-66, 54s, 65s, 76s, 87s, 98s, T9s, JTs"))
                    adj.append("stack scurt: 4-bet = all-in, fara call-uri speculative")
                if bf > 1.25:
                    four = four.minus(Range.parse("A5s-A2s, KQs, AQs:0.5, KJs, QJs"))
                    adj.append(f"ICM x{bf:.2f}: 4-bet doar cu premium")
                size = min(sit.hero_stack_bb + sit.hero_bet_bb, (2.3 if pos in ("CO", "BTN") else 2.5) * villain.bet_bb)
                if eff <= 45:
                    size = sit.hero_stack_bb + sit.hero_bet_bb
                if four.contains(hc) and four.weight(hc) >= 0.5:
                    action = "allin" if size >= sit.hero_stack_bb + sit.hero_bet_bb - 1e-9 else "raise"
                    why = f"{hc} in range-ul de 4-bet ({four.percent():.0f}%)"
                elif call_r.contains(hc) and call_r.weight(hc) >= 0.5 and eq >= req * 0.85:
                    action, size = "call", 0.0
                    why = f"{hc} in range-ul de call vs 3-bet ({call_r.percent():.0f}%), echitate {100*eq:.0f}%"
                else:
                    action, size = "fold", 0.0
                    why = f"{hc}: fold vs 3-bet (range 3-bet estimat {vr.percent():.0f}%)"
                rec = Recommendation(action, size_bb=size if action != "call" else 0.0, equity=eq, required_equity=req,
                                     reasons=reasons + [f"3-bet de la {villain.name}: range {vr.percent():.0f}% (3B {100*vst.threebet:.0f}%)", why] + adj)
                rec.ev_bb = {"call": round(call_ev(eq, sit.to_call_bb, sit.pot_bb) * 0.85, 2),
                             "4bet": round(bluff_ev(size - sit.hero_bet_bb, sit.pot_bb, vst.fold_to_4bet, max(0.0, eq - 0.1)) * 0.5, 2),
                             "fold": 0.0}
            else:  # facing 4-bet
                five = Range.parse("KK+, AKs, AKo:0.6, QQ:0.5")
                call5 = Range.parse("QQ:0.5, JJ:0.3, AKo:0.4, AQs:0.3")
                if vst.threebet > 0.12:
                    five = five.union(Range.parse("QQ, AKo, JJ:0.5"))
                if bf > 1.25:
                    five = Range.parse("KK+, AKs:0.7")
                if five.contains(hc) and five.weight(hc) >= 0.5:
                    action, size = "allin", sit.hero_stack_bb + sit.hero_bet_bb
                    why = f"{hc}: 5-bet all-in"
                elif call5.contains(hc) and eq >= req:
                    action, size = "call", 0.0
                    why = f"{hc}: call vs 4-bet (pot odds {100*po:.0f}%, echitate {100*eq:.0f}%)"
                else:
                    action, size = "fold", 0.0
                    why = f"{hc}: fold vs 4-bet (range 4-bet estimat {vr.percent():.0f}%)"
                rec = Recommendation(action, size_bb=size, equity=eq, required_equity=req,
                                     reasons=reasons + [f"4-bet de la {villain.name}: range {vr.percent():.0f}%", why])
                rec.ev_bb = {"call": round(call_ev(eq, sit.to_call_bb, sit.pot_bb) * 0.85, 2), "fold": 0.0}
            rec.villain_range, rec.villain_range_pct = vr, vr.percent()
            rec.confidence = self._conf(eq - req, 0.12)
            return rec

        # fallback: evaluare pe echitate
        ranges = [preflop_range_for(o, sit) for o in opps] or [Range.random_hand()]
        eq = self._equity(sit, ranges, rng)
        po = pot_odds(sit.to_call_bb, sit.pot_bb)
        req = icm_required_equity(po, bf)
        action = "call" if eq > req and sit.to_call_bb > 0 else ("check" if sit.to_call_bb == 0 else "fold")
        rec = Recommendation(action, equity=eq, required_equity=req, reasons=reasons + [f"echitate {100*eq:.0f}% vs necesar {100*req:.0f}%"])
        rec.ev_bb = {"call": round(call_ev(eq, sit.to_call_bb, sit.pot_bb), 2), "fold": 0.0}
        rec.confidence = self._conf(eq - req)
        return rec

    # ------------------------------------------------------------ postflop
    def _postflop(self, sit: Situation, rng: random.Random) -> Recommendation:
        opps = sit.active_opponents()
        villain = sit.main_villain()
        vst = villain.stats_or_default() if villain else PlayerStats("villain")
        bf = self._icm_factor(sit)
        an = analyze_hand(sit.hero_cards, sit.board)
        hc = hand_class(*sit.hero_cards)
        street = sit.street
        cards_to_come = 5 - len(sit.board)
        reasons: List[str] = [f"{street}: {cards_str(sit.hero_cards, True)} pe [{cards_str(sit.board, True)}] -> {an.made_name}"
                              + (f" ({', '.join(an.notes)})" if an.notes else "")]

        # range-urile adversarilor
        ranges: List[Range] = []
        for o in opps:
            r = preflop_range_for(o, sit)
            acts = list(o.postflop_actions)
            if o.last_action in ("bet", "raise", "check", "call"):
                acts.append(o.last_action)
            r = narrow_range_postflop(r, sit.board, acts, o.stats)
            ranges.append(r)
        vr = ranges[0] if ranges else Range.random_hand()
        eq = self._equity(sit, ranges, rng)
        n_opp = max(1, len(opps))
        pot = sit.pot_bb
        to_call = sit.to_call_bb
        eff = sit.effective_stack_bb()
        stack_behind = sit.hero_stack_bb
        s_p_r = spr(eff, max(0.01, pot - to_call)) if street == "flop" else spr(eff, max(0.01, pot))
        reasons.append(f"echitate {100*eq:.0f}% vs {n_opp} range(uri) (principal {vr.percent():.0f}%), "
                       f"SPR {s_p_r:.1f}, draw outs {an.outs}")
        if sit.mode == "mtt" and bf > 1.05:
            reasons.append(f"presiune ICM: bubble factor {bf:.2f}")

        ev: Dict[str, float] = {}
        multiway_pen = 0.85 ** (n_opp - 1)

        if to_call > 0:
            # ---------------- facem fata unui pariu
            po = pot_odds(to_call, pot)
            req = icm_required_equity(po, bf)
            # implied odds pentru draw-uri cand mai sunt carti de venit si stack-uri adanci
            implied = 0.0
            if cards_to_come and an.outs >= 4 and stack_behind - to_call > pot:
                implied = min(0.08, 0.02 * an.outs / 4 * min(2.0, (stack_behind - to_call) / max(pot, 1)) / 2)
            # reverse implied odds pe maini medii fara draw
            rio = 0.03 if (an.made_category == PAIR and not an.top_pair and not an.overpair and an.outs < 4) else 0.0
            ev_call = call_ev(eq, to_call, pot) * (0.95 if cards_to_come else 1.0) + implied * pot - rio * pot
            ev["fold"] = 0.0
            ev["call"] = round(ev_call, 2)
            # raise
            fold_eq = vst.fold_to_raise_post if street != "river" else vst.fold_to_raise_post * 0.9
            fold_eq *= multiway_pen
            raise_to = max(to_call + sit.hero_bet_bb + (pot), min(stack_behind + sit.hero_bet_bb, 3.0 * (to_call + sit.hero_bet_bb) + (pot - to_call - sit.hero_bet_bb) * 0.5))
            raise_to = min(raise_to, stack_behind + sit.hero_bet_bb)
            eq_called = max(0.0, eq - (0.10 if street != "river" else 0.15))
            if an.made_category >= TWO_PAIR or an.set_or_better:
                eq_called = max(eq_called, eq - 0.04)
            ev_raise = bluff_ev(raise_to - sit.hero_bet_bb, pot, fold_eq, eq_called)
            ev["raise"] = round(ev_raise * 0.85, 2)
            if stack_behind + sit.hero_bet_bb <= raise_to * 1.6 and stack_behind > to_call:
                ev["allin"] = round(bluff_ev(stack_behind, pot, fold_eq * 1.1, eq_called) * 0.85, 2)

            best = max(ev, key=ev.get)
            # praguri de siguranta: nu da raise cu echitate mica pe river
            if best in ("raise", "allin") and street == "river" and eq < 0.55 and fold_eq < 0.55:
                best = "call" if ev["call"] > 0 else "fold"
            if best in ("raise", "allin") and eq < req and an.outs < 8:
                best = "call" if ev["call"] > 0 else "fold"
            if best == "call" and eq < req and implied == 0:
                best = "fold"
            size = raise_to if best == "raise" else (stack_behind + sit.hero_bet_bb if best == "allin" else 0.0)
            rec = Recommendation(best, size_bb=size, equity=eq, required_equity=req, ev_bb=ev, reasons=reasons)
            rec.reasons.append(f"de platit {to_call:.1f}bb in pot {pot:.1f}bb: pot odds {100*po:.0f}%"
                               + (f", cu ICM necesar {100*req:.0f}%" if bf > 1.05 else "")
                               + (f", implied odds +{100*implied:.0f}%" if implied else ""))
            if best in ("raise", "allin"):
                rec.reasons.append(f"raise: fold equity estimat {100*fold_eq:.0f}% (fold-to-raise {100*vst.fold_to_raise_post:.0f}%), "
                                   f"echitate daca e platit ~{100*eq_called:.0f}%")
            elif best == "call":
                rec.reasons.append("call: echitatea depaseste echitatea necesara" if eq >= req else
                                   "call: pe baza implied odds (draw puternic, stack-uri adanci)")
            else:
                rec.reasons.append(f"fold: {100*eq:.0f}% < {100*req:.0f}% necesar si raise-ul nu e profitabil")
            rec.confidence = self._conf(eq - req if best != "raise" else ev["raise"] - max(ev["call"], 0), 0.12)
            rec.villain_range, rec.villain_range_pct = vr, vr.percent()
            rec.analysis = an
            return rec

        # ---------------- nimeni nu a pariat: check sau bet
        if sit.hero_was_aggressor:
            fold_base = vst.fold_to_cbet
        else:
            fold_base = vst.fold_to_bet_post
        if street == "river":
            fold_base *= 0.9
        ev["check"] = round(eq * pot * (0.92 if villain and villain.position != "BB" else 1.0) - (0.0 if street == "river" else 0.0), 2)
        # realizarea echitatii la check: pierdem putin OOP
        check_realization = 0.85 if cards_to_come else 1.0
        ev["check"] = round(eq * pot * check_realization, 2)
        sizes = {"bet 33%": 0.33, "bet 66%": 0.66, "bet 100%": 1.0}
        if street == "river" or an.made_category >= STRAIGHT:
            sizes["bet 150%"] = 1.5
        if eff <= pot * 1.6:
            sizes["allin"] = eff / pot if pot > 0 else 1.0
        best_bet_key, best_bet_ev, best_bet_size = None, -1e9, 0.0
        for key, frac in sizes.items():
            b = min(stack_behind, pot * frac)
            if b <= 0:
                continue
            # fold equity creste cu marimea pariului (relativ la alpha), scade multiway
            fe = fold_base * (0.75 + 0.5 * min(1.0, frac / 0.66)) * multiway_pen
            fe = max(0.05, min(0.85, fe))
            # cand suntem platiti, range-ul lui e mai tare
            eq_called = max(0.0, eq - 0.07 - 0.05 * frac)
            if an.made_category >= TWO_PAIR or an.set_or_better:
                eq_called = max(eq_called, eq - 0.03)
            e = bluff_ev(b, pot, fe, eq_called)
            if cards_to_come and an.outs >= 8 and eq_called < 0.5:
                e += 0.05 * pot  # semi-bluff: pastram sansa de a lovi
            # pariu subtire pentru valoare: penalizam cand suntem rar platiti de maini mai slabe
            if eq_called < 0.42 and fe < 0.4:
                e -= 0.08 * pot * frac
            if e > best_bet_ev:
                best_bet_key, best_bet_ev, best_bet_size = key, e, b
        if best_bet_key:
            ev[best_bet_key] = round(best_bet_ev, 2)
        best = max(ev, key=ev.get)
        # protectie: cu maini foarte puternice pariem (nu dam check mereu), exceptand slowplay vs maniac
        if an.made_category >= TWO_PAIR and best == "check" and best_bet_key and not (vst.af >= 3.5 and n_opp == 1):
            if best_bet_ev > ev["check"] - 0.15 * pot:
                best = best_bet_key
        if best.startswith("bet") or best == "allin":
            action = "allin" if best == "allin" else "bet"
            size = best_bet_size + sit.hero_bet_bb
        else:
            action, size = "check", 0.0
        rec = Recommendation(action, size_bb=size, equity=eq, required_equity=0.0, ev_bb=ev, reasons=reasons)
        if action != "check":
            kind = "valoare" if eq >= 0.6 else ("semi-bluff" if an.outs >= 6 else "bluff")
            fe_used = max(0.05, min(0.85, fold_base * (0.75 + 0.5 * min(1.0, (best_bet_size / max(pot, 0.01)) / 0.66)) * multiway_pen))
            rec.reasons.append(f"{best} ({kind}): fold equity ~{100*fe_used:.0f}% "
                               f"(fold-to-{'cbet' if sit.hero_was_aggressor else 'bet'} {100*fold_base:.0f}%), alpha {100*alpha(best_bet_size, pot):.0f}%")
        else:
            rec.reasons.append("check: pariul nu aduce EV suplimentar (echitate medie, putin fold equity)"
                               if eq < 0.6 else "check: controlul potului / inducem bluff-uri")
        rec.confidence = self._conf((max(ev.values()) - sorted(ev.values())[-2]) if len(ev) > 1 else 0.1, 0.25 * max(pot, 1))
        rec.villain_range, rec.villain_range_pct = vr, vr.percent()
        rec.analysis = an
        return rec
