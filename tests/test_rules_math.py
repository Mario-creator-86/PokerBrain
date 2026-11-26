import random
import unittest

from pokerbrain.rules import HandEngine, Seat, Action, ActionType, Street, position_name
from pokerbrain.math_tools import (pot_odds, mdf, alpha, icm, bubble_factor, icm_required_equity,
                                   bankroll_advice, risk_of_ruin, outs_to_equity, call_ev, bluff_ev)


def mk(n, stack=100.0):
    return [Seat(f"P{i}", stack) for i in range(n)]


class TestRules(unittest.TestCase):
    def test_positions(self):
        self.assertEqual(position_name(0, 6), "BTN")
        self.assertEqual(position_name(1, 6), "SB")
        self.assertEqual(position_name(2, 6), "BB")
        self.assertEqual(position_name(3, 6), "UTG")
        self.assertEqual(position_name(5, 6), "CO")
        self.assertEqual(position_name(3, 9), "UTG")
        self.assertEqual(position_name(8, 9), "CO")

    def test_blinds_and_order(self):
        seats = mk(3)
        e = HandEngine(seats, button=0, sb=0.5, bb=1.0, rng=random.Random(1))
        self.assertEqual(seats[1].stack, 99.5)
        self.assertEqual(seats[2].stack, 99.0)
        self.assertEqual(e.pot, 1.5)
        self.assertEqual(e.to_act, 0)  # butonul actioneaza primul la 3 jucatori
        legal = e.legal_actions()
        self.assertEqual(legal["call"], 1.0)
        self.assertEqual(legal["min_raise"], 2.0)
        self.assertEqual(legal["max_raise"], 100.0)

    def test_fold_to_bb(self):
        seats = mk(3)
        e = HandEngine(seats, button=0, sb=0.5, bb=1.0, rng=random.Random(1))
        e.act(Action(ActionType.FOLD))
        e.act(Action(ActionType.FOLD))
        self.assertTrue(e.finished)
        self.assertEqual(seats[2].stack, 100.5)
        self.assertEqual(e.results["P2"], 0.5)
        self.assertEqual(e.results["P1"], -0.5)

    def test_check_around_to_showdown(self):
        seats = mk(2)
        e = HandEngine(seats, button=0, sb=0.5, bb=1.0, rng=random.Random(2))
        # heads-up: butonul este SB si actioneaza primul preflop
        self.assertEqual(e.to_act, 0)
        e.act(Action(ActionType.CALL))
        self.assertEqual(e.street, Street.PREFLOP)
        self.assertEqual(e.to_act, 1)  # BB are optiunea
        e.act(Action(ActionType.CHECK))
        self.assertEqual(e.street, Street.FLOP)
        self.assertEqual(e.to_act, 1)  # postflop BB (non-buton) actioneaza primul
        for _ in range(3):
            e.act(Action(ActionType.CHECK))
            e.act(Action(ActionType.CHECK))
        self.assertTrue(e.finished)
        self.assertEqual(len(e.board), 5)
        self.assertAlmostEqual(sum(s.stack for s in seats), 200.0)

    def test_raise_reopens_action(self):
        seats = mk(3)
        e = HandEngine(seats, button=0, sb=0.5, bb=1.0, rng=random.Random(3))
        e.act(Action(ActionType.RAISE, 3.0))   # BTN raise to 3
        e.act(Action(ActionType.CALL))         # SB call
        e.act(Action(ActionType.RAISE, 10.0))  # BB 3-bet to 10
        self.assertEqual(e.to_act, 0)
        self.assertEqual(e.legal_actions()["call"], 7.0)
        self.assertEqual(e.legal_actions()["min_raise"], 17.0)
        e.act(Action(ActionType.CALL))
        e.act(Action(ActionType.FOLD))
        self.assertEqual(e.street, Street.FLOP)
        self.assertAlmostEqual(e.pot, 23.0)

    def test_all_in_side_pots(self):
        seats = [Seat("short", 10.0), Seat("mid", 50.0), Seat("big", 100.0)]
        e = HandEngine(seats, button=0, sb=0.5, bb=1.0, rng=random.Random(4))
        e.act(Action(ActionType.ALLIN))        # short all-in 10
        e.act(Action(ActionType.ALLIN))        # mid all-in 50
        e.act(Action(ActionType.CALL))         # big calls 50
        self.assertTrue(e.finished)
        total = sum(s.stack for s in seats)
        self.assertAlmostEqual(total, 160.0)
        # big nu poate pierde mai mult de 50
        self.assertGreaterEqual(seats[2].stack, 50.0)
        # short nu poate castiga mai mult de 30
        self.assertLessEqual(seats[0].stack, 30.0 + 1e-9)

    def test_many_random_hands_conserve_chips(self):
        rng = random.Random(9)
        for trial in range(60):
            n = rng.randint(2, 6)
            seats = [Seat(f"P{i}", rng.choice([5.0, 20.0, 100.0])) for i in range(n)]
            total = sum(s.stack for s in seats)
            e = HandEngine(seats, button=rng.randrange(n), sb=0.5, bb=1.0, ante=rng.choice([0, 0.1]),
                           rng=rng)
            steps = 0
            while not e.finished and steps < 200:
                legal = e.legal_actions()
                choice = rng.random()
                if "check" in legal and choice < 0.5:
                    e.act(Action(ActionType.CHECK))
                elif "call" in legal and choice < 0.6:
                    e.act(Action(ActionType.CALL))
                elif "min_raise" in legal and choice < 0.85:
                    amt = rng.uniform(legal["min_raise"], legal["max_raise"])
                    e.act(Action(ActionType.RAISE, amt))
                elif "fold" in legal:
                    e.act(Action(ActionType.FOLD))
                else:
                    e.act(Action(ActionType.CHECK))
                steps += 1
            self.assertTrue(e.finished, f"mana nu s-a terminat: {e.describe()}")
            self.assertAlmostEqual(sum(s.stack for s in seats), total, places=6)
            self.assertAlmostEqual(sum(e.results.values()), 0.0, places=6)


