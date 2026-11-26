"""Fereastra compacta PokerBrain: input rapid al situatiei, recomandare cu procente, adversari cu
statistici, bankroll, simulator si watcher de ecran. Always-on-top, ~360x640 px."""
from __future__ import annotations
import json
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, List, Optional

from ..cards import cards as parse_cards, cards_str
from ..advisor import Advisor, Situation, Opponent, Recommendation
from ..players import PlayerDB, PlayerStats, EVENTS
from ..math_tools import bankroll_advice
from ..rules import POSITION_NAMES
from .. import charts

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

BG = "#1e1f26"
BG2 = "#2a2c36"
FG = "#e6e6e6"
DIM = "#9aa0ad"
GREEN = "#4ad17a"
RED = "#ff5c5c"
BLUE = "#5aa9ff"
YELLOW = "#ffd166"

PREFLOP_STATES = [
    ("unopened", "nimeni n-a deschis"),
    ("limped", "limp-uri in fata"),
    ("facing_open", "open in fata"),
    ("facing_3bet", "am deschis, primesc 3-bet"),
    ("facing_4bet", "primesc 4-bet"),
    ("facing_shove", "all-in in fata"),
]
PRE_ACTIONS = ["none", "open", "call", "limp", "3bet", "4bet", "allin", "check"]
LAST_ACTIONS = ["none", "check", "call", "bet", "raise", "allin"]
OBS_EVENTS = [
    ("vpip", "a intrat voluntar (VPIP)"), ("vpip_opp", "a avut ocazia, fold pre"), ("pfr", "a ridicat preflop (PFR)"),
    ("limp", "a dat limp"), ("call_open", "a dat call la open"), ("3bet", "a dat 3-bet"), ("3bet_opp", "putea 3-bet, nu a facut"),
    ("fold_to_3bet", "fold la 3-bet"), ("fold_to_3bet_opp", "a continuat vs 3-bet"), ("steal", "a furat din CO/BTN/SB"),
    ("fold_to_steal", "fold la steal"), ("fold_to_steal_opp", "a aparat vs steal"),
    ("cbet", "a dat c-bet"), ("cbet_opp", "putea c-bet, a dat check"), ("fold_to_cbet", "fold la c-bet"),
    ("fold_to_cbet_opp", "a continuat vs c-bet"), ("fold_to_bet_post", "fold la pariu postflop"),
    ("fold_to_bet_post_opp", "call la pariu postflop"), ("fold_to_raise_post", "fold la raise postflop"),
    ("fold_to_raise_post_opp", "a continuat vs raise"), ("bet_or_raise", "bet/raise postflop (AF)"), ("call_post", "call postflop (AF)"),
    ("check_raise", "check-raise"), ("wtsd", "a mers la showdown"), ("wsd", "a castigat la showdown"),
]


def load_settings() -> dict:
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(d: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)


def _f(var: tk.StringVar, default: float = 0.0) -> float:
    try:
        return float(str(var.get()).replace(",", ".").strip() or default)
    except ValueError:
        return default


