import unittest

from pokerbrain.simulator import Table, Tournament, build_situation, HandContext, PROFILES
from pokerbrain.advisor import Advisor
from pokerbrain.players import PlayerDB
from pokerbrain.rules import HandEngine, Seat, Action, ActionType
import random


class TestSimulator(unittest.TestCase):
    def test_cash_table_runs_and_learns(self):
        t = Table(["fish", "maniac", "nit", "tag"], advisor=Advisor(iterations=120), seed=11)
        rep = t.run(60)
        self.assertEqual(rep.hands, 60)
        # conservarea chipurilor: suma rezultatelor e zero
        total = rep.hero_net_bb + sum(rep.bot_net_bb.values())
        self.assertAlmostEqual(total, 0.0, places=6)
        # profilurile s-au actualizat din observatie
        fish = t.db.get("fish1")
        nit = t.db.get("nit1")
        self.assertGreaterEqual(fish.hands, 60)
        self.assertGreater(fish.vpip, nit.vpip)

    def test_hero_beats_weak_table_over_time(self):
        t = Table(["fish", "fish", "maniac"], advisor=Advisor(iterations=120), seed=21)
        rep = t.run(250)
        self.assertGreater(rep.hero_net_bb, -150.0, rep.summary())  # nu pierde masiv vs jucatori slabi

    def test_tournament_finishes(self):
        tr = Tournament(["fish", "tag", "lag"], advisor=Advisor(iterations=100), seed=4)
        rep = tr.run(2)
        self.assertEqual(len(rep.finishes), 2)
        for f in rep.finishes:
            self.assertTrue(1 <= f <= 4)

    def test_build_situation_preflop(self):
        seats = [Seat("hero", 100), Seat("v1", 100), Seat("v2", 100)]
        eng = HandEngine(seats, button=1, sb=0.5, bb=1.0, rng=random.Random(2))
        ctx = HandContext(eng)
        # SB = seat 2, BB = seat 0 (hero), BTN = seat 1 actioneaza primul
        self.assertEqual(eng.to_act, 1)
        eng.act(Action(ActionType.RAISE, 2.5))
        eng.act(Action(ActionType.FOLD))
        self.assertEqual(eng.to_act, 0)
        sit = build_situation(eng, 0, ctx, PlayerDB(":memory:"))
        self.assertEqual(sit.preflop_state, "facing_open")
        self.assertEqual(sit.hero_position, "BB")
        self.assertEqual(len(sit.opponents), 1)
        self.assertEqual(sit.opponents[0].preflop_action, "open")
        self.assertAlmostEqual(sit.to_call_bb, 1.5)
        self.assertAlmostEqual(sit.pot_bb, 4.0)

    def test_profiles_exist(self):
        for k in ("nit", "tag", "lag", "fish", "maniac"):
            self.assertIn(k, PROFILES)


if __name__ == "__main__":
    unittest.main()
