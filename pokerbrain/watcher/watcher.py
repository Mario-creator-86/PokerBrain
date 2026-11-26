"""TableWatcher: citeste periodic regiunile din profilul de layout si produce un TableSnapshot."""
from __future__ import annotations
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .layout import LayoutProfile, templates_dir
from .capture import grab_screen, grab_window, crop, HAVE_PIL
from .recognize import CardRecognizer, TextReader
from .windows import find_window, CaptureBlocked


@dataclass
class SeatSnapshot:
    seat: int
    name: str = ""
    stack: Optional[float] = None
    bet: Optional[float] = None
    dealer: bool = False


@dataclass
class TableSnapshot:
    hero_cards: List[str] = field(default_factory=list)
    board: List[str] = field(default_factory=list)
    pot: Optional[float] = None
    to_call: Optional[float] = None
    hero_stack: Optional[float] = None
    hero_bet: Optional[float] = None
    seats: List[SeatSnapshot] = field(default_factory=list)
    timestamp: float = 0.0
    errors: List[str] = field(default_factory=list)

    def key(self) -> str:
        """Semnatura folosita pentru a detecta schimbari."""
        return f"{self.hero_cards}|{self.board}|{self.pot}|{self.to_call}|{[(s.name, s.bet) for s in self.seats]}"


class TableWatcher:
    def __init__(self, layout: LayoutProfile, on_update: Optional[Callable[[TableSnapshot], None]] = None):
        self.layout = layout
        self.cards = CardRecognizer(templates_dir(layout.name), layout.card_template_size,
                                    layout.card_match_threshold, layout.empty_variance_threshold)
        self.text = TextReader()
        self.on_update = on_update
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.last: Optional[TableSnapshot] = None
        self.last_key = ""

    # ------------------------------------------------------------ citire
    def read(self) -> TableSnapshot:
        snap = TableSnapshot(timestamp=time.time())
        if not HAVE_PIL:
            snap.errors.append("Pillow lipseste")
            return snap
        L = self.layout
        if L.window_title:
            win = find_window(L.window_title)
            if win is None:
                snap.errors.append(f"fereastra '{L.window_title}' nu este deschisa")
                return snap
            try:
                # fara adus in fata: watcher-ul nu fura focusul; daca PrintWindow nu merge si masa e
                # acoperita, citirea va fi gresita (eroare raportata de recunoastere)
                screen = grab_window(win, bring_front=False)
            except CaptureBlocked as e:
                snap.errors.append(str(e))
                return snap
        else:
            screen = grab_screen()

        def card_at(key: str) -> Optional[str]:
            r = L.region(key)
            if not r:
                return None
            label, _d = self.cards.recognize(crop(screen, r))
            return label

        def num_at(key: str) -> Optional[float]:
            r = L.region(key)
            if not r or not self.text.available:
                return None
            return self.text.read_number(crop(screen, r))

        def text_at(key: str) -> str:
            r = L.region(key)
            if not r or not self.text.available:
                return ""
            return self.text.read_text(crop(screen, r))

        if not self.cards.ready:
            snap.errors.append("fara sabloane de carti: ruleaza calibrarea si captureaza cartile")
        for k in ("hero_card_1", "hero_card_2"):
            c = card_at(k)
            if c:
                snap.hero_cards.append(c)
        for i in range(1, 6):
            c = card_at(f"board_{i}")
            if c:
                snap.board.append(c)
            else:
                break
        snap.pot = num_at("pot")
        snap.to_call = num_at("to_call")
        snap.hero_stack = num_at("hero_stack")
        snap.hero_bet = num_at("hero_bet")
        if not self.text.available and any(L.region(k) for k in ("pot", "to_call", "hero_stack")):
            snap.errors.append("OCR indisponibil (instaleaza Tesseract + pytesseract); introdu potul/stack-urile manual")
        for s in range(1, L.n_seats + 1):
            ss = SeatSnapshot(seat=s)
            ss.name = text_at(f"seat_{s}_name")
            ss.stack = num_at(f"seat_{s}_stack")
            ss.bet = num_at(f"seat_{s}_bet")
            r = L.region(f"seat_{s}_dealer")
            if r:
                img = crop(screen, r)
                ss.dealer = not self.cards.is_empty(img)
            snap.seats.append(ss)
        return snap

    # ------------------------------------------------------------ polling
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                snap = self.read()
                self.last = snap
                k = snap.key()
                if k != self.last_key:
                    self.last_key = k
                    if self.on_update:
                        self.on_update(snap)
            except Exception as e:  # pragma: no cover
                snap = TableSnapshot(timestamp=time.time(), errors=[f"eroare la citire: {e}"])
                self.last = snap
                if self.on_update:
                    self.on_update(snap)
            self._stop.wait(self.layout.poll_seconds)
