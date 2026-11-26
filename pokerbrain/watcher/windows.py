"""Ferestre de nivel inalt pe Windows (ctypes): enumerare, dreptunghi, adus in fata, DPI awareness.
Pe alte platforme functiile intorc liste goale / None, iar watcher-ul lucreaza cu ecranul intreg."""
from __future__ import annotations
import ctypes
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

IS_WINDOWS = sys.platform == "win32"
Rect = Tuple[int, int, int, int]  # x, y, w, h

if IS_WINDOWS:
    import ctypes.wintypes as wt
    _user32 = ctypes.windll.user32
    _dwm = ctypes.windll.dwmapi
    _shcore = getattr(ctypes.windll, "shcore", None)
else:  # pragma: no cover
    _user32 = _dwm = _shcore = None

_DWMWA_CLOAKED = 14
_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_SW_RESTORE = 9

_dpi_done = False


def set_dpi_awareness() -> bool:
    """Face procesul DPI-aware (per monitor) ca GetWindowRect si captura sa fie in aceiasi pixeli fizici.
    Trebuie apelata inainte de crearea oricarei ferestre (Tk)."""
    global _dpi_done
    if not IS_WINDOWS or _dpi_done:
        return _dpi_done
    ok = False
    try:
        # PER_MONITOR_AWARE_V2 = -4 (Windows 10 1703+)
        ok = bool(_user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)))
    except (AttributeError, OSError):
        ok = False
    if not ok and _shcore is not None:
        try:
            ok = _shcore.SetProcessDpiAwareness(2) == 0  # PROCESS_PER_MONITOR_DPI_AWARE
        except (AttributeError, OSError):
            ok = False
    if not ok:
        try:
            ok = bool(_user32.SetProcessDPIAware())
        except (AttributeError, OSError):
            ok = False
    _dpi_done = ok or is_dpi_aware()
    return _dpi_done


def is_dpi_aware() -> bool:
    if not IS_WINDOWS:
        return True
    try:
        return bool(_user32.IsProcessDPIAware())
    except (AttributeError, OSError):
        return False


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    rect: Rect

    def __str__(self) -> str:
        x, y, w, h = self.rect
        return f"{self.title}  [{w}x{h} @ {x},{y}]"


def _is_cloaked(hwnd: int) -> bool:
    val = wt.DWORD(0)
    try:
        _dwm.DwmGetWindowAttribute(wt.HWND(hwnd), _DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val))
    except OSError:
        return False
    return val.value != 0


def window_rect(hwnd: int) -> Optional[Rect]:
    """Dreptunghiul vizibil al ferestrei (fara marginile invizibile), in pixeli de ecran."""
    if not IS_WINDOWS:
        return None
    r = wt.RECT()
    try:
        res = _dwm.DwmGetWindowAttribute(wt.HWND(hwnd), _DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r))
    except OSError:
        res = 1
    if res != 0:
        if not _user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(r)):
            return None
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None
    return (r.left, r.top, w, h)


def window_title(hwnd: int) -> str:
    n = _user32.GetWindowTextLengthW(wt.HWND(hwnd))
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    _user32.GetWindowTextW(wt.HWND(hwnd), buf, n + 1)
    return buf.value


def list_windows(exclude_substrings: Tuple[str, ...] = ("PokerBrain",)) -> List[WindowInfo]:
    """Ferestrele vizibile, cu titlu, necloaked, care nu sunt tool windows, ordonate ca pe ecran (z-order)."""
    if not IS_WINDOWS:
        return []
    out: List[WindowInfo] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lp):
        if not _user32.IsWindowVisible(hwnd):
            return True
        title = window_title(hwnd)
        if not title or title == "Program Manager":
            return True
        if any(s in title for s in exclude_substrings):
            return True
        ex = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        if ex & _WS_EX_TOOLWINDOW:
            return True
        if _is_cloaked(hwnd):
            return True
        rect = window_rect(hwnd)
        if rect is None or rect[0] <= -20000 or rect[2] < 80 or rect[3] < 60:
            return True
        out.append(WindowInfo(int(hwnd), title, rect))
        return True

    _user32.EnumWindows(cb, 0)
    return out


def find_window(title_substring: str) -> Optional[WindowInfo]:
    """Prima fereastra vizibila al carei titlu contine textul dat (fara a tine cont de majuscule)."""
    if not title_substring:
        return None
    needle = title_substring.lower()
    for w in list_windows():
        if needle in w.title.lower():
            return w
    return None


