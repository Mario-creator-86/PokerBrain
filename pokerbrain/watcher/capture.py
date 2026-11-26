"""Captura de ecran (Pillow ImageGrab) a unei regiuni absolute sau a unei ferestre."""
from __future__ import annotations
import time
from typing import Optional, Tuple

try:
    from PIL import Image, ImageGrab
    HAVE_PIL = True
except ImportError:  # pragma: no cover
    Image = None
    ImageGrab = None
    HAVE_PIL = False

from .windows import (WindowInfo, capture_window, capture_blocked, bring_to_front, window_rect, CaptureBlocked)


def grab_region(region: Tuple[int, int, int, int]):
    """Returneaza un PIL.Image RGB pentru regiunea (x, y, w, h), in pixeli fizici de ecran."""
    if not HAVE_PIL:
        raise RuntimeError("Pillow nu este instalat")
    x, y, w, h = region
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    return img.convert("RGB")


def grab_screen():
    if not HAVE_PIL:
        raise RuntimeError("Pillow nu este instalat")
    return ImageGrab.grab(all_screens=True).convert("RGB")


def crop(img, region: Tuple[int, int, int, int]):
    x, y, w, h = region
    return img.crop((x, y, x + w, y + h))


def grab_window(win: WindowInfo, bring_front: bool = True, settle_ms: int = 350):
    """Imaginea zonei vizibile a ferestrei. Intai PrintWindow (functioneaza si cand fereastra e
    acoperita); daca nu merge, o aduce in fata (optional) si captureaza ecranul in dreptunghiul ei.
    Ridica CaptureBlocked daca aplicatia si-a protejat fereastra impotriva capturii."""
    img = capture_window(win.hwnd)
    if img is not None:
        return img.convert("RGB")
    if capture_blocked(win.hwnd):
        raise CaptureBlocked(f"'{win.title}' blocheaza captura de ecran (display affinity); "
                             f"clientul nu permite citirea mesei")
    if bring_front:
        bring_to_front(win.hwnd)
        time.sleep(settle_ms / 1000.0)
    rect = window_rect(win.hwnd) or win.rect
    return grab_region(rect)
