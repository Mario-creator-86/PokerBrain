"""Recunoasterea cartilor (template matching pe sabloane capturate de utilizator) si a textului
(pytesseract, optional). Fara dependente obligatorii in afara de Pillow si numpy."""
from __future__ import annotations
import os
import re
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = None
    ImageOps = None

try:
    import pytesseract  # type: ignore
    HAVE_TESSERACT = True
except ImportError:
    pytesseract = None
    HAVE_TESSERACT = False

from ..cards import card as parse_card, RANKS, SUITS


def _to_vector(img, size: Tuple[int, int]) -> np.ndarray:
    """Imagine -> vector normalizat (grayscale redimensionat, medie 0, norma 1)."""
    g = img.convert("L").resize(size, Image.BILINEAR)
    v = np.asarray(g, dtype=np.float32).ravel() / 255.0
    v = v - v.mean()
    n = np.linalg.norm(v)
    return v / n if n > 1e-6 else v


def _color_signature(img) -> Tuple[float, float, float]:
    """Culoarea medie (r, g, b) normalizata, folosita pentru a distinge culorile cartilor
    in cliente cu 4 culori (rosu/negru/verde/albastru)."""
    a = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    # pixelii "colorati" (nu fundalul alb al cartii)
    sat = a.max(axis=2) - a.min(axis=2)
    mask = sat > 0.25
    if mask.sum() < 5:
        return (0.0, 0.0, 0.0)
    sel = a[mask]
    return tuple(float(x) for x in sel.mean(axis=0))


class CardRecognizer:
    """Compara regiunea cu sabloanele salvate (ex: As.png, Td.png). Returneaza codul cartii sau None."""

    def __init__(self, template_dir: str, size: Tuple[int, int] = (24, 32), threshold: float = 0.22,
                 empty_variance: float = 0.012):
        self.dir = template_dir
        self.size = size
        self.threshold = threshold
        self.empty_variance = empty_variance
        self.templates: Dict[str, np.ndarray] = {}
        self.colors: Dict[str, Tuple[float, float, float]] = {}
        self.empty: Optional[np.ndarray] = None
        self.reload()

    def reload(self) -> None:
        self.templates.clear()
        if not os.path.isdir(self.dir) or Image is None:
            return
        for f in os.listdir(self.dir):
            if not f.lower().endswith(".png"):
                continue
            label = f[:-4]
            try:
                img = Image.open(os.path.join(self.dir, f))
            except OSError:
                continue
            if label == "empty":
                self.empty = _to_vector(img, self.size)
                continue
            try:
                parse_card(label)
            except ValueError:
                continue
            self.templates[label] = _to_vector(img, self.size)
            self.colors[label] = _color_signature(img)

    @property
    def ready(self) -> bool:
        return len(self.templates) >= 2

    def save_template(self, img, label: str) -> str:
        if label != "empty":
            parse_card(label)
        os.makedirs(self.dir, exist_ok=True)
        path = os.path.join(self.dir, f"{label}.png")
        img.save(path)
        self.reload()
        return path

    def is_empty(self, img) -> bool:
        g = np.asarray(img.convert("L"), dtype=np.float32) / 255.0
        if g.var() < self.empty_variance:
            return True
        if self.empty is not None and np.linalg.norm(self.empty) > 1e-6:
            v = _to_vector(img, self.size)
            if 1.0 - float(np.dot(v, self.empty)) < self.threshold * 0.5:
                return True
        return False

    def recognize(self, img) -> Tuple[Optional[str], float]:
        """Returneaza (eticheta, distanta). Eticheta None daca nu e nicio carte / nicio potrivire."""
        if not self.templates:
            return None, 1.0
        if self.is_empty(img):
            return None, 0.0
        v = _to_vector(img, self.size)
        col = _color_signature(img)
        best, best_d = None, 1e9
        for label, t in self.templates.items():
            d = 1.0 - float(np.dot(v, t))  # distanta cosinus: 0 = identic, 1 = necorelat
            # penalizam diferentele de culoare (ajuta la distingerea culorilor cu aceeasi forma)
            c = self.colors.get(label, (0, 0, 0))
            d += 0.15 * sum((a - b) ** 2 for a, b in zip(c, col))
            if d < best_d:
                best, best_d = label, d
        if best_d > self.threshold:
            return None, best_d
        return best, best_d

    def missing_templates(self) -> List[str]:
        return [r + s for r in RANKS for s in SUITS if (r + s) not in self.templates]


