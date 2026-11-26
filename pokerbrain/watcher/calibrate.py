"""Tool de calibrare (Tkinter): captureaza fereastra mesei (sau tot ecranul), lasa utilizatorul sa
faca zoom, sa deseneze regiuni, sa le numeasca si sa salveze profilul. Tot aici se captureaza
sabloanele de carti.

Cand este aleasa o fereastra, regiunile se salveaza RELATIV la fereastra (merg si daca masa e mutata).
Daca aplicatia isi protejeaza fereastra impotriva capturii (display affinity), acest lucru este
raportat; PokerBrain nu ocoleste protectia.

Rulare: python -m pokerbrain.watcher.calibrate [nume_profil]
"""
from __future__ import annotations
import sys
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from typing import List, Optional, Tuple

from PIL import Image, ImageTk


def fit_screenshot_to_window(img, vis_w: int, vis_h: int, tolerance: int = 24):
    """Un screenshot al ferestrei (Alt+PrtSc) include marginile invizibile de redimensionare (~8 px
    stanga/dreapta/jos). Daca imaginea e putin mai mare decat zona vizibila, o decupam centrat pe
    orizontala si aliniat sus, ca regiunile sa fie relative la aceeasi zona ca la captura directa."""
    w, h = img.size
    if (w, h) == (vis_w, vis_h):
        return img
    if 0 <= w - vis_w <= tolerance and 0 <= h - vis_h <= tolerance:
        left = (w - vis_w) // 2
        return img.crop((left, 0, left + vis_w, vis_h))
    return img

from .layout import LayoutProfile, CARD_REGIONS, TEXT_REGIONS, SEAT_FIELDS, templates_dir, list_layouts
from .capture import grab_screen, grab_window, crop
from .recognize import CardRecognizer
from .windows import list_windows, find_window, capture_blocked, CaptureBlocked, WindowInfo, IS_WINDOWS

HELP = ("1) Alege fereastra mesei din lista si apasa 'Captura' (sau 'Incarca imagine' pentru un screenshot facut de tine)   "
        "2) 'Zoom pe masa' + dreptunghi peste masa (optional)   3) alege regiunea din lista din stanga si deseneaz-o   "
        "4) Salveaza.   Fara fereastra aleasa se captureaza tot ecranul.")
FULL_SCREEN = "(tot ecranul)"


