import time
import unittest

from pokerbrain.cards import cards
from pokerbrain.advisor import Advisor, Situation, Opponent
from pokerbrain.players import PlayerStats, PlayerDB
from pokerbrain import charts


def hero(s):
    c = cards(s)
    return (c[0], c[1])


class TestCharts(unittest.TestCase):
    def test_open_ranges_monotone(self):
        pcts = [charts.open_range(p, 6).percent() for p in ["UTG", "HJ", "CO", "BTN"]]
        self.assertEqual(pcts, sorted(pcts))
        self.assertGreater(charts.open_range("BTN", 6).percent(), 35)
        self.assertLess(charts.open_range("UTG", 9).percent(), 14)

    def test_push_ranges(self):
        self.assertGreater(charts.push_range("SB", 6).percent(), charts.push_range("UTG", 6).percent())
        self.assertGreater(charts.push_range("BTN", 5).percent(), charts.push_range("BTN", 12).percent())
        self.assertTrue(charts.push_range("UTG", 10).contains("AA"))
        self.assertFalse(charts.push_range("UTG", 15).contains("72o"))


class TestAdvisorPreflop(unittest.TestCase):
    def setUp(self):
        self.adv = Advisor(iterations=600)

    def test_open_aa_utg(self):
        sit = Situation(hero("As Ad"), hero_position="UTG", opponents=[Opponent("v", "BB")], seed=1)
        rec = self.adv.recommend(sit)
        self.assertEqual(rec.action, "raise")
        self.assertAlmostEqual(rec.size_bb, 2.5)

    def test_fold_trash_utg(self):
        sit = Situation(hero("7c 2d"), hero_position="UTG", opponents=[Opponent("v", "BB")], seed=1)
        self.assertEqual(self.adv.recommend(sit).action, "fold")

    def test_btn_opens_wider(self):
        sit = Situation(hero("Jh 8h"), hero_position="BTN", opponents=[Opponent("v", "BB")], seed=1)
        self.assertEqual(self.adv.recommend(sit).action, "raise")
        sit.hero_position = "UTG"
        self.assertEqual(self.adv.recommend(sit).action, "fold")

    def test_bb_checks_unopened(self):
        sit = Situation(hero("7c 2d"), hero_position="BB", opponents=[Opponent("v", "SB")], seed=1)
        self.assertEqual(self.adv.recommend(sit).action, "check")

    def test_3bet_vs_open(self):
        v = Opponent("v", "CO", preflop_action="open", last_action="raise", bet_bb=2.5)
        sit = Situation(hero("Kh Kd"), hero_position="BTN", opponents=[v], pot_bb=4.0, to_call_bb=2.5,
                        preflop_state="facing_open", seed=1)
        rec = self.adv.recommend(sit)
        self.assertEqual(rec.action, "raise")
        self.assertGreater(rec.size_bb, 6.0)
        self.assertGreater(rec.equity, 0.7)

    def test_call_vs_open_with_suited_connector(self):
        v = Opponent("v", "CO", preflop_action="open", last_action="raise", bet_bb=2.5)
        sit = Situation(hero("8h 7h"), hero_position="BTN", opponents=[v], pot_bb=4.0, to_call_bb=2.5,
                        preflop_state="facing_open", seed=1)
        rec = self.adv.recommend(sit)
        self.assertIn(rec.action, ("call", "raise"))

    def test_fold_junk_vs_open(self):
        v = Opponent("v", "UTG", preflop_action="open", last_action="raise", bet_bb=2.5)
        sit = Situation(hero("9c 4d"), hero_position="BTN", opponents=[v], pot_bb=4.0, to_call_bb=2.5,
                        preflop_state="facing_open", seed=1)
        self.assertEqual(self.adv.recommend(sit).action, "fold")

    def test_exploit_frequent_raiser(self):
        """Adversar care deschide foarte des si da fold la 3-bet: 3-bet mai larg."""
        st = PlayerStats("agro", hands=200, vpip_opp=200, vpip_n=90, pfr_opp=200, pfr_n=75,
                         fold_to_3bet_opp=30, fold_to_3bet_n=24)
        v = Opponent("agro", "CO", stats=st, preflop_action="open", last_action="raise", bet_bb=2.5)
        sit = Situation(hero("Ah Td"), hero_position="BTN", opponents=[v], pot_bb=4.0, to_call_bb=2.5,
                        preflop_state="facing_open", seed=1)
        rec = self.adv.recommend(sit)
        self.assertEqual(rec.action, "raise", rec.summary())
        # vs un nit care deschide rar, ATo din BTN e cel mult call/fold
        nit = PlayerStats("nit", hands=200, vpip_opp=200, vpip_n=24, pfr_opp=200, pfr_n=20,
                          fold_to_3bet_opp=30, fold_to_3bet_n=8)
        v2 = Opponent("nit", "CO", stats=nit, preflop_action="open", last_action="raise", bet_bb=2.5)
        sit2 = Situation(hero("Ah Td"), hero_position="BTN", opponents=[v2], pot_bb=4.0, to_call_bb=2.5,
                         preflop_state="facing_open", seed=1)
        rec2 = self.adv.recommend(sit2)
        self.assertNotEqual(rec2.action, "raise", rec2.summary())

    def test_push_fold_short(self):
        sit = Situation(hero("Ac 5d"), hero_position="CO", hero_stack_bb=9, opponents=[Opponent("v", "BB", stack_bb=30)],
                        mode="mtt", seed=1)
        rec = self.adv.recommend(sit)
        self.assertEqual(rec.action, "allin", rec.summary())
        sit.hero_cards = hero("8c 3d")
        self.assertEqual(self.adv.recommend(sit).action, "fold")

    def test_call_shove(self):
        v = Opponent("v", "SB", stack_bb=10, preflop_action="allin", last_action="allin", bet_bb=10)
        sit = Situation(hero("Ad Qd"), hero_position="BB", hero_stack_bb=40, opponents=[v], pot_bb=11.0, to_call_bb=9.0,
                        preflop_state="facing_shove", mode="mtt", seed=1)
        rec = self.adv.recommend(sit)
        self.assertEqual(rec.action, "call", rec.summary())
        sit.hero_cards = hero("9c 3d")
        self.assertEqual(self.adv.recommend(sit).action, "fold")

    def test_icm_tightens(self):
        """Pe bubble, un call marginal devine fold."""
        v = Opponent("v", "SB", stack_bb=12, preflop_action="allin", last_action="allin", bet_bb=12)
        base = dict(hero_position="BB", hero_stack_bb=14, opponents=[v], pot_bb=13.0, to_call_bb=11.0,
                    preflop_state="facing_shove", seed=3)
        cash = Situation(hero("Kc Jd"), mode="cash", **base)
        mtt = Situation(hero("Kc Jd"), mode="mtt", payouts=[50, 30, 20], all_stacks_bb=[14, 12, 60, 40], **base)
        rc = self.adv.recommend(cash)
        rm = self.adv.recommend(mtt)
        self.assertGreater(rm.required_equity, rc.required_equity)