class OpponentRow:
    def __init__(self, parent: tk.Widget, row: int, app: "App"):
        self.app = app
        self.active = tk.BooleanVar(value=row == 0)
        self.name = tk.StringVar(value=f"villain{row + 1}")
        self.pos = tk.StringVar(value="BB")
        self.stack = tk.StringVar(value="100")
        self.pre = tk.StringVar(value="none")
        self.last = tk.StringVar(value="none")
        self.bet = tk.StringVar(value="0")
        ttk.Checkbutton(parent, variable=self.active, width=1).grid(row=row, column=0, padx=(0, 2))
        self.name_cb = ttk.Combobox(parent, textvariable=self.name, width=9, values=app.db.names())
        self.name_cb.grid(row=row, column=1, padx=1)
        ttk.Combobox(parent, textvariable=self.pos, width=5, values=POSITION_NAMES[9], state="readonly").grid(row=row, column=2, padx=1)
        ttk.Entry(parent, textvariable=self.stack, width=5).grid(row=row, column=3, padx=1)
        ttk.Combobox(parent, textvariable=self.pre, width=5, values=PRE_ACTIONS, state="readonly").grid(row=row, column=4, padx=1)
        ttk.Combobox(parent, textvariable=self.last, width=5, values=LAST_ACTIONS, state="readonly").grid(row=row, column=5, padx=1)
        ttk.Entry(parent, textvariable=self.bet, width=5).grid(row=row, column=6, padx=1)

    def to_opponent(self) -> Optional[Opponent]:
        if not self.active.get():
            return None
        name = self.name.get().strip() or "villain"
        st = self.app.db.get(name)
        return Opponent(name=name, position=self.pos.get(), stack_bb=_f(self.stack, 100), stats=st,
                        last_action=self.last.get(), bet_bb=_f(self.bet, 0), preflop_action=self.pre.get())


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PokerBrain")
        self.configure(bg=BG)
        self.attributes("-topmost", True)
        self.settings = load_settings()
        try:
            self.attributes("-alpha", float(self.settings.get("alpha", 0.95)))
        except tk.TclError:
            pass
        self.resizable(False, False)
        self.db = PlayerDB()
        self.advisor = Advisor(iterations=int(self.settings.get("iterations", 1500)))
        self.watcher = None
        self._busy = False
        self._style()
        self._build()
        self._load_settings_into_ui()
        self.bind("<Return>", lambda e: self.analyze())
        self.bind("<Control-n>", lambda e: self.new_hand())
        self.bind("<Escape>", lambda e: self.board.set(""))
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        geo = self.settings.get("geometry")
        if geo:
            try:
                self.geometry(geo)
            except tk.TclError:
                pass

    # ------------------------------------------------------------ stil
    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure(".", background=BG, foreground=FG, fieldbackground=BG2, font=("Segoe UI", 9))
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Dim.TLabel", foreground=DIM, font=("Segoe UI", 8))
        s.configure("TFrame", background=BG)
        s.configure("TLabelframe", background=BG, foreground=DIM)
        s.configure("TLabelframe.Label", background=BG, foreground=DIM, font=("Segoe UI", 8))
        s.configure("TButton", background=BG2, foreground=FG, padding=2)
        s.map("TButton", background=[("active", "#3a3d4a")])
        s.configure("TCheckbutton", background=BG, foreground=FG)
        s.configure("TRadiobutton", background=BG, foreground=FG)
        s.configure("TEntry", foreground=FG, insertcolor=FG)
        s.configure("TCombobox", foreground=FG, arrowcolor=FG)
        s.map("TCombobox", fieldbackground=[("readonly", BG2)], foreground=[("readonly", FG)])
        s.configure("TSpinbox", foreground=FG, arrowcolor=FG)
        self.option_add("*TCombobox*Listbox.background", BG2)
        self.option_add("*TCombobox*Listbox.foreground", FG)

    # ------------------------------------------------------------ constructie
    def _build(self):
        pad = {"padx": 2, "pady": 1}
        top = ttk.Frame(self)
        top.pack(fill="x", padx=4, pady=(4, 0))
        self.mode = tk.StringVar(value="cash")
        ttk.Radiobutton(top, text="Cash", variable=self.mode, value="cash", command=self._mode_changed).pack(side="left")
        ttk.Radiobutton(top, text="Turneu", variable=self.mode, value="mtt", command=self._mode_changed).pack(side="left", padx=(0, 6))
        ttk.Label(top, text="Locuri").pack(side="left")
        self.n_players = tk.StringVar(value="6")
        ttk.Spinbox(top, from_=2, to=10, textvariable=self.n_players, width=3).pack(side="left", padx=(0, 6))
        ttk.Label(top, text="Pozitie").pack(side="left")
        self.position = tk.StringVar(value="BTN")
        ttk.Combobox(top, textvariable=self.position, width=5, values=POSITION_NAMES[9], state="readonly").pack(side="left")

        row2 = ttk.Frame(self)
        row2.pack(fill="x", padx=4)
        self.row2 = row2
        ttk.Label(row2, text="BB =").pack(side="left")
        self.bb_money = tk.StringVar(value="1")
        ttk.Entry(row2, textvariable=self.bb_money, width=6).pack(side="left", padx=(0, 6))
        ttk.Label(row2, text="Bankroll").pack(side="left")
        self.bankroll = tk.StringVar(value="0")
        ttk.Entry(row2, textvariable=self.bankroll, width=8).pack(side="left", padx=(0, 6))
        self.br_label = ttk.Label(row2, text="", style="Dim.TLabel")
        self.br_label.pack(side="left")

        # turneu
        self.mtt_frame = ttk.Frame(self)
        ttk.Label(self.mtt_frame, text="Ramasi").pack(side="left")
        self.players_left = tk.StringVar(value="0")
        ttk.Entry(self.mtt_frame, textvariable=self.players_left, width=5).pack(side="left", padx=(0, 4))
        ttk.Label(self.mtt_frame, text="In bani").pack(side="left")
        self.itm = tk.StringVar(value="0")
        ttk.Entry(self.mtt_frame, textvariable=self.itm, width=4).pack(side="left", padx=(0, 4))
        ttk.Label(self.mtt_frame, text="Ante(bb)").pack(side="left")
        self.ante = tk.StringVar(value="0")
        ttk.Entry(self.mtt_frame, textvariable=self.ante, width=4).pack(side="left", padx=(0, 4))
        ttk.Label(self.mtt_frame, text="Plati %").pack(side="left")
        self.payouts = tk.StringVar(value="50,30,20")
        ttk.Entry(self.mtt_frame, textvariable=self.payouts, width=10).pack(side="left")

        hand = ttk.LabelFrame(self, text="Mana (Enter = analizeaza, Ctrl+N = mana noua, Esc = sterge board)")
        hand.pack(fill="x", padx=4, pady=2)
        ttk.Label(hand, text="Carti").grid(row=0, column=0, sticky="e", **pad)
        self.hero = tk.StringVar()
        e = ttk.Entry(hand, textvariable=self.hero, width=8, font=("Consolas", 11))
        e.grid(row=0, column=1, **pad)
        self.hero_entry = e
        ttk.Label(hand, text="Board").grid(row=0, column=2, sticky="e", **pad)
        self.board = tk.StringVar()
        ttk.Entry(hand, textvariable=self.board, width=16, font=("Consolas", 11)).grid(row=0, column=3, columnspan=3, sticky="w", **pad)
        ttk.Label(hand, text="Pot").grid(row=1, column=0, sticky="e", **pad)
        self.pot = tk.StringVar(value="1.5")
        ttk.Entry(hand, textvariable=self.pot, width=8).grid(row=1, column=1, **pad)
        ttk.Label(hand, text="De platit").grid(row=1, column=2, sticky="e", **pad)
        self.to_call = tk.StringVar(value="0")
        ttk.Entry(hand, textvariable=self.to_call, width=6).grid(row=1, column=3, **pad)
        ttk.Label(hand, text="Stack").grid(row=1, column=4, sticky="e", **pad)
        self.stack = tk.StringVar(value="100")
        ttk.Entry(hand, textvariable=self.stack, width=6).grid(row=1, column=5, **pad)
        ttk.Label(hand, text="Preflop").grid(row=2, column=0, sticky="e", **pad)
        self.pre_state = tk.StringVar(value=PREFLOP_STATES[0][1])
        ttk.Combobox(hand, textvariable=self.pre_state, width=22, values=[t for _, t in PREFLOP_STATES],
                     state="readonly").grid(row=2, column=1, columnspan=3, sticky="w", **pad)
        ttk.Label(hand, text="Pus deja").grid(row=2, column=4, sticky="e", **pad)
        self.hero_bet = tk.StringVar(value="0")
        ttk.Entry(hand, textvariable=self.hero_bet, width=6).grid(row=2, column=5, **pad)
        ttk.Label(hand, text="Limperi/Calleri").grid(row=3, column=0, columnspan=2, sticky="e", **pad)
        self.n_limpers = tk.StringVar(value="0")
        ttk.Spinbox(hand, from_=0, to=8, textvariable=self.n_limpers, width=3).grid(row=3, column=2, sticky="w", **pad)
        self.n_callers = tk.StringVar(value="0")
        ttk.Spinbox(hand, from_=0, to=8, textvariable=self.n_callers, width=3).grid(row=3, column=3, sticky="w", **pad)
        self.was_aggr = tk.BooleanVar(value=False)
        ttk.Checkbutton(hand, text="am fost agresor", variable=self.was_aggr).grid(row=3, column=4, columnspan=2, sticky="w", **pad)
        ttk.Label(hand, text="Toate sumele in bb. Carti: As Kd / AsKd / 10h", style="Dim.TLabel").grid(row=4, column=0, columnspan=6, sticky="w")

        opp = ttk.LabelFrame(self, text="Adversari (in mana, nume, pozitie, stack, preflop, ultima actiune, pariu)")
        opp.pack(fill="x", padx=4, pady=2)
        self.opp_rows: List[OpponentRow] = [OpponentRow(opp, i, self) for i in range(3)]
        obs = ttk.Frame(opp)
        obs.grid(row=3, column=0, columnspan=7, sticky="w", pady=(2, 0))
        ttk.Label(obs, text="Observ").pack(side="left")
        self.obs_target = tk.StringVar(value="1")
        ttk.Combobox(obs, textvariable=self.obs_target, width=2, values=["1", "2", "3"], state="readonly").pack(side="left", padx=2)
        self.obs_event = tk.StringVar(value=OBS_EVENTS[0][1])
        ttk.Combobox(obs, textvariable=self.obs_event, width=24, values=[t for _, t in OBS_EVENTS], state="readonly").pack(side="left", padx=2)
        ttk.Button(obs, text="+", width=2, command=self.add_observation).pack(side="left")
        ttk.Button(obs, text="+mana", width=6, command=self.add_hand_all).pack(side="left", padx=2)

        rec = ttk.LabelFrame(self, text="Recomandare")
        rec.pack(fill="both", expand=True, padx=4, pady=2)
        self.rec_label = tk.Label(rec, text="—", font=("Segoe UI", 20, "bold"), bg=BG, fg=FG, anchor="w")
        self.rec_label.pack(fill="x", padx=4)
        self.stats_label = tk.Label(rec, text="", font=("Consolas", 10), bg=BG, fg=YELLOW, anchor="w", justify="left")
        self.stats_label.pack(fill="x", padx=4)
        self.reasons = tk.Text(rec, height=9, width=48, bg=BG2, fg=FG, font=("Segoe UI", 8), wrap="word",
                               relief="flat", padx=4, pady=2)
        self.reasons.pack(fill="both", expand=True, padx=4, pady=2)
        self.reasons.configure(state="disabled")

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=4, pady=(0, 2))
        ttk.Button(btns, text="Analizeaza", command=self.analyze).pack(side="left")
        ttk.Button(btns, text="Mana noua", command=self.new_hand).pack(side="left", padx=2)
        ttk.Button(btns, text="Jucatori", command=self.open_players).pack(side="left", padx=2)
        ttk.Button(btns, text="Simulare", command=self.open_sim).pack(side="left", padx=2)
        self.watch_btn = ttk.Button(btns, text="Watcher", command=self.toggle_watcher)
        self.watch_btn.pack(side="left", padx=2)
        ttk.Button(btns, text="Calibrare", command=self.open_calibrate).pack(side="left", padx=2)
        self.status = ttk.Label(self, text="gata", style="Dim.TLabel", anchor="w")
        self.status.pack(fill="x", padx=6, pady=(0, 3))
        self._mode_changed()

    def _mode_changed(self):
        if self.mode.get() == "mtt":
            self.mtt_frame.pack(fill="x", padx=4, after=self.row2)
        else:
            self.mtt_frame.pack_forget()
        self._update_bankroll_label()

    def _load_settings_into_ui(self):
        s = self.settings
        self.bb_money.set(str(s.get("bb_money", "1")))
        self.bankroll.set(str(s.get("bankroll", "0")))
        self.n_players.set(str(s.get("n_players", "6")))
        self.mode.set(s.get("mode", "cash"))
        self._mode_changed()

    def _collect_settings(self) -> dict:
        s = dict(self.settings)
        s.update({"bb_money": self.bb_money.get(), "bankroll": self.bankroll.get(), "n_players": self.n_players.get(),
                  "mode": self.mode.get(), "geometry": self.geometry()})
        return s

    def on_close(self):
        try:
            if self.watcher:
                self.watcher.stop()
            save_settings(self._collect_settings())
            self.db.close()
        finally:
            self.destroy()

    def set_status(self, text: str):
        self.status.config(text=text)

    # ------------------------------------------------------------ actiuni
    def _update_bankroll_label(self):
        br = _f(self.bankroll)
        bbm = _f(self.bb_money, 1.0)
        if br <= 0 or bbm <= 0:
            self.br_label.config(text="")
            return
        game = "cash" if self.mode.get() == "cash" else "mtt"
        buyin = 100 * bbm if game == "cash" else _f(self.stack, 100) * bbm
        adv = bankroll_advice(br, buyin, game)
        self.br_label.config(text=f"{adv.buyins:.0f} BI: {adv.status}")

    def build_situation(self) -> Situation:
        hero = parse_cards(self.hero.get())
        if len(hero) != 2:
            raise ValueError("introdu exact 2 carti pentru hero (ex: As Kd)")
        board = parse_cards(self.board.get())
        if len(board) not in (0, 3, 4, 5):
            raise ValueError("board-ul trebuie sa aiba 0, 3, 4 sau 5 carti")
        if set(board) & set(hero):
            raise ValueError("carti duplicate intre mana si board")
        opps = [r.to_opponent() for r in self.opp_rows]
        opps = [o for o in opps if o is not None]
        state_key = next((k for k, t in PREFLOP_STATES if t == self.pre_state.get()), "unopened")
        if not board and state_key in ("facing_open", "facing_3bet", "facing_4bet", "facing_shove") and opps:
            # ne asiguram ca villain-ul principal are actiunea preflop potrivita
            main = max(opps, key=lambda o: o.bet_bb)
            if main.preflop_action == "none":
                main.preflop_action = {"facing_open": "open", "facing_3bet": "3bet", "facing_4bet": "4bet",
                                       "facing_shove": "allin"}[state_key]
                main.last_action = {"open": "raise", "3bet": "3bet", "4bet": "4bet", "allin": "allin"}[main.preflop_action]
            if main.bet_bb <= 0:
                main.bet_bb = _f(self.to_call) + _f(self.hero_bet)
        payouts = []
        if self.mode.get() == "mtt":
            try:
                payouts = [float(x) for x in self.payouts.get().replace(";", ",").split(",") if x.strip()]
            except ValueError:
                payouts = []
        sit = Situation(
            hero_cards=(hero[0], hero[1]), board=board, hero_position=self.position.get(),
            n_players=int(_f(self.n_players, 6)), hero_stack_bb=_f(self.stack, 100), pot_bb=_f(self.pot, 1.5),
            to_call_bb=_f(self.to_call), hero_bet_bb=_f(self.hero_bet), opponents=opps, mode=self.mode.get(),
            bb_money=_f(self.bb_money, 1.0), bankroll=_f(self.bankroll), ante_bb=_f(self.ante) if self.mode.get() == "mtt" else 0.0,
            hero_was_aggressor=self.was_aggr.get(), preflop_state=state_key, n_limpers=int(_f(self.n_limpers)),
            n_callers=int(_f(self.n_callers)), payouts=payouts, players_left=int(_f(self.players_left)),
            itm_places=int(_f(self.itm)), iterations=self.advisor.iterations,
        )
        if sit.mode == "mtt" and opps:
            sit.all_stacks_bb = [sit.hero_stack_bb] + [o.stack_bb for o in opps]
        return sit

    def analyze(self):
        if self._busy:
            return
        try:
            sit = self.build_situation()
        except ValueError as e:
            self.set_status(str(e))
            return
        self._busy = True
        self.set_status("calculez...")
        self._update_bankroll_label()

        def work():
            try:
                rec = self.advisor.recommend(sit)
                self.after(0, lambda: self.show_recommendation(rec, sit))
            except Exception as e:  # pragma: no cover
                self.after(0, lambda: self.set_status(f"eroare: {e}"))
            finally:
                self._busy = False
        threading.Thread(target=work, daemon=True).start()

    def show_recommendation(self, rec: Recommendation, sit: Situation):
        color = {"fold": RED, "check": BLUE, "call": BLUE, "bet": GREEN, "raise": GREEN, "allin": YELLOW}.get(rec.action, FG)
        self.rec_label.config(text=rec.headline(), fg=color)
        ev_txt = "  ".join(f"{k} {v:+.1f}" for k, v in sorted(rec.ev_bb.items(), key=lambda kv: -kv[1])[:4])
        self.stats_label.config(text=f"echitate {100*rec.equity:4.1f}%   necesar {100*rec.required_equity:4.1f}%   "
                                     f"incredere {100*rec.confidence:.0f}%\nEV(bb): {ev_txt}")
        self.reasons.configure(state="normal")
        self.reasons.delete("1.0", "end")
        for r in rec.reasons:
            self.reasons.insert("end", "• " + r + "\n")
        if rec.villain_range is not None and sit.street == "preflop":
            self.reasons.insert("end", f"range {rec.villain_range_pct:.0f}%: {rec.villain_range.to_string()[:160]}\n")
        for e in rec.exploits:
            self.reasons.insert("end", "➜ " + e + "\n")
        self.reasons.configure(state="disabled")
        self.set_status(f"{sit.street} | {cards_str(sit.hero_cards, True)} | {rec.hand_class}")

    def new_hand(self):
        self.hero.set("")
        self.board.set("")
        self.pot.set("1.5")
        self.to_call.set("0")
        self.hero_bet.set("0")
        self.n_limpers.set("0")
        self.n_callers.set("0")
        self.was_aggr.set(False)
        self.pre_state.set(PREFLOP_STATES[0][1])
        for r in self.opp_rows:
            r.pre.set("none")
            r.last.set("none")
            r.bet.set("0")
        self.rec_label.config(text="—", fg=FG)
        self.stats_label.config(text="")
        self.reasons.configure(state="normal")
        self.reasons.delete("1.0", "end")
        self.reasons.configure(state="disabled")
        self.hero_entry.focus_set()
        self.set_status("mana noua")

    def add_observation(self):
        idx = int(self.obs_target.get()) - 1
        row = self.opp_rows[idx]
        name = row.name.get().strip()
        if not name:
            self.set_status("adversarul nu are nume")
            return
        key = next((k for k, t in OBS_EVENTS if t == self.obs_event.get()), None)
        if not key:
            return
        st = self.db.get(name)
        st.observe(key)
        if key in ("vpip", "pfr", "3bet", "limp", "call_open"):
            # VPIP/PFR implica si oportunitatea; evenimentele compuse le tratam simplu
            pass
        self.db.save(name)
        self.set_status(st.summary())
        self._refresh_name_lists()

    def add_hand_all(self):
        for r in self.opp_rows:
            if r.active.get() and r.name.get().strip():
                self.db.get(r.name.get().strip()).new_hand()
        self.db.save()
        self.set_status("+1 mana pentru adversarii activi")

    def _refresh_name_lists(self):
        names = self.db.names()
        for r in self.opp_rows:
            r.name_cb.configure(values=names)

    # ------------------------------------------------------------ ferestre secundare
    def open_players(self):
        PlayersWindow(self)

    def open_sim(self):
        SimWindow(self)

    def open_calibrate(self):
        try:
            from ..watcher.calibrate import Calibrator
            from ..watcher.layout import LayoutProfile, list_layouts
        except ImportError as e:
            messagebox.showerror("Calibrare", f"modulul watcher nu e disponibil: {e}")
            return
        names = list_layouts()
        profile = LayoutProfile.load(names[0]) if names else None
        Calibrator(self, profile)

    def toggle_watcher(self):
        if self.watcher and self.watcher.running:
            self.watcher.stop()
            self.watch_btn.config(text="Watcher")
            self.set_status("watcher oprit")
            return
        try:
            from ..watcher.layout import LayoutProfile, list_layouts
            from ..watcher.watcher import TableWatcher
        except ImportError as e:
            messagebox.showerror("Watcher", f"modulul watcher nu e disponibil: {e}")
            return
        names = list_layouts()
        if not names:
            messagebox.showinfo("Watcher", "Nu exista niciun profil de layout. Apasa 'Calibrare' si defineste regiunile mesei.")
            return
        layout = LayoutProfile.load(self.settings.get("layout", names[0]) if self.settings.get("layout") in names else names[0])
        self.watcher = TableWatcher(layout, on_update=lambda snap: self.after(0, lambda: self.apply_snapshot(snap)))
        self.watcher.start()
        self.watch_btn.config(text="Watcher ●")
        self.set_status(f"watcher pornit pe profilul '{layout.name}'")

    def apply_snapshot(self, snap):
        bbm = _f(self.bb_money, 1.0) or 1.0
        changed = False
        if snap.hero_cards and len(snap.hero_cards) == 2:
            txt = " ".join(snap.hero_cards)
            if txt != self.hero.get():
                self.hero.set(txt)
                changed = True
        board_txt = " ".join(snap.board)
        if board_txt != self.board.get():
            self.board.set(board_txt)
            changed = True
        if snap.pot is not None:
            self.pot.set(f"{snap.pot / bbm:.2f}")
        if snap.to_call is not None:
            self.to_call.set(f"{snap.to_call / bbm:.2f}")
        if snap.hero_stack is not None:
            self.stack.set(f"{snap.hero_stack / bbm:.1f}")
        if snap.hero_bet is not None:
            self.hero_bet.set(f"{snap.hero_bet / bbm:.2f}")
        others = [s for s in snap.seats if s.seat != self.watcher.layout.hero_seat]
        for row, s in zip(self.opp_rows, others):
            if s.name:
                row.name.set(s.name)
            if s.stack is not None:
                row.stack.set(f"{s.stack / bbm:.1f}")
            if s.bet is not None:
                row.bet.set(f"{s.bet / bbm:.2f}")
        if snap.errors:
            self.set_status("; ".join(snap.errors)[:120])
        if changed and len(snap.hero_cards) == 2:
            self.analyze()


