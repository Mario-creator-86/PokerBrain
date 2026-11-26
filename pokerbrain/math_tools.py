"""Matematica de poker: pot odds, MDF, alpha, SPR, EV, ICM, bubble factor, bankroll."""
from __future__ import annotations
import itertools
import math
from dataclasses import dataclass
from typing import Dict, List, Sequence


# ----------------------------------------------------------------------------
# Odds si frecvente
# ----------------------------------------------------------------------------

def pot_odds(to_call: float, pot_before_call: float) -> float:
    """Echitatea minima necesara pentru un call profitabil (ignorand implied odds).
    pot_before_call = potul existent inclusiv pariul adversarului."""
    if to_call <= 0:
        return 0.0
    return to_call / (pot_before_call + to_call)


def pot_odds_ratio(to_call: float, pot_before_call: float) -> str:
    if to_call <= 0:
        return "-"
    return f"{pot_before_call / to_call:.1f}:1"


def mdf(bet: float, pot_before_bet: float) -> float:
    """Minimum Defense Frequency: cat de des trebuie sa continuam ca adversarul sa nu profite bluffing."""
    if bet <= 0:
        return 1.0
    return pot_before_bet / (pot_before_bet + bet)


def alpha(bet: float, pot_before_bet: float) -> float:
    """Frecventa de fold necesara pentru ca un bluff pur sa fie break-even."""
    if bet <= 0:
        return 0.0
    return bet / (pot_before_bet + bet)


def bluff_ev(bet: float, pot: float, fold_freq: float, equity_when_called: float = 0.0) -> float:
    """EV al unui pariu (semi)bluff: fold_freq*pot + (1-fold_freq)*(eq*(pot+2*bet) - bet)."""
    called = 1.0 - fold_freq
    return fold_freq * pot + called * (equity_when_called * (pot + 2 * bet) - bet)


def call_ev(equity: float, to_call: float, pot_before_call: float) -> float:
    """EV al unui call (presupunand ca nu mai sunt pariuri)."""
    return equity * (pot_before_call + to_call) - to_call


def spr(effective_stack: float, pot: float) -> float:
    return effective_stack / pot if pot > 0 else float("inf")


def implied_odds_needed(to_call: float, pot_before_call: float, equity: float) -> float:
    """Cat trebuie sa mai castigam pe strazile urmatoare pentru ca un call cu echitate insuficienta sa fie corect."""
    if equity <= 0:
        return float("inf")
    needed_total = to_call / equity - to_call  # potul total necesar la castig
    return max(0.0, needed_total - pot_before_call)


def outs_to_equity(outs: int, cards_to_come: int) -> float:
    """Probabilitatea de a lovi un out (47 necunoscute pe flop, 46 pe turn)."""
    if cards_to_come == 2:
        return 1 - ((47 - outs) / 47) * ((46 - outs) / 46)
    if cards_to_come == 1:
        return outs / 46
    return 0.0


def rule_of_two_and_four(outs: int, cards_to_come: int) -> float:
    return min(1.0, outs * (0.04 if cards_to_come == 2 else 0.02))


def raise_fold_equity_needed(raise_size: float, pot_before_raise: float, to_call: float,
                             equity_when_called: float) -> float:
    """Frecventa de fold minima pentru ca un raise sa fie break-even."""
    ev_called = equity_when_called * (pot_before_raise + raise_size + raise_size - to_call) - raise_size
    win_if_fold = pot_before_raise
    if win_if_fold - ev_called <= 0:
        return 0.0
    return max(0.0, min(1.0, -ev_called / (win_if_fold - ev_called)))


# ----------------------------------------------------------------------------
# Turnee: ICM, bubble factor, M
# ----------------------------------------------------------------------------

def icm(stacks: Sequence[float], payouts: Sequence[float]) -> List[float]:
    """Malmuth-Harville ICM: valoarea in bani a fiecarui stack. Exact pentru <= 9 jucatori."""
    n = len(stacks)
    payouts = list(payouts)[:n] + [0.0] * max(0, n - len(payouts))
    total = sum(stacks)
    if total <= 0:
        return [0.0] * n
    values = [0.0] * n

    def rec(remaining: List[int], place: int, prob: float):
        if place >= len(payouts) or prob < 1e-12 or not remaining:
            return
        if payouts[place] == 0 and all(p == 0 for p in payouts[place:]):
            return
        tot = sum(stacks[i] for i in remaining)
        for i in remaining:
            p = prob * stacks[i] / tot if tot > 0 else 0.0
            values[i] += p * payouts[place]
            rest = [j for j in remaining if j != i]
            rec(rest, place + 1, p)

    if n <= 10:
        rec(list(range(n)), 0, 1.0)
    else:
        # aproximare: doar primele 3 locuri explicit, restul proportional
        for i in range(n):
            p1 = stacks[i] / total
            values[i] = p1 * payouts[0]
            for j in range(n):
                if j == i:
                    continue
                p2 = (stacks[j] / total) * (stacks[i] / (total - stacks[j]))
                values[i] += p2 * (payouts[1] if len(payouts) > 1 else 0)
            values[i] += stacks[i] / total * sum(payouts[2:])
    return values