class TestAdvisorPostflop(unittest.TestCase):
    def setUp(self):
        self.adv = Advisor(iterations=600)

    def test_set_bets(self):
        v = Opponent("v", "BB", preflop_action="call", last_action="check")
        sit = Situation(hero("8d 8c"), board=cards("8s Kd 2c"), hero_position="BTN", opponents=[v], pot_bb=6.0,
                        hero_was_aggressor=True, seed=2)
        rec = self.adv.recommend(sit)
        self.assertEqual(rec.action, "bet", rec.summary())
        self.assertGreater(rec.equity, 0.85)

    def test_air_vs_calling_station_checks(self):
        st = PlayerStats("station", hands=150, fold_to_cbet_opp=40, fold_to_cbet_n=6, saw_flop=80, wtsd_n=40)
        v = Opponent("station", "BB", stats=st, preflop_action="call", last_action="check")
        sit = Situation(hero("7d 2c"), board=cards("Ks Qd 9c"), hero_position="BTN", opponents=[v], pot_bb=6.0,
                        hero_was_aggressor=True, seed=2)
        rec = self.adv.recommend(sit)
        self.assertEqual(rec.action, "check", rec.summary())

    def test_air_vs_folder_cbets(self):
        st = PlayerStats("folder", hands=150, fold_to_cbet_opp=40, fold_to_cbet_n=32)
        v = Opponent("folder", "BB", stats=st, preflop_action="call", last_action="check")
        sit = Situation(hero("7d 2c"), board=cards("Ks Qd 9c"), hero_position="BTN", opponents=[v], pot_bb=6.0,
                        hero_was_aggressor=True, seed=2)
        rec = self.adv.recommend(sit)
        self.assertEqual(rec.action, "bet", rec.summary())

    def test_fold_weak_vs_big_bet(self):
        v = Opponent("v", "BB", preflop_action="call", last_action="bet", bet_bb=12.0)
        sit = Situation(hero("7d 2c"), board=cards("Ks Qd 9c Jh 3s"), hero_position="BTN", opponents=[v],
                        pot_bb=18.0, to_call_bb=12.0, seed=2)
        self.assertEqual(self.adv.recommend(sit).action, "fold")

    def test_call_with_draw_good_odds(self):
        v = Opponent("v", "BB", preflop_action="call", last_action="bet", bet_bb=2.0)
        sit = Situation(hero("Ah Kh"), board=cards("Qh 7h 2c"), hero_position="BTN", opponents=[v],
                        pot_bb=8.0, to_call_bb=2.0, seed=2)
        rec = self.adv.recommend(sit)
        self.assertIn(rec.action, ("call", "raise"), rec.summary())

    def test_nuts_river_bets_or_raises(self):
        v = Opponent("v", "BB", preflop_action="call", last_action="bet", bet_bb=5.0)
        sit = Situation(hero("Ah Kh"), board=cards("Qh Jh Th 2c 2d"), hero_position="BTN", opponents=[v],
                        pot_bb=15.0, to_call_bb=5.0, seed=2)
        rec = self.adv.recommend(sit)
        self.assertIn(rec.action, ("raise", "allin"), rec.summary())

    def test_speed(self):
        v = Opponent("v", "BB", preflop_action="call", last_action="bet", bet_bb=4.0)
        sit = Situation(hero("Ah Kh"), board=cards("Qh 7h 2c"), hero_position="BTN", opponents=[v, Opponent("w", "SB", preflop_action="call", last_action="call", bet_bb=4.0)],
                        pot_bb=14.0, to_call_bb=4.0, seed=2)
        adv = Advisor(iterations=1500)
        t = time.perf_counter()
        adv.recommend(sit)
        dt = time.perf_counter() - t
        self.assertLess(dt, 1.5, f"advisor prea lent: {dt:.2f}s")


