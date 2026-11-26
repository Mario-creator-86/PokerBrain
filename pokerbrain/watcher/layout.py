"""Profiluri de layout: regiunile de pe ecran (in pixeli absoluti) unde se afla cartile, potul,
stack-urile si numele jucatorilor. Se salveaza ca JSON in pokerbrain/data/layouts/<nume>.json."""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

Region = Tuple[int, int, int, int]  # x, y, w, h

# numele regiunilor cunoscute; seat_N_* pentru N = 1..9 (1 = hero)
CARD_REGIONS = ["hero_card_1", "hero_card_2", "board_1", "board_2", "board_3", "board_4", "board_5"]
TEXT_REGIONS = ["pot", "to_call", "hero_stack", "hero_bet"]
SEAT_FIELDS = ["name", "stack", "bet", "dealer"]


def layouts_dir() -> str:
    d = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "layouts")
    os.makedirs(d, exist_ok=True)
    return d


def templates_dir(profile_name: str) -> str:
    d = os.path.join(layouts_dir(), f"{profile_name}_templates")
    os.makedirs(d, exist_ok=True)
    return d


def list_layouts() -> List[str]:
    return sorted(f[:-5] for f in os.listdir(layouts_dir()) if f.endswith(".json"))


@dataclass
class LayoutProfile:
    name: str = "default"
    regions: Dict[str, Region] = field(default_factory=dict)
    n_seats: int = 6
    hero_seat: int = 1
    # titlul (sau o parte din el) ferestrei mesei; cand e setat, regiunile sunt RELATIVE la coltul
    # stanga-sus al zonei vizibile a ferestrei si profilul merge si daca masa este mutata
    window_title: str = ""
    # scalarea sabloanelor de carti (latime x inaltime la care se compara)
    card_template_size: Tuple[int, int] = (24, 32)
    card_match_threshold: float = 0.22   # distanta medie normalizata maxima pentru o potrivire
    empty_variance_threshold: float = 0.012  # sub aceasta varianta regiunea e considerata goala
    poll_seconds: float = 0.8
    notes: str = ""

    def region(self, key: str) -> Optional[Region]:
        r = self.regions.get(key)
        return tuple(r) if r else None

    def seat_region(self, seat: int, field_name: str) -> Optional[Region]:
        return self.region(f"seat_{seat}_{field_name}")

    def expected_keys(self) -> List[str]:
        keys = list(CARD_REGIONS) + list(TEXT_REGIONS)
        for s in range(1, self.n_seats + 1):
            for f in SEAT_FIELDS:
                keys.append(f"seat_{s}_{f}")
        return keys

    def missing_keys(self) -> List[str]:
        return [k for k in self.expected_keys() if k not in self.regions]

    def save(self, path: Optional[str] = None) -> str:
        path = path or os.path.join(layouts_dir(), f"{self.name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
        return path

    @classmethod
    def load(cls, name_or_path: str) -> "LayoutProfile":
        path = name_or_path if name_or_path.endswith(".json") else os.path.join(layouts_dir(), f"{name_or_path}.json")
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        d["regions"] = {k: tuple(v) for k, v in d.get("regions", {}).items()}
        d["card_template_size"] = tuple(d.get("card_template_size", (24, 32)))
        return cls(**d)