def bring_to_front(hwnd: int) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        if _user32.IsIconic(wt.HWND(hwnd)):
            _user32.ShowWindow(wt.HWND(hwnd), _SW_RESTORE)
        return bool(_user32.SetForegroundWindow(wt.HWND(hwnd)))
    except OSError:
        return False


def is_minimized(hwnd: int) -> bool:
    if not IS_WINDOWS:
        return False
    return bool(_user32.IsIconic(wt.HWND(hwnd)))


WDA_NONE = 0x0
WDA_MONITOR = 0x1
WDA_EXCLUDEFROMCAPTURE = 0x11


def display_affinity(hwnd: int) -> Optional[int]:
    """Setarea de 'display affinity' a ferestrei (orice proces). 0x11 = fereastra se exclude din capturi."""
    if not IS_WINDOWS:
        return None
    val = wt.DWORD(0)
    try:
        if not _user32.GetWindowDisplayAffinity(wt.HWND(hwnd), ctypes.byref(val)):
            return None
    except (AttributeError, OSError):
        return None
    return int(val.value)


def capture_blocked(hwnd: int) -> bool:
    """True daca aplicatia si-a protejat fereastra impotriva capturii de ecran (WDA_MONITOR /
    WDA_EXCLUDEFROMCAPTURE). Unii clienti de poker fac asta ca masura anti-asistenta; PokerBrain
    nu incearca sa ocoleasca protectia, doar o raporteaza."""
    aff = display_affinity(hwnd)
    return bool(aff) and aff != WDA_NONE


class CaptureBlocked(RuntimeError):
    pass


_PW_RENDERFULLCONTENT = 0x00000002
_SRCCOPY = 0x00CC0020
_DIB_RGB_COLORS = 0
_BI_RGB = 0


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]


def capture_window(hwnd: int):
    """Imaginea ferestrei (zona vizibila, fara marginile invizibile) obtinuta cu PrintWindow, care
    functioneaza si cand fereastra este acoperita de alte ferestre. Returneaza None daca nu se poate
    (fereastra minimizata, proces fara DPI awareness, continut negru/uniform)."""
    if not IS_WINDOWS or not is_dpi_aware() or is_minimized(hwnd):
        return None
    from PIL import Image
    gdi = ctypes.windll.gdi32
    full = wt.RECT()
    if not _user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(full)):
        return None
    fw, fh = full.right - full.left, full.bottom - full.top
    if fw <= 0 or fh <= 0:
        return None
    hdc_win = _user32.GetWindowDC(wt.HWND(hwnd))
    if not hdc_win:
        return None
    hdc_mem = gdi.CreateCompatibleDC(hdc_win)
    hbmp = gdi.CreateCompatibleBitmap(hdc_win, fw, fh)
    img = None
    try:
        old = gdi.SelectObject(hdc_mem, hbmp)
        ok = _user32.PrintWindow(wt.HWND(hwnd), hdc_mem, _PW_RENDERFULLCONTENT)
        if ok:
            bmi = _BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
            bmi.biWidth = fw
            bmi.biHeight = -fh  # top-down
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = _BI_RGB
            buf = ctypes.create_string_buffer(fw * fh * 4)
            lines = gdi.GetDIBits(hdc_mem, hbmp, 0, fh, buf, ctypes.byref(bmi), _DIB_RGB_COLORS)
            if lines == fh:
                img = Image.frombuffer("RGB", (fw, fh), buf.raw, "raw", "BGRX", 0, 1).copy()
        gdi.SelectObject(hdc_mem, old)
    finally:
        gdi.DeleteObject(hbmp)
        gdi.DeleteDC(hdc_mem)
        _user32.ReleaseDC(wt.HWND(hwnd), hdc_win)
    if img is None:
        return None
    # decupam la zona vizibila (DWM), care exclude marginile invizibile de redimensionare
    vis = window_rect(hwnd)
    if vis:
        ox, oy = vis[0] - full.left, vis[1] - full.top
        if 0 <= ox < fw and 0 <= oy < fh:
            img = img.crop((ox, oy, min(fw, ox + vis[2]), min(fh, oy + vis[3])))
    # continut uniform (negru/alb) = fereastra nu a desenat nimic
    extrema = img.convert("L").getextrema()
    if extrema[1] - extrema[0] < 8:
        return None
    return img