class Calibrator(tk.Toplevel):
    def __init__(self, master, profile: Optional[LayoutProfile] = None):
        super().__init__(master)
        self.title("PokerBrain - calibrare layout")
        self.profile = profile or LayoutProfile(name="default")
        self.screen: Optional[Image.Image] = None
        self.view: Tuple[int, int, int, int] = (0, 0, 1, 1)   # portiunea din captura afisata (x, y, w, h)
        self.scale = 1.0
        self.photo = None
        self.start = None
        self.rect = None
        self.zoom_mode = False
        self.windows: List[WindowInfo] = []
        self._build()
        self.refresh_windows()
        self.after(200, self.capture_initial)

    # ------------------------------------------------------------ constructie
    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Profil:").pack(side="left")
        self.name_var = tk.StringVar(value=self.profile.name)
        ttk.Entry(top, textvariable=self.name_var, width=10).pack(side="left", padx=4)
        ttk.Label(top, text="Locuri:").pack(side="left")
        self.seats_var = tk.IntVar(value=self.profile.n_seats)
        ttk.Spinbox(top, from_=2, to=10, textvariable=self.seats_var, width=3, command=self.refresh_list).pack(side="left", padx=4)
        ttk.Label(top, text="Fereastra:").pack(side="left")
        self.window_var = tk.StringVar(value=self.profile.window_title or FULL_SCREEN)
        self.window_cb = ttk.Combobox(top, textvariable=self.window_var, width=34)
        self.window_cb.pack(side="left", padx=2)
        ttk.Button(top, text="↻", width=2, command=self.refresh_windows).pack(side="left")
        ttk.Button(top, text="Captura", command=self.capture_now).pack(side="left", padx=4)
        ttk.Button(top, text="Captura in 3s", command=lambda: self.capture_delayed(3000)).pack(side="left", padx=2)
        ttk.Button(top, text="Incarca imagine", command=self.load_image).pack(side="left", padx=2)
        self.zoom_btn = ttk.Button(top, text="Zoom pe masa", command=self.start_zoom)
        self.zoom_btn.pack(side="left", padx=4)
        ttk.Button(top, text="Vedere completa", command=self.reset_view).pack(side="left", padx=2)
        ttk.Button(top, text="Salveaza", command=self.save).pack(side="left", padx=4)
        ttk.Button(top, text="Sablon carte", command=self.save_card_template).pack(side="left", padx=2)
        ttk.Label(self, text=HELP, wraplength=1200, justify="left").pack(fill="x", padx=4)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="y")
        self.listbox = tk.Listbox(left, width=22, height=30, exportselection=False)
        self.listbox.pack(fill="y", expand=True)
        self.refresh_list()
        ttk.Button(left, text="Sterge regiunea", command=self.delete_region).pack(fill="x")
        self.canvas = tk.Canvas(body, bg="black", cursor="cross")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<MouseWheel>", self.on_wheel)
        self.status = ttk.Label(self, text="")
        self.status.pack(fill="x")

    def keys(self):
        n = self.seats_var.get()
        keys = list(CARD_REGIONS) + list(TEXT_REGIONS)
        for s in range(1, n + 1):
            for f in SEAT_FIELDS:
                keys.append(f"seat_{s}_{f}")
        return keys

    def refresh_list(self):
        sel = self.listbox.curselection()
        self.listbox.delete(0, "end")
        for k in self.keys():
            mark = "x" if k in self.profile.regions else " "
            self.listbox.insert("end", f"[{mark}] {k}")
        if sel and sel[0] < self.listbox.size():
            self.listbox.selection_set(sel[0])

    def selected_key(self) -> Optional[str]:
        sel = self.listbox.curselection()
        if not sel:
            return None
        return self.listbox.get(sel[0])[4:]

    # ------------------------------------------------------------ ferestre
    def refresh_windows(self):
        self.windows = list_windows() if IS_WINDOWS else []
        values = [FULL_SCREEN] + [w.title for w in self.windows]
        self.window_cb.configure(values=values)
        if self.window_var.get() not in values and self.window_var.get() != FULL_SCREEN:
            # pastram textul (poate fi o parte din titlu, ex. 'NLHP'); se cauta ca substring
            pass

    def selected_window(self) -> Optional[WindowInfo]:
        txt = self.window_var.get().strip()
        if not txt or txt == FULL_SCREEN:
            return None
        for w in self.windows:
            if w.title == txt:
                return w
        return find_window(txt)

    # ------------------------------------------------------------ captura
    def capture_initial(self):
        if self.selected_window() is not None:
            self.capture_now()
        else:
            self.capture_delayed(700)

    def capture_now(self):
        """Captureaza fereastra aleasa (fara sa fie nevoie sa fie in fata) sau tot ecranul."""
        win = self.selected_window()
        if win is None:
            if self.window_var.get().strip() not in ("", FULL_SCREEN):
                self.status.config(text=f"fereastra '{self.window_var.get()}' nu este deschisa; captez tot ecranul")
            self.capture_delayed(500)
            return
        if capture_blocked(win.hwnd):
            self.screen = None
            self.canvas.delete("all")
            msg = (f"'{win.title}' isi protejeaza fereastra impotriva capturii de ecran (display affinity).\n\n"
                   "Clientul de poker nu permite citirea mesei de catre alte programe, iar PokerBrain nu "
                   "ocoleste aceasta protectie. Poti folosi introducerea manuala din fereastra principala, "
                   "sau watcher-ul cu un replayer / client care nu blocheaza captura.")
            self.status.config(text="captura blocata de aplicatie: " + win.title)
            messagebox.showwarning("Captura blocata", msg, parent=self)
            return
        self.withdraw()
        try:
            self.master.withdraw()
        except tk.TclError:
            pass
        self.update_idletasks()
        try:
            img = grab_window(win, bring_front=True)
        except CaptureBlocked as e:
            img = None
            err = str(e)
        else:
            err = ""
        finally:
            try:
                self.master.deiconify()
            except tk.TclError:
                pass
            self.deiconify()
            self.lift()
        if img is None:
            self.status.config(text=err or "captura a esuat")
            return
        self.screen = img
        self.view = (0, 0, img.size[0], img.size[1])
        self.render()
        self.status.config(text=f"captura ferestrei '{win.title}' {img.size[0]}x{img.size[1]}; regiunile se salveaza relativ la fereastra")

    def load_image(self):
        """Incarca un screenshot facut de utilizator (PrtSc = tot ecranul, Alt+PrtSc = fereastra activa).
        Cu o fereastra aleasa, imaginea e tratata ca fiind fereastra (regiuni relative); altfel ca tot ecranul."""
        path = filedialog.askopenfilename(parent=self, title="Alege screenshot-ul",
                                          filetypes=[("Imagini", "*.png *.jpg *.jpeg *.bmp *.webp"), ("Toate", "*.*")])
        if not path:
            return
        try:
            img = Image.open(path).convert("RGB")
        except OSError as e:
            messagebox.showerror("Imagine", f"nu pot deschide imaginea: {e}", parent=self)
            return
        win = self.selected_window()
        note = "tot ecranul (pixeli absoluti)"
        if win is not None:
            img = fit_screenshot_to_window(img, win.rect[2], win.rect[3])
            note = f"fereastra '{win.title}' (regiuni relative)"
            if img.size != (win.rect[2], win.rect[3]):
                note += f"; ATENTIE: imaginea are {img.size[0]}x{img.size[1]}, fereastra {win.rect[2]}x{win.rect[3]}"
        self.screen = img
        self.view = (0, 0, img.size[0], img.size[1])
        self.render()
        self.status.config(text=f"imagine incarcata {img.size[0]}x{img.size[1]}, interpretata ca {note}")

    def capture_delayed(self, ms: int):
        """Ascunde ferestrele PokerBrain, asteapta `ms` si captureaza tot ecranul."""
        self.withdraw()
        try:
            self.master.withdraw()
        except tk.TclError:
            pass
        self.after(ms, self.capture_screen)

    def capture_screen(self):
        try:
            self.screen = grab_screen()
        finally:
            try:
                self.master.deiconify()
            except tk.TclError:
                pass
            self.deiconify()
        self.lift()
        w, h = self.screen.size
        self.view = (0, 0, w, h)
        self.render()
        self.status.config(text=f"captura {w}x{h} (toate monitoarele); regiunile se salveaza in pixeli absoluti. "
                                f"Foloseste 'Zoom pe masa' ca sa lucrezi marit.")

    # ------------------------------------------------------------ afisare / zoom
    def render(self):
        if self.screen is None:
            return
        vx, vy, vw, vh = self.view
        img = self.screen.crop((vx, vy, vx + vw, vy + vh))
        max_w = max(400, self.winfo_screenwidth() - 260)
        max_h = max(300, self.winfo_screenheight() - 170)
        self.scale = min(max_w / vw, max_h / vh)
        disp = img.resize((max(1, int(vw * self.scale)), max(1, int(vh * self.scale))),
                          Image.LANCZOS if self.scale < 1 else Image.NEAREST)
        self.photo = ImageTk.PhotoImage(disp)
        self.canvas.config(width=disp.size[0], height=disp.size[1])
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.rect = None
        self.draw_regions()

    def to_screen(self, cx: float, cy: float) -> Tuple[int, int]:
        vx, vy, _, _ = self.view
        return int(vx + cx / self.scale), int(vy + cy / self.scale)

    def to_canvas(self, sx: float, sy: float) -> Tuple[float, float]:
        vx, vy, _, _ = self.view
        return (sx - vx) * self.scale, (sy - vy) * self.scale

    def draw_regions(self):
        self.canvas.delete("region")
        for k, (x, y, w, h) in self.profile.regions.items():
            x0, y0 = self.to_canvas(x, y)
            x1, y1 = self.to_canvas(x + w, y + h)
            color = "yellow" if k.startswith(("hero_card", "board")) else "cyan"
            self.canvas.create_rectangle(x0, y0, x1, y1, outline=color, width=1, tags="region")
            self.canvas.create_text(x0 + 2, y0 - 6, text=k, anchor="w", fill=color, font=("Segoe UI", 7), tags="region")

    def start_zoom(self):
        if self.screen is None:
            return
        self.zoom_mode = True
        self.zoom_btn.state(["pressed"])
        self.status.config(text="deseneaza un dreptunghi peste masa de poker")

    def reset_view(self):
        if self.screen is None:
            return
        self.view = (0, 0, self.screen.size[0], self.screen.size[1])
        self.render()

    def set_view(self, x: int, y: int, w: int, h: int):
        sw, sh = self.screen.size
        x, y = max(0, x), max(0, y)
        w, h = max(50, min(w, sw - x)), max(50, min(h, sh - y))
        self.view = (x, y, w, h)
        self.render()

    def on_wheel(self, e):
        """Rotita: zoom in/out in jurul cursorului."""
        if self.screen is None:
            return
        sx, sy = self.to_screen(e.x, e.y)
        vx, vy, vw, vh = self.view
        factor = 0.8 if e.delta > 0 else 1.25
        nw, nh = int(vw * factor), int(vh * factor)
        sw, sh = self.screen.size
        nw, nh = max(100, min(nw, sw)), max(60, min(nh, sh))
        rx, ry = (sx - vx) / vw, (sy - vy) / vh
        nx, ny = int(sx - rx * nw), int(sy - ry * nh)
        nx, ny = max(0, min(nx, sw - nw)), max(0, min(ny, sh - nh))
        self.view = (nx, ny, nw, nh)
        self.render()

    # ------------------------------------------------------------ desenare
    def on_press(self, e):
        self.start = (e.x, e.y)
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=2)

    def on_drag(self, e):
        if self.start and self.rect:
            self.canvas.coords(self.rect, self.start[0], self.start[1], e.x, e.y)

    def on_release(self, e):
        if not self.start or self.screen is None:
            return
        x0, y0 = self.start
        x1, y1 = e.x, e.y
        self.start = None
        if abs(x1 - x0) < 3 or abs(y1 - y0) < 3:
            return
        sx0, sy0 = self.to_screen(min(x0, x1), min(y0, y1))
        sx1, sy1 = self.to_screen(max(x0, x1), max(y0, y1))
        x, y, w, h = sx0, sy0, max(1, sx1 - sx0), max(1, sy1 - sy0)
        if self.zoom_mode:
            self.zoom_mode = False
            self.zoom_btn.state(["!pressed"])
            self.set_view(x, y, w, h)
            self.status.config(text=f"zoom pe {(x, y, w, h)}; acum alege regiunea din lista si deseneaz-o")
            return
        key = self.selected_key()
        if not key:
            messagebox.showinfo("Regiune", "Alege intai numele regiunii din lista (sau apasa 'Zoom pe masa').", parent=self)
            self.canvas.delete(self.rect)
            self.rect = None
            return
        self.profile.regions[key] = (x, y, w, h)
        self.refresh_list()
        self.draw_regions()
        idx = self.listbox.curselection()
        if idx and idx[0] + 1 < self.listbox.size():
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(idx[0] + 1)
            self.listbox.see(idx[0] + 1)
        self.status.config(text=f"{key} = {(x, y, w, h)}")

    def delete_region(self):
        key = self.selected_key()
        if key and key in self.profile.regions:
            del self.profile.regions[key]
            self.refresh_list()
            self.draw_regions()

    # ------------------------------------------------------------ salvare
    def save(self):
        self.profile.name = self.name_var.get().strip() or "default"
        self.profile.n_seats = self.seats_var.get()
        txt = self.window_var.get().strip()
        self.profile.window_title = "" if txt in ("", FULL_SCREEN) else txt
        path = self.profile.save()
        missing = self.profile.missing_keys()
        mode = f"relativ la fereastra '{self.profile.window_title}'" if self.profile.window_title else "pixeli absoluti"
        self.status.config(text=f"salvat {path} ({mode}); regiuni lipsa: {len(missing)}")

    def save_card_template(self):
        """Salveaza continutul regiunii selectate (hero_card_x / board_x) ca sablon pentru o carte."""
        key = self.selected_key()
        if not key or key not in self.profile.regions or not self.screen:
            messagebox.showinfo("Sablon", "Selecteaza o regiune de carte definita (hero_card_1, board_1, ...).", parent=self)
            return
        label = simpledialog.askstring("Sablon carte", "Ce carte se vede in regiune? (ex: As, Td, 9h; 'empty' pentru loc gol)",
                                       parent=self)
        if not label:
            return
        self.profile.name = self.name_var.get().strip() or "default"
        rec = CardRecognizer(templates_dir(self.profile.name), self.profile.card_template_size)
        try:
            path = rec.save_template(crop(self.screen, self.profile.regions[key]), label.strip())
        except ValueError as e:
            messagebox.showerror("Sablon", str(e), parent=self)
            return
        self.status.config(text=f"sablon salvat: {path}; lipsesc {len(rec.missing_templates())} carti")


def main(argv=None):
    from .windows import set_dpi_awareness
    set_dpi_awareness()
    argv = argv if argv is not None else sys.argv[1:]
    root = tk.Tk()
    root.withdraw()
    profile = None
    if argv:
        try:
            profile = LayoutProfile.load(argv[0])
        except OSError:
            profile = LayoutProfile(name=argv[0])
    elif list_layouts():
        profile = LayoutProfile.load(list_layouts()[0])
    cal = Calibrator(root, profile)
    cal.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