class TestMath(unittest.TestCase):
    def test_pot_odds(self):
        self.assertAlmostEqual(pot_odds(10, 20), 1 / 3)
        self.assertAlmostEqual(mdf(10, 10), 0.5)
        self.assertAlmostEqual(alpha(10, 10), 0.5)
        self.assertAlmostEqual(outs_to_equity(9, 2), 0.35, delta=0.01)
        self.assertAlmostEqual(outs_to_equity(9, 1), 9 / 46)
        self.assertAlmostEqual(call_ev(0.5, 10, 20), 5.0)
        self.assertAlmostEqual(bluff_ev(10, 10, 0.5), 0.0)

    def test_icm(self):
        v = icm([5000, 3000, 2000], [50, 30, 20])
        self.assertAlmostEqual(sum(v), 100.0, places=6)
        self.assertGreater(v[0], v[1])
        self.assertGreater(v[1], v[2])
        # stack dublu nu valoreaza dublu
        self.assertLess(v[0], 2 * v[2] * 1.0 + 1e-9 + 10)
        v2 = icm([1000, 1000, 1000, 1000], [50, 30, 20])
        for x in v2:
            self.assertAlmostEqual(x, 25.0, places=6)

    def test_bubble_factor(self):
        bf = bubble_factor([5000, 3000, 2000, 500], [50, 30, 20], hero=1, villain=0)
        self.assertGreater(bf, 1.0)
        req = icm_required_equity(0.4, bf)
        self.assertGreater(req, 0.4)
        self.assertAlmostEqual(icm_required_equity(0.4, 1.0), 0.4)

    def test_bankroll(self):
        a = bankroll_advice(1000, 100, "cash")
        self.assertIn("SUB", a.status)
        a = bankroll_advice(6000, 100, "cash")
        self.assertIn("confortabil", a.status)
        self.assertLess(risk_of_ruin(5000, 5, 90), risk_of_ruin(2000, 5, 90))


if __name__ == "__main__":
    unittest.main()
