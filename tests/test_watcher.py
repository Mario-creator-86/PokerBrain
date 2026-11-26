import os
import tempfile
import unittest

from PIL import Image, ImageDraw

import numpy as np

from pokerbrain.watcher.recognize import parse_number, CardRecognizer, TextReader, otsu_threshold, find_tesseract
from pokerbrain.watcher.layout import LayoutProfile


def _card_image(label: str, color=(200, 30, 30)) -> Image.Image:
    img = Image.new("RGB", (40, 56), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((6, 4), label[0], fill=color)
    d.rectangle((10, 28, 30, 48), fill=color if label[1] in "dh" else (20, 20, 20))
    if label[1] in "sc":
        d.ellipse((14, 32, 26, 44), fill=(255, 255, 255))
    return img


class TestRecognize(unittest.TestCase):
    def test_parse_number(self):
        self.assertEqual(parse_number("$1,234.5"), 1234.5)
        self.assertEqual(parse_number("2.5k"), 2500.0)
        self.assertEqual(parse_number("1,5"), 1.5)
        self.assertEqual(parse_number("Pot: 37"), 37.0)
        self.assertIsNone(parse_number("abc"))
        self.assertIsNone(parse_number(""))

    def test_card_templates_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            rec = CardRecognizer(d, size=(24, 32), threshold=0.3)
            self.assertFalse(rec.ready)
            for lab in ("As", "Kd", "Th", "7c"):
                rec.save_template(_card_image(lab), lab)
            rec.save_template(Image.new("RGB", (40, 56), (30, 90, 40)), "empty")
            self.assertTrue(rec.ready)
            label, dist = rec.recognize(_card_image("Kd"))
            self.assertEqual(label, "Kd")
            label, _ = rec.recognize(Image.new("RGB", (40, 56), (30, 90, 40)))
            self.assertIsNone(label)
            self.assertEqual(len(rec.missing_templates()), 48)
            with self.assertRaises(ValueError):
                rec.save_template(_card_image("As"), "Zz")

    def test_otsu_and_prep(self):
        a = np.array([[10] * 50 + [200] * 50] * 10, dtype=np.uint8)
        thr = otsu_threshold(a)
        self.assertTrue(10 <= thr < 200)
        img = Image.new("RGB", (60, 20), (20, 70, 35))
        ImageDraw.Draw(img).text((4, 4), "148", fill=(240, 240, 240))
        out = TextReader._prep(img)
        self.assertEqual(out.size, (60 * 4 + 24, 20 * 4 + 24))
        arr = np.asarray(out)
        self.assertEqual(arr[0, 0], 255)            # margine alba
        self.assertGreater((arr == 255).mean(), 0.5)  # text negru pe alb, fundalul majoritar

    @unittest.skipIf(find_tesseract() is None, "Tesseract nu este instalat")
    def test_ocr_reads_poker_amounts(self):
        from PIL import ImageFont
        tr = TextReader()
        self.assertTrue(tr.available)
        font = ImageFont.truetype("arial.ttf", 20)
        ok = 0
        samples = ["148", "Pot: 37", "1,250", "25.5", "$0.50"]
        for s in samples:
            img = Image.new("RGB", (150, 34), (20, 70, 35))
            ImageDraw.Draw(img).text((6, 4), s, fill=(240, 240, 240), font=font)
            if tr.read_number(img) == parse_number(s):
                ok += 1
        self.assertGreaterEqual(ok, 4, f"OCR a citit corect doar {ok}/{len(samples)}")

    def test_calibrator_zoom_mapping(self):
        """Zoom-ul pe masa: coordonatele desenate pe canvas se traduc corect in pixeli de ecran."""
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("fara display")
        root.withdraw()
        try:
            from pokerbrain.watcher.calibrate import Calibrator
            cal = Calibrator(root, LayoutProfile(name="t"))
            cal.withdraw()
            # inlocuim captura programata cu o imagine sintetica
            for after_id in cal.tk.call("after", "info"):
                cal.after_cancel(after_id)
            cal.screen = Image.new("RGB", (2400, 1200), (0, 80, 0))
            cal.reset_view()
            self.assertEqual(cal.view, (0, 0, 2400, 1200))
            cal.set_view(600, 300, 400, 200)
            self.assertEqual(cal.view, (600, 300, 400, 200))
            cx, cy = cal.to_canvas(700, 350)
            self.assertEqual(cal.to_screen(cx, cy), (700, 350))
            # desenam o regiune pe canvas in modul zoom
            cal.listbox.selection_set(0)  # hero_card_1
            x0, y0 = cal.to_canvas(650, 320)
            x1, y1 = cal.to_canvas(690, 380)
            E = type("E", (), {})
            e0, e1 = E(), E()
            e0.x, e0.y = x0, y0
            e1.x, e1.y = x1, y1
            cal.on_press(e0)
            cal.on_release(e1)
            x, y, w, h = cal.profile.regions["hero_card_1"]
            self.assertAlmostEqual(x, 650, delta=2)
            self.assertAlmostEqual(y, 320, delta=2)
            self.assertAlmostEqual(w, 40, delta=3)
            self.assertAlmostEqual(h, 60, delta=3)
            # modul zoom: dreptunghiul devine noua vedere
            cal.start_zoom()
            cal.on_press(e0)
            cal.on_release(e1)
            self.assertEqual(cal.view[0], x)
            self.assertFalse(cal.zoom_mode)
        finally:
            root.destroy()

    def test_windows_helpers(self):
        """Enumerarea ferestrelor, dreptunghiul si detectarea protectiei la captura, pe o fereastra Tk proprie."""
        import sys
        if sys.platform != "win32":
            self.skipTest("doar pe Windows")
        import tkinter as tk
        from pokerbrain.watcher import windows as W
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("fara display")
        try:
            title = "CalibTestWindow-7f3a"
            root.title(title)
            root.geometry("300x200+100+100")
            root.update()
            wins = W.list_windows()
            mine = [w for w in wins if w.title == title]
            self.assertEqual(len(mine), 1, [w.title for w in wins][:10])
            w = mine[0]
            self.assertGreater(w.rect[2], 100)
            self.assertGreater(w.rect[3], 100)
            self.assertIsNotNone(W.find_window("calibtestwindow"))
            self.assertIsNone(W.find_window("fereastra-care-nu-exista-9z9z"))
            self.assertFalse(W.capture_blocked(w.hwnd))
            self.assertEqual(W.display_affinity(w.hwnd), W.WDA_NONE)
            img = W.capture_window(w.hwnd)  # None daca procesul de test nu e DPI-aware
            if img is not None:
                self.assertEqual(img.size[0], w.rect[2])
                self.assertEqual(img.size[1], w.rect[3])
            # excluderea implicita a ferestrelor PokerBrain
            self.assertFalse(any("PokerBrain" in x.title for x in W.list_windows()))
        finally:
            root.destroy()

    def test_fit_screenshot_to_window(self):
        from pokerbrain.watcher.calibrate import fit_screenshot_to_window
        img = Image.new("RGB", (634, 731), (0, 0, 0))
        img.putpixel((8, 0), (255, 0, 0))  # coltul stanga-sus al zonei vizibile
        out = fit_screenshot_to_window(img, 618, 723)
        self.assertEqual(out.size, (618, 723))
        self.assertEqual(out.getpixel((0, 0)), (255, 0, 0))
        same = Image.new("RGB", (618, 723))
        self.assertIs(fit_screenshot_to_window(same, 618, 723), same)
        big = Image.new("RGB", (2000, 1000))
        self.assertIs(fit_screenshot_to_window(big, 618, 723), big)

    def test_layout_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = LayoutProfile(name="t", regions={"hero_card_1": (10, 20, 30, 40)}, n_seats=6, window_title="NLHP")
            path = p.save(os.path.join(d, "t.json"))
            q = LayoutProfile.load(path)
            self.assertEqual(q.region("hero_card_1"), (10, 20, 30, 40))
            self.assertEqual(q.window_title, "NLHP")
            self.assertIn("board_1", q.missing_keys())
            self.assertNotIn("hero_card_1", q.missing_keys())


if __name__ == "__main__":
    unittest.main()