class PlayersWindow(tk.Toplevel):
    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Jucatori")
        self.configure(bg=BG)
        self.attributes("-topmost", True)
        self.geometry("520x360")
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=4, pady=4)
        self.listbox = tk.Listbox(left, width=18, bg=BG2, fg=FG, exportselection=False)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.show())
        ttk.Button(left, text="Sterge", command=self.delete).pack(fill="x", pady=2)
        self.text = tk.Text(self, bg=BG2, fg=FG, font=("Consolas", 9), wrap="word", relief="flat")
        self.text.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.refresh()

    def refresh(self):
        self.listbox.delete(0, "end")
        for n in self.app.db.names():
            self.listbox.insert("end", n)

    def show(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        st = self.app.db.get(self.listbox.get(sel[0]))
        self.text.delete("1.0", "end")
        self.text.insert("end", st.summary() + "\n\n")
        self.text.insert("end", f"maini: {st.hands}   net: {st.net_bb:+.1f}bb   incredere date: {100*st.confidence:.0f}%\n")
        self.text.insert("end", f"limp {100*st.limp:.0f}%  call open {100*st.call_open:.0f}%  steal {100*st.steal:.0f}%  "
                                f"fold-to-steal {100*st.fold_to_steal:.0f}%\n")
        self.text.insert("end", f"fold-to-bet {100*st.fold_to_bet_post:.0f}%  fold-to-raise {100*st.fold_to_raise_post:.0f}%  "
                                f"check-raise {100*st.check_raise:.0f}%  W$SD {100*st.wsd:.0f}%\n\n")
        self.text.insert("end", "Exploatari:\n")
        for e in st.exploits():
            self.text.insert("end", f" • {e}\n")
        self.text.insert("end", "\nRange estimat de open din CO: " + f"{st.open_range('CO', 6).percent():.0f}%\n")
        self.text.insert("end", "Range estimat de 3-bet vs CO (din BTN): " + f"{st.three_bet_range('CO', 'BTN').percent():.0f}%\n")

    def delete(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        name = self.listbox.get(sel[0])
        if messagebox.askyesno("Sterge", f"Stergi istoricul pentru {name}?"):
            self.app.db.delete(name)
            self.refresh()
            self.app._refresh_name_lists()


class SimWindow(tk.Toplevel):
    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Simulare")
        self.configure(bg=BG)
        self.attributes("-topmost", True)
        self.geometry("540x420")
        f = ttk.Frame(self)
        f.pack(fill="x", padx=4, pady=4)
        self.counts: Dict[str, tk.StringVar] = {}
        for i, (name, default) in enumerate([("nit", 1), ("tag", 1), ("lag", 1), ("fish", 1), ("maniac", 1)]):
            ttk.Label(f, text=name).grid(row=0, column=2 * i)
            v = tk.StringVar(value=str(default))
            self.counts[name] = v
            ttk.Spinbox(f, from_=0, to=8, textvariable=v, width=2).grid(row=0, column=2 * i + 1, padx=(0, 6))
        g = ttk.Frame(self)
        g.pack(fill="x", padx=4)
        self.kind = tk.StringVar(value="cash")
        ttk.Radiobutton(g, text="Cash (maini)", variable=self.kind, value="cash").pack(side="left")
        ttk.Radiobutton(g, text="Turneu SNG (turnee)", variable=self.kind, value="mtt").pack(side="left", padx=4)
        ttk.Label(g, text="Numar").pack(side="left")
        self.n = tk.StringVar(value="300")
        ttk.Entry(g, textvariable=self.n, width=6).pack(side="left", padx=2)
        ttk.Label(g, text="Iteratii MC").pack(side="left")
        self.iters = tk.StringVar(value="300")
        ttk.Entry(g, textvariable=self.iters, width=5).pack(side="left", padx=2)
        self.use_db = tk.BooleanVar(value=False)
        ttk.Checkbutton(g, text="scrie in DB jucatori", variable=self.use_db).pack(side="left", padx=4)
        self.run_btn = ttk.Button(g, text="Ruleaza", command=self.run)
        self.run_btn.pack(side="left", padx=4)
        self.text = tk.Text(self, bg=BG2, fg=FG, font=("Consolas", 9), relief="flat")
        self.text.pack(fill="both", expand=True, padx=4, pady=4)
        self.text.insert("end", "Hero = Advisor. Botii: nit (foarte strans), tag (solid), lag (larg-agresiv), "
                                "fish (loose-passive), maniac (hiper-agresiv).\nRezultatele in bb/100 au varianta mare la "
                                "sub 1000 de maini.\n")

    def log(self, msg: str):
        self.text.insert("end", msg + "\n")
        self.text.see("end")

    def run(self):
        from ..simulator import Table, Tournament
        bots: List[str] = []
        for name, v in self.counts.items():
            bots += [name] * int(_f(v, 0))
        if not bots:
            self.log("alege cel putin un bot")
            return
        n = int(_f(self.n, 100))
        iters = int(_f(self.iters, 300))
        kind = self.kind.get()
        db = self.app.db if self.use_db.get() else None
        self.run_btn.config(state="disabled")
        self.log(f"\n>>> {kind} cu {bots}, {n} {'maini' if kind == 'cash' else 'turnee'} ...")

        def progress(k, rep):
            self.after(0, lambda: self.log(f"  {k}: hero {rep.hero_net_bb:+.1f}bb" if kind == "cash" else f"  turneu {k}: loc {rep.finishes[-1]}"))

        def work():
            try:
                adv = Advisor(iterations=iters)
                if kind == "cash":
                    t = Table(bots, advisor=adv, db=db, seed=None or 0)
                    rep = t.run(n, progress=progress)
                    lines = [rep.summary(), "", "Profilurile invatate (din ce a vazut hero):"]
                    for nm in t.db.names():
                        lines.append("  " + t.db.get(nm).summary())
                else:
                    tr = Tournament(bots, advisor=adv, db=db, seed=0)
                    rep = tr.run(n, progress=progress)
                    lines = [rep.summary()]
                self.after(0, lambda: self.log("\n".join(lines)))
            except Exception as e:  # pragma: no cover
                self.after(0, lambda: self.log(f"eroare: {e}"))
            finally:
                self.after(0, lambda: self.run_btn.config(state="normal"))
        threading.Thread(target=work, daemon=True).start()


def main():
    try:
        from ..watcher.windows import set_dpi_awareness
        set_dpi_awareness()
    except Exception:
        pass
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
