import random
import unittest

from pokerbrain.cards import card, cards, cards_str, Deck
from pokerbrain.evaluator import (evaluate, category, HIGH_CARD, PAIR, TWO_PAIR, TRIPS, STRAIGHT,
                                  FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH)
from pokerbrain.ranges import Range, hand_class, HAND_CLASSES, TOTAL_COMBOS
from pokerbrain.equity import equity_vs_hands, equity_vs_ranges, analyze_hand, top_range


class TestCards(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(card("As"), 51)
        self.assertEqual(card("2c"), 0)
        self.assertEqual(cards("As Kd"), [51, 45])
        self.assertEqual(cards("AsKd"), [51, 45])
        self.assertEqual(cards_str(cards("Th 9h")), "Th 9h")
        with self.assertRaises(ValueError):
            cards("As As")

    def test_deck(self):
        d = Deck(random.Random(1), dead=[51])
        self.assertEqual(len(d), 51)
        drawn = d.draw(5)
        self.assertEqual(len(drawn), 5)
        self.assertNotIn(51, drawn)


class TestEvaluator(unittest.TestCase):
    def cat(self, s):
        return category(evaluate(cards(s)))

    def test_categories(self):
        self.assertEqual(self.cat("As Ks Qs Js Ts 2c 3d"), STRAIGHT_FLUSH)
        self.assertEqual(self.cat("As Ad Ah Ac Kd 2c 3d"), QUADS)
        self.assertEqual(self.cat("As Ad Ah Kc Kd 2c 3d"), FULL_HOUSE)
        self.assertEqual(self.cat("As 2s 9s Js Ts 2c 3d"), FLUSH)
        self.assertEqual(self.cat("As 2d 3h 4c 5d 9c Td"), STRAIGHT)
        self.assertEqual(self.cat("Ks Qd 3h 4c 5d 9c Td"), HIGH_CARD)
        self.assertEqual(self.cat("As Ad 3h 4c 5d 9c Td"), PAIR)
        self.assertEqual(self.cat("As Ad 3h 3c 5d 9c Td"), TWO_PAIR)
        self.assertEqual(self.cat("As Ad Ah 3c 5d 9c Td"), TRIPS)

    def test_ordering(self):
        self.assertGreater(evaluate(cards("As Ad Kh Kc 2d")), evaluate(cards("Ks Kd Qh Qc 2d")))
        self.assertGreater(evaluate(cards("As Kd 9h 7c 2d")), evaluate(cards("As Kd 9h 6c 2d")))
        self.assertGreater(evaluate(cards("6s 5d 4h 3c 2d")), evaluate(cards("As 2d 3h 4c 5d")))
        self.assertEqual(evaluate(cards("As Ad Kh Kc 2d 3c 4c")), evaluate(cards("Ah Ac Ks Kd 2c 3d 4d")))
        # full house: trips rank matters first
        self.assertGreater(evaluate(cards("3s 3d 3h Ac Ad")), evaluate(cards("2s 2d 2h Ac Ad")))
        # two pair with a third pair picks the best two
        s = evaluate(cards("As Ad Kh Kc 2d 2c 9d"))
        self.assertEqual(category(s), TWO_PAIR)
        self.assertGreater(s, evaluate(cards("As Ad Kh Kc 3d 3c 9d")) - 1)

    def test_speed(self):
        import time
        rng = random.Random(3)
        hands = [rng.sample(range(52), 7) for _ in range(20000)]
        t = time.perf_counter()
        for h in hands:
            evaluate(h)
        dt = time.perf_counter() - t
        self.assertLess(dt, 2.0, f"evaluator prea lent: {dt:.2f}s / 20k")


class TestRanges(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(len(HAND_CLASSES), 169)
        self.assertEqual(hand_class(card("As"), card("Ks")), "AKs")
        self.assertEqual(hand_class(card("Kd"), card("As")), "AKo")
        self.assertEqual(hand_class(card("7d"), card("7s")), "77")

    def test_parse(self):
        r = Range.parse("22+")
        self.assertEqual(len(r), 13)
        self.assertAlmostEqual(r.combos(), 78)
        r = Range.parse("A2s+")
        self.assertEqual(len(r), 12)
        r = Range.parse("KTo+")
        self.assertEqual(sorted(r.weights), ["KJo", "KQo", "KTo"])
        r = Range.parse("QQ-88")
        self.assertEqual(sorted(r.weights), ["88", "99", "JJ", "QQ", "TT"])
        r = Range.parse("A5s-A2s")
        self.assertEqual(len(r), 4)
        r = Range.parse("T9s-54s")
        self.assertEqual(sorted(r.weights), ["54s", "65s", "76s", "87s", "98s", "T9s"])
        r = Range.parse("AK")
        self.assertEqual(sorted(r.weights), ["AKo", "AKs"])
        r = Range.parse("A5s:0.5, KK")
        self.assertAlmostEqual(r.weight("A5s"), 0.5)
        self.assertAlmostEqual(Range.random_hand().combos(), TOTAL_COMBOS)

    def test_concrete(self):
        r = Range.parse("AA")
        self.assertEqual(len(r.concrete_combos()), 6)
        self.assertEqual(len(r.concrete_combos(dead=[card("As")])), 3)

    def test_top_range(self):
        r = top_range(10)
        self.assertTrue(r.contains("AA"))
        self.assertTrue(r.contains("AKs"))
        self.assertFalse(r.contains("72o"))
        self.assertAlmostEqual(r.percent(), 10, delta=0.5)


class TestEquity(unittest.TestCase):
    def test_aa_vs_kk(self):
        res = equity_vs_hands(tuple(cards("As Ad")), [tuple(cards("Ks Kd"))], iterations=4000,
                              rng=random.Random(1))
        self.assertAlmostEqual(res.equity, 0.82, delta=0.03)

    def test_exact_river(self):
        res = equity_vs_hands(tuple(cards("As Ad")), [tuple(cards("Ks Kd"))],
                              board=cards("2c 7d 9h Jc 3s"))
        self.assertTrue(res.exact)
        self.assertEqual(res.equity, 1.0)

    def test_turn_exact(self):
        # flush draw + 3 asi pe turn: 12 outs / 44 = 27.3%
        res = equity_vs_hands(tuple(cards("As 5s")), [tuple(cards("Kd Kc"))],
                              board=cards("2s 7s 9h Jc"))
        self.assertTrue(res.exact)
        self.assertAlmostEqual(res.equity, 12 / 44, delta=0.001)

    def test_vs_range(self):
        res = equity_vs_ranges(tuple(cards("As Ad")), [Range.parse("22+, A2s+, K9s+, ATo+")],
                               iterations=2000, rng=random.Random(2))
        self.assertGreater(res.equity, 0.78)
        res2 = equity_vs_ranges(tuple(cards("7c 2d")), [Range.random_hand()], iterations=2000,
                                rng=random.Random(2))
        self.assertLess(res2.equity, 0.40)

    def test_multiway(self):
        res = equity_vs_ranges(tuple(cards("As Ad")), [Range.random_hand(), Range.random_hand()],
                               iterations=2000, rng=random.Random(5))
        self.assertAlmostEqual(res.equity, 0.73, delta=0.05)

    def test_analysis(self):
        a = analyze_hand(cards("As Ks"), cards("Qs Js 2d"))
        self.assertTrue(a.flush_draw)
        self.assertTrue(a.nut_flush_draw)
        self.assertTrue(a.gutshot)
        self.assertGreaterEqual(a.outs, 12)
        a = analyze_hand(cards("Td 9d"), cards("8c 7h 2s"))
        self.assertTrue(a.oesd)
        a = analyze_hand(cards("Ad Ac"), cards("8c 7h 2s"))
        self.assertTrue(a.overpair)
        a = analyze_hand(cards("Ad 8d"), cards("8c 7h 2s"))
        self.assertTrue(a.top_pair)
        a = analyze_hand(cards("8d 8s"), cards("8c 7h 2s"))
        self.assertTrue(a.set_or_better)
        self.assertGreater(a.strength_rank, 0.95)


if __name__ == "__main__":
    unittest.main()