class TestPlayers(unittest.TestCase):
    def test_db_roundtrip(self):
        db = PlayerDB(":memory:")
        st = db.get("bob")
        st.new_hand()
        st.observe("vpip")
        st.observe("pfr")
        db.save()
        self.assertEqual(db.get("bob").vpip_n, 1)
        self.assertIn("bob", db.names())

    def test_archetypes(self):
        fish = PlayerStats("f", hands=100, vpip_opp=100, vpip_n=55, pfr_opp=100, pfr_n=8, aggr_actions=10, passive_actions=40)
        self.assertTrue(fish.archetype().startswith("fish"))
        nit = PlayerStats("n", hands=100, vpip_opp=100, vpip_n=12, pfr_opp=100, pfr_n=10)
        self.assertEqual(nit.archetype(), "nit")
        tag = PlayerStats("t", hands=100, vpip_opp=100, vpip_n=23, pfr_opp=100, pfr_n=19)
        self.assertEqual(tag.archetype(), "TAG")
        lag = PlayerStats("l", hands=100, vpip_opp=100, vpip_n=34, pfr_opp=100, pfr_n=28)
        self.assertEqual(lag.archetype(), "LAG")
        self.assertEqual(PlayerStats("u").archetype(), "necunoscut")

    def test_ranges_adapt(self):
        loose = PlayerStats("l", hands=100, vpip_opp=100, vpip_n=50, pfr_opp=100, pfr_n=40)
        tight = PlayerStats("t", hands=100, vpip_opp=100, vpip_n=12, pfr_opp=100, pfr_n=10)
        self.assertGreater(loose.open_range("CO", 6).percent(), tight.open_range("CO", 6).percent())
        self.assertTrue(any("3-bet" in e for e in loose.exploits()))


if __name__ == "__main__":
    unittest.main()