def bubble_factor(stacks: Sequence[float], payouts: Sequence[float], hero: int, villain: int) -> float:
    """Raportul intre cat pierdem (in $ ICM) daca pierdem tot stack-ul vs villain si cat castigam daca il luam pe al lui.
    > 1 inseamna presiune ICM: trebuie echitate mai mare decat pot odds."""
    base = icm(stacks, payouts)
    eff = min(stacks[hero], stacks[villain])
    win = list(stacks)
    win[hero] += eff
    win[villain] -= eff
    lose = list(stacks)
    lose[hero] -= eff
    lose[villain] += eff
    gain = icm(win, payouts)[hero] - base[hero]
    loss = base[hero] - icm(lose, payouts)[hero]
    if gain <= 1e-12:
        return 10.0
    return max(1.0, loss / gain)


def icm_required_equity(chip_pot_odds: float, bf: float) -> float:
    """Echitatea necesara ajustata cu bubble factor: eq >= risk*bf / (risk*bf + reward)."""
    if chip_pot_odds >= 1:
        return 1.0
    risk = chip_pot_odds
    reward = 1 - chip_pot_odds
    return (risk * bf) / (risk * bf + reward)


def m_ratio(stack: float, sb: float, bb: float, ante: float, players: int) -> float:
    orbit_cost = sb + bb + ante * players
    return stack / orbit_cost if orbit_cost > 0 else float("inf")


def m_zone(m: float) -> str:
    if m >= 20:
        return "verde (joc complet)"
    if m >= 10:
        return "galben (fara call-uri speculative)"
    if m >= 6:
        return "portocaliu (push/fold agresiv, fara limp/call)"
    if m >= 1:
        return "rosu (push cu orice mana decenta)"
    return "mort (all-in cu orice)"


def stack_depth_label(bb: float) -> str:
    if bb >= 100:
        return "deep"
    if bb >= 40:
        return "standard"
    if bb >= 25:
        return "mediu"
    if bb >= 15:
        return "scurt"
    return "push/fold"


# ----------------------------------------------------------------------------
# Bankroll
# ----------------------------------------------------------------------------

@dataclass
class BankrollAdvice:
    buyins: float
    status: str
    recommended_max_stake: float
    risk_of_ruin: float
    notes: List[str]


def risk_of_ruin(bankroll: float, winrate_per_100: float, std_per_100: float) -> float:
    """Risk of ruin clasic: exp(-2*mu*B/sigma^2), unitati consistente (bb)."""
    if winrate_per_100 <= 0:
        return 1.0
    if std_per_100 <= 0:
        return 0.0
    return math.exp(-2 * winrate_per_100 * bankroll / (std_per_100 ** 2))


def bankroll_for_ror(target_ror: float, winrate_per_100: float, std_per_100: float) -> float:
    if winrate_per_100 <= 0 or target_ror <= 0 or target_ror >= 1:
        return float("inf")
    return -math.log(target_ror) * std_per_100 ** 2 / (2 * winrate_per_100)


def kelly_fraction(p_win: float, odds: float) -> float:
    """Fractia Kelly pentru un pariu cu probabilitate p si odds b:1."""
    if odds <= 0:
        return 0.0
    return max(0.0, (p_win * (odds + 1) - 1) / odds)


def bankroll_advice(bankroll: float, buyin: float, game: str = "cash",
                    winrate_bb100: float = 3.0, std_bb100: float = 90.0) -> BankrollAdvice:
    """Reguli de bankroll: cash 30-50 BI (100bb), MTT 100-200 BI, SNG 50-100 BI."""
    if buyin <= 0:
        return BankrollAdvice(float("inf"), "n/a", 0, 0, ["buy-in invalid"])
    bi = bankroll / buyin
    notes: List[str] = []
    if game == "cash":
        min_bi, good_bi = 30, 50
        ror = risk_of_ruin(bankroll / (buyin / 100.0), winrate_bb100, std_bb100)
        notes.append(f"RoR estimat la {winrate_bb100:.0f}bb/100, sd {std_bb100:.0f}: {100*ror:.1f}%")
    elif game == "mtt":
        min_bi, good_bi = 100, 200
        ror = max(0.0, min(1.0, math.exp(-bi / 60.0)))
        notes.append("MTT: varianta foarte mare, ROI tipic 10-30%, pastreaza 100-200 buy-in-uri")
    else:  # sng / spin
        min_bi, good_bi = 50, 100
        ror = max(0.0, min(1.0, math.exp(-bi / 35.0)))
    if bi < min_bi * 0.6:
        status = "SUB-BANKROLLED: coboara miza"
    elif bi < min_bi:
        status = "la limita: joaca prudent sau coboara"
    elif bi < good_bi:
        status = "ok"
    else:
        status = "confortabil: poti incerca miza urmatoare (shot)"
    rec_stake = bankroll / good_bi
    notes.append(f"{bi:.0f} buy-in-uri; miza maxima recomandata: buy-in {rec_stake:.2f}")
    return BankrollAdvice(bi, status, rec_stake, ror, notes)


def decision_cost(amount_bb: float, bb_value: float, stack_bb: float, bankroll: float) -> Dict[str, float]:
    """Ce inseamna o decizie in bani si in procente din stack si din bankroll."""
    money = amount_bb * bb_value
    return {
        "bb": amount_bb,
        "money": money,
        "pct_stack": 100.0 * amount_bb / stack_bb if stack_bb > 0 else 0.0,
        "pct_bankroll": 100.0 * money / bankroll if bankroll > 0 else 0.0,
    }
