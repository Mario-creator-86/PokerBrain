"""Punct de intrare: `python -m pokerbrain` porneste UI-ul; vezi `--help` pentru simulare si analiza din linia de comanda."""
from __future__ import annotations
import argparse
import sys


def main(argv=None) -> int:
    # inainte de orice fereastra: coordonatele ferestrelor si capturile in aceiasi pixeli fizici
    try:
        from .watcher.windows import set_dpi_awareness
        set_dpi_awareness()
    except Exception:
        pass
    p = argparse.ArgumentParser(prog="pokerbrain", description="PokerBrain - asistent NLHE")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("ui", help="porneste fereastra compacta (implicit)")
    s = sub.add_parser("sim", help="simulare cash sau turneu in consola")
    s.add_argument("--bots", default="nit,tag,lag,fish,maniac", help="lista de arhetipuri separate prin virgula")
    s.add_argument("--hands", type=int, default=500)
    s.add_argument("--mtt", action="store_true", help="turneu SNG in loc de cash (--hands = numar de turnee)")
    s.add_argument("--iters", type=int, default=300, help="iteratii Monte Carlo per decizie")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--verbose", action="store_true")
    a = sub.add_parser("advise", help="o recomandare rapida din linia de comanda")
    a.add_argument("hand", help="ex: AsKd")
    a.add_argument("--board", default="")
    a.add_argument("--pos", default="BTN")
    a.add_argument("--players", type=int, default=6)
    a.add_argument("--stack", type=float, default=100)
    a.add_argument("--pot", type=float, default=1.5)
    a.add_argument("--call", type=float, default=0.0)
    a.add_argument("--state", default="unopened", help="unopened|limped|facing_open|facing_3bet|facing_4bet|facing_shove")
    a.add_argument("--villain", default="villain:BB:100:none:none:0", help="nume:pozitie:stack:actiune_pre:ultima_actiune:pariu")
    a.add_argument("--mtt", action="store_true")
    a.add_argument("--aggressor", action="store_true", help="am fost agresor pe strada anterioara")
    sub.add_parser("calibrate", help="tool de calibrare pentru watcher")
    sub.add_parser("ranges", help="afiseaza charturile preflop")
    args = p.parse_args(argv)

    if args.cmd in (None, "ui"):
        from .ui.app import main as ui_main
        ui_main()
        return 0
    if args.cmd == "sim":
        from .simulator import Table, Tournament
        from .advisor import Advisor
        bots = [b.strip() for b in args.bots.split(",") if b.strip()]
        log = print if args.verbose else None
        adv = Advisor(iterations=args.iters)
        if args.mtt:
            rep = Tournament(bots, advisor=adv, seed=args.seed, log=log).run(args.hands, progress=lambda k, r: print(f"turneu {k}: loc {r.finishes[-1]}"))
        else:
            t = Table(bots, advisor=adv, seed=args.seed, log=log)
            rep = t.run(args.hands, progress=lambda k, r: print(f"{k} maini: hero {r.hero_net_bb:+.1f}bb"))
            print()
            for n in t.db.names():
                print(t.db.get(n).summary())
        print()
        print(rep.summary())
        return 0
    if args.cmd == "advise":
        from .cards import cards
        from .advisor import Advisor, Situation, Opponent
        from .players import PlayerDB
        h = cards(args.hand)
        parts = args.villain.split(":")
        while len(parts) < 6:
            parts.append("")
        db = PlayerDB()
        v = Opponent(name=parts[0] or "villain", position=parts[1] or "BB", stack_bb=float(parts[2] or 100),
                     stats=db.get(parts[0] or "villain"), preflop_action=parts[3] or "none",
                     last_action=parts[4] or "none", bet_bb=float(parts[5] or 0))
        sit = Situation((h[0], h[1]), board=cards(args.board), hero_position=args.pos, n_players=args.players,
                        hero_stack_bb=args.stack, pot_bb=args.pot, to_call_bb=args.call, opponents=[v],
                        mode="mtt" if args.mtt else "cash", preflop_state=args.state, hero_was_aggressor=args.aggressor)
        rec = Advisor().recommend(sit)
        print(rec.summary())
        if rec.villain_range is not None:
            print(f"range {rec.villain_range_pct:.0f}%: {rec.villain_range.to_string()[:300]}")
        return 0
    if args.cmd == "calibrate":
        from .watcher.calibrate import main as cal_main
        cal_main([])
        return 0
    if args.cmd == "ranges":
        from . import charts
        for pos in charts.POSITIONS_6[:-1]:
            print(f"6-max open {pos}: {charts.describe_chart(charts.open_range(pos, 6))}\n")
        for pos in charts.POSITIONS_9[:-1]:
            print(f"9-max open {pos}: {charts.open_range(pos, 9).percent():.1f}%")
        for k, v in charts.THREE_BET.items():
            print(f"3-bet {k}: {charts.describe_chart(charts.Range.parse(v))}\n")
        for bbs in (15, 12, 10, 8, 6, 4):
            print(f"push {bbs}bb: " + "  ".join(f"{g} {charts.push_range(g if g != 'EP' else 'UTG', bbs).percent():.0f}%"
                                               for g in ("UTG", "HJ", "CO", "BTN", "SB")))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