_NUM = re.compile(r"[-+]?\d[\d.,]*")


def otsu_threshold(a: np.ndarray) -> int:
    """Pragul Otsu pentru o imagine grayscale uint8 (maximizeaza varianta intre clase)."""
    hist = np.bincount(a.ravel(), minlength=256).astype(np.float64)
    total = a.size
    sum_total = float(np.dot(np.arange(256), hist))
    sum_b = 0.0
    w_b = 0.0
    best, thr = 0.0, 128
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_total - sum_b) / w_f
        between = w_b * w_f * (m_b - m_f) ** 2
        if between > best:
            best, thr = between, t
    return thr


# locatii uzuale ale binarului Tesseract pe Windows (installerul UB-Mannheim nu il pune in PATH)
_TESSERACT_CANDIDATES = [
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tesseract-OCR", "tesseract.exe"),
    os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Tesseract-OCR", "tesseract.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tesseract.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Tesseract-OCR", "tesseract.exe"),
    "/usr/bin/tesseract", "/usr/local/bin/tesseract", "/opt/homebrew/bin/tesseract",
]


def find_tesseract() -> Optional[str]:
    """Calea catre tesseract: din PATH, altfel din locatiile uzuale de instalare."""
    from shutil import which
    found = which("tesseract")
    if found:
        return found
    for c in _TESSERACT_CANDIDATES:
        if c and os.path.isfile(c):
            return c
    return None


class TextReader:
    """Citeste text/numere din regiuni. Foloseste pytesseract daca exista; altfel `available` = False."""

    def __init__(self, tesseract_cmd: Optional[str] = None):
        self.available = HAVE_TESSERACT
        self.cmd: Optional[str] = None
        if HAVE_TESSERACT:
            cmd = tesseract_cmd or find_tesseract()
            if cmd:
                pytesseract.pytesseract.tesseract_cmd = cmd
                self.cmd = cmd
            try:
                pytesseract.get_tesseract_version()
            except Exception:
                self.available = False

    @staticmethod
    def _prep(img, scale: int = 4, pad: int = 12):
        """Pregateste regiunea pentru Tesseract: marire LANCZOS, binarizare Otsu, text negru pe alb,
        margine alba. (Pe sume stil poker: 173/180 corecte fata de 105/180 cu prag pe medie.)"""
        g = img.convert("L")
        w, h = g.size
        g = g.resize((max(1, w * scale), max(1, h * scale)), Image.LANCZOS)
        a = np.asarray(g, dtype=np.uint8)
        thr = otsu_threshold(a)
        binar = a > thr
        if binar.mean() < 0.5:  # textul trebuie sa fie negru pe alb; daca fundalul e inchis, inversam
            binar = ~binar
        out = Image.fromarray(np.where(binar, 255, 0).astype(np.uint8))
        return ImageOps.expand(out, border=pad, fill=255)

    def read_text(self, img) -> str:
        if not self.available:
            return ""
        try:
            return pytesseract.image_to_string(self._prep(img), config="--psm 7").strip()
        except Exception:
            return ""

    def read_number(self, img) -> Optional[float]:
        if not self.available:
            return None
        try:
            txt = pytesseract.image_to_string(self._prep(img), config="--psm 7 -c tessedit_char_whitelist=0123456789.,$€kKmM")
        except Exception:
            return None
        return parse_number(txt)


def parse_number(txt: str) -> Optional[float]:
    """'$1,234.5' -> 1234.5; '2.5k' -> 2500; '1,5' -> 1.5 (virgula ca decimal daca e singura si urmata de 1-2 cifre)."""
    if not txt:
        return None
    t = txt.strip().lower().replace(" ", "")
    mult = 1.0
    if t.endswith("k"):
        mult = 1000.0
        t = t[:-1]
    elif t.endswith("m"):
        mult = 1_000_000.0
        t = t[:-1]
    m = _NUM.search(t)
    if not m:
        return None
    s = m.group(0)
    if "," in s and "." not in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            s = parts[0] + "." + parts[1]
        else:
            s = s.replace(",", "")
    else:
        s = s.replace(",", "")
    try:
        return float(s) * mult
    except ValueError:
        return None
