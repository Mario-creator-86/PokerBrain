"""Regulile Texas Hold'em No-Limit: motor complet de mana (blinds, ante, ordine, min-raise,
all-in, side pots, showdown). Folosit de simulator si pentru validarea actiunilor."""
from __future__ import annotations
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from .cards import Deck, cards_str
from .evaluator import evaluate


class Street(Enum):
    PREFLOP = 0
    FLOP = 1
    TURN = 2
    RIVER = 3
    SHOWDOWN = 4


class ActionType(Enum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"
    ALLIN = "allin"


@dataclass
class Action:
    type: ActionType
    amount: float = 0.0  # pentru bet/raise: suma TOTALA pusa pe strada curenta de jucator (raise-to)

    def __repr__(self) -> str:
        return f"{self.type.value}{'' if self.amount == 0 else f' {self.amount:g}'}"


@dataclass
class Seat:
    name: str
    stack: float
    hole: List[int] = field(default_factory=list)
    in_hand: bool = True
    all_in: bool = False
    bet_this_street: float = 0.0
    total_invested: float = 0.0
    acted_this_street: bool = False
    sitting_out: bool = False

    @property
    def active(self) -> bool:
        return self.in_hand and not self.all_in and not self.sitting_out


POSITION_NAMES = {
    2: ["BTN/SB", "BB"],
    3: ["BTN", "SB", "BB"],
    4: ["CO", "BTN", "SB", "BB"],
    5: ["HJ", "CO", "BTN", "SB", "BB"],
    6: ["UTG", "HJ", "CO", "BTN", "SB", "BB"],
    7: ["UTG", "LJ", "HJ", "CO", "BTN", "SB", "BB"],
    8: ["UTG", "UTG1", "LJ", "HJ", "CO", "BTN", "SB", "BB"],
    9: ["UTG", "UTG1", "UTG2", "LJ", "HJ", "CO", "BTN", "SB", "BB"],
    10: ["UTG", "UTG1", "UTG2", "UTG3", "LJ", "HJ", "CO", "BTN", "SB", "BB"],
}


def position_name(seat_offset_from_button: int, n_players: int) -> str:
    """seat_offset: 0 = buton, 1 = SB, 2 = BB, 3 = primul care actioneaza preflop (UTG), ..."""
    names = POSITION_NAMES.get(n_players, POSITION_NAMES[9])
    if n_players == 2:
        return names[seat_offset_from_button % 2]
    # ordinea in lista: UTG ... CO, BTN, SB, BB; UTG este offset 3
    idx = (seat_offset_from_button - 3) % n_players
    return names[idx]


@dataclass
class HandRecord:
    """Istoricul actiunilor unei maini, pentru statistici."""
    actions: List[Tuple[Street, str, Action, float]] = field(default_factory=list)  # street, player, action, pot
    board: List[int] = field(default_factory=list)
    winners: Dict[str, float] = field(default_factory=dict)
    showdown_hands: Dict[str, List[int]] = field(default_factory=dict)
    went_to_showdown: List[str] = field(default_factory=list)


class HandEngine:
    """Ruleaza o singura mana. Jucatorii dau actiuni prin `act()`; motorul valideaza si avanseaza."""

    def __init__(self, seats: List[Seat], button: int, sb: float, bb: float, ante: float = 0.0,
                 rng: Optional[random.Random] = None, bb_ante: bool = False):
        self.seats = seats
        self.n = len(seats)
        self.button = button % self.n
        self.sb = sb
        self.bb = bb
        self.ante = ante
        self.bb_ante = bb_ante
        self.rng = rng or random.Random()
        self.deck = Deck(self.rng)
        self.board: List[int] = []
        self.pot = 0.0
        self.street = Street.PREFLOP
        self.current_bet = 0.0       # cel mai mare bet_this_street
        self.min_raise_increment = bb
        self.last_aggressor: Optional[int] = None
        self.to_act: Optional[int] = None
        self.record = HandRecord()
        self.finished = False
        self.results: Dict[str, float] = {}
        self._start()

    # ------------------------------------------------------------------ setup
    def _players_in(self) -> List[int]:
        return [i for i, s in enumerate(self.seats) if s.in_hand and not s.sitting_out]

    def _next_active(self, start: int) -> Optional[int]:
        for k in range(1, self.n + 1):
            i = (start + k) % self.n
            if self.seats[i].active:
                return i
        return None

    def _post(self, i: int, amount: float, blind: bool = False) -> float:
        s = self.seats[i]
        amt = min(amount, s.stack)
        s.stack -= amt
        s.bet_this_street += amt
        s.total_invested += amt
        self.pot += amt
        if s.stack <= 1e-9:
            s.all_in = True
        return amt

    def _start(self) -> None:
        for s in self.seats:
            s.hole = []
            s.in_hand = not s.sitting_out and s.stack > 0
            s.all_in = False
            s.bet_this_street = 0.0
            s.total_invested = 0.0
            s.acted_this_street = False
        players = self._players_in()
        if len(players) < 2:
            self.finished = True
            return
        # antes
        if self.ante > 0:
            if self.bb_ante:
                bb_seat = self._blind_seat(2)
                a = self._post(bb_seat, self.ante)
                self.seats[bb_seat].bet_this_street -= a  # ante nu conteaza ca bet
            else:
                for i in players:
                    a = self._post(i, self.ante)
                    self.seats[i].bet_this_street -= a
        # blinds
        sb_seat = self._blind_seat(1)
        bb_seat = self._blind_seat(2)
        self._post(sb_seat, self.sb)
        self._post(bb_seat, self.bb)
        self.current_bet = self.bb
        self.min_raise_increment = self.bb
        # deal
        for i in players:
            self.seats[i].hole = self.deck.draw(2)
        self.to_act = self._next_active(bb_seat)
        self.last_aggressor = bb_seat
        self._check_street_end_or_continue(initial=True)

    def _blind_seat(self, offset: int) -> int:
        players = self._players_in()
        if len(players) == 2:
            # heads-up: butonul este SB
            return self.button if offset == 1 else self._next_in(self.button)
        i = self.button
        for _ in range(offset):
            i = self._next_in(i)
        return i

    def _next_in(self, start: int) -> int:
        for k in range(1, self.n + 1):
            i = (start + k) % self.n
            if self.seats[i].in_hand and not self.seats[i].sitting_out:
                return i
        return start

    # ------------------------------------------------------------- game flow
    def legal_actions(self, i: Optional[int] = None) -> Dict[str, float]:
        """Actiuni legale pentru jucatorul la rand: {'fold':0, 'check':0, 'call':x, 'min_raise':y, 'max_raise':z}."""
        i = self.to_act if i is None else i
        if i is None or self.finished:
            return {}
        s = self.seats[i]
        out: Dict[str, float] = {}
        to_call = self.current_bet - s.bet_this_street
        if to_call > 0:
            out["fold"] = 0.0
            out["call"] = min(to_call, s.stack)
        else:
            out["check"] = 0.0
        if s.stack > to_call + 1e-9:
            min_total = self.current_bet + self.min_raise_increment if self.current_bet > 0 else self.bb
            max_total = s.bet_this_street + s.stack
            if max_total < min_total:
                min_total = max_total  # all-in sub min-raise
            out["min_raise"] = min_total
            out["max_raise"] = max_total
        return out

    def to_call(self, i: Optional[int] = None) -> float:
        i = self.to_act if i is None else i
        if i is None:
            return 0.0
        s = self.seats[i]
        return max(0.0, min(self.current_bet - s.bet_this_street, s.stack))

    def act(self, action: Action) -> None:
        if self.finished or self.to_act is None:
            raise RuntimeError("mana s-a terminat")
        i = self.to_act
        s = self.seats[i]
        legal = self.legal_actions(i)
        pot_before = self.pot
        t = action.type
        if t == ActionType.FOLD:
            if "fold" not in legal:
                t = ActionType.CHECK  # fold cand poti da check = check
            else:
                s.in_hand = False
        if t == ActionType.CHECK:
            if "check" not in legal:
                raise ValueError("nu poti da check cand ai de platit")
        elif t == ActionType.CALL:
            if "call" not in legal:
                raise ValueError("nu e nimic de platit")
            self._post(i, legal["call"])
        elif t in (ActionType.BET, ActionType.RAISE, ActionType.ALLIN):
            if "min_raise" not in legal:
                # nu poate ridica: tratam ca call/check
                if "call" in legal:
                    self._post(i, legal["call"])
                    t = ActionType.CALL
                else:
                    t = ActionType.CHECK
            else:
                total = legal["max_raise"] if t == ActionType.ALLIN else action.amount
                total = max(legal["min_raise"], min(legal["max_raise"], total))
                increment = total - self.current_bet
                full_raise = increment >= self.min_raise_increment - 1e-9
                self._post(i, total - s.bet_this_street)
                if full_raise:
                    self.min_raise_increment = increment
                if total > self.current_bet:
                    self.current_bet = total
                    self.last_aggressor = i
                    if full_raise:
                        for j, o in enumerate(self.seats):
                            if j != i:
                                o.acted_this_street = False
                action = Action(t, total)
        s.acted_this_street = True
        self.record.actions.append((self.street, s.name, Action(t, action.amount), pot_before))
        self._check_street_end_or_continue()

    def _check_street_end_or_continue(self, initial: bool = False) -> None:
        players = self._players_in()
        if len(players) == 1:
            self._award_uncontested(players[0])
            return
        active = [i for i in players if self.seats[i].active]
        # strada se termina cand toti activi au actionat si au egalat current_bet
        def street_done() -> bool:
            if len(active) == 0:
                return True
            if len(active) == 1:
                # un singur jucator activ: daca a egalat, gata
                a = self.seats[active[0]]
                return a.bet_this_street >= self.current_bet - 1e-9 and (a.acted_this_street or self.current_bet > 0 and all(
                    self.seats[j].all_in for j in players if j != active[0]))
            return all(self.seats[i].acted_this_street and self.seats[i].bet_this_street >= self.current_bet - 1e-9
                       for i in active)

        if initial:
            # preflop: BB are optiunea
            self.seats[self._blind_seat(2)].acted_this_street = False
            if self.to_act is None or self.seats[self.to_act].active is False:
                self.to_act = self._next_active(self.to_act if self.to_act is not None else self.button)
            return
        if street_done():
            self._advance_street()
            return
        nxt = self._next_active(self.to_act if self.to_act is not None else self.button)
        # sarim peste cei care au actionat deja si au egalat
        for _ in range(self.n):
            if nxt is None:
                break
            s = self.seats[nxt]
            if s.acted_this_street and s.bet_this_street >= self.current_bet - 1e-9:
                nxt = self._next_active(nxt)
            else:
                break
        if nxt is None:
            self._advance_street()
            return
        self.to_act = nxt

    def _advance_street(self) -> None:
        for s in self.seats:
            s.bet_this_street = 0.0
            s.acted_this_street = False
        self.current_bet = 0.0
        self.min_raise_increment = self.bb
        players = self._players_in()
        active = [i for i in players if self.seats[i].active]
        if self.street == Street.PREFLOP:
            self.board += self.deck.draw(3)
            self.street = Street.FLOP
        elif self.street == Street.FLOP:
            self.board += self.deck.draw(1)
            self.street = Street.TURN
        elif self.street == Street.TURN:
            self.board += self.deck.draw(1)
            self.street = Street.RIVER
        else:
            self._showdown()
            return
        self.record.board = list(self.board)
        if len(active) <= 1:
            # toti all-in (sau unul singur activ fara adversari activi): rulam pana la showdown
            self._advance_street()
            return
        self.to_act = self._next_active(self.button)
        self.last_aggressor = None

    def _award_uncontested(self, winner: int) -> None:
        s = self.seats[winner]
        s.stack += self.pot
        self.record.winners = {s.name: self.pot}
        self.pot = 0.0
        self._finish()

    def _showdown(self) -> None:
        self.street = Street.SHOWDOWN
        players = self._players_in()
        while len(self.board) < 5:
            self.board += self.deck.draw(1)
        self.record.board = list(self.board)
        scores = {i: evaluate(self.seats[i].hole + self.board) for i in players}
        for i in players:
            self.record.showdown_hands[self.seats[i].name] = list(self.seats[i].hole)
            self.record.went_to_showdown.append(self.seats[i].name)
        # side pots: dupa total_invested
        contributions = {i: s.total_invested for i, s in enumerate(self.seats) if s.total_invested > 0}
        winners: Dict[str, float] = {}
        remaining = dict(contributions)
        eligible = set(players)
        while remaining and any(v > 0 for v in remaining.values()):
            level = min(v for v in remaining.values() if v > 0)
            pot_level = 0.0
            for i in list(remaining):
                take = min(level, remaining[i])
                pot_level += take
                remaining[i] -= take
            contenders = [i for i in eligible if contributions[i] >= level - 1e-9]
            if not contenders:
                contenders = list(eligible)
            best = max(scores[i] for i in contenders)
            winners_here = [i for i in contenders if scores[i] == best]
            share = pot_level / len(winners_here)
            for i in winners_here:
                self.seats[i].stack += share
                winners[self.seats[i].name] = winners.get(self.seats[i].name, 0.0) + share
            # cei care au contribuit doar pana la level ies din eligibilitate
            eligible = {i for i in eligible if remaining.get(i, 0) > 0} or eligible
            remaining = {i: v for i, v in remaining.items() if v > 0}
        self.pot = 0.0
        self.record.winners = winners
        self._finish()

    def _finish(self) -> None:
        self.finished = True
        self.to_act = None
        for s in self.seats:
            self.results[s.name] = -s.total_invested + self.record.winners.get(s.name, 0.0)

    # ------------------------------------------------------------- utilitare
    def position_of(self, i: int) -> str:
        players = self._players_in_at_start()
        n = len(players)
        if i not in players:
            return "-"
        offset = (i - self.button) % self.n
        # convertim offset de scaune in offset de jucatori
        order = []
        j = self.button
        for _ in range(self.n):
            if j in players:
                order.append(j)
            j = (j + 1) % self.n
        return position_name(order.index(i), n)

    def _players_in_at_start(self) -> List[int]:
        return [i for i, s in enumerate(self.seats) if not s.sitting_out and (s.in_hand or s.total_invested > 0 or s.hole)]

    def describe(self) -> str:
        return (f"{self.street.name} pot={self.pot:g} board=[{cards_str(self.board)}] "
                f"to_act={self.seats[self.to_act].name if self.to_act is not None else '-'} "
                f"bet={self.current_bet:g}")
