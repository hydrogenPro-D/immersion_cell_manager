"""Guards for the startup splash and icon wiring (each one is easy to break
silently; see SPLASH_AND_ICON_GUIDE.md)."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestStartup(unittest.TestCase):

    def test_splash_does_not_import_the_gui_package(self):
        # Importing src.gui would load the whole GUI before the splash shows.
        source = (ROOT / "src" / "splash.py").read_text(encoding="utf-8")
        imported = {n.module for n in ast.walk(ast.parse(source))
                    if isinstance(n, ast.ImportFrom) and n.module}
        self.assertEqual([m for m in imported if m.startswith("src.gui")], [])

    def test_taskbar_identity_is_claimed_before_qapplication(self):
        # Windows binds the taskbar button when the first window appears.
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        claim = source.index("claim_taskbar_identity()")
        app = source.index("QApplication(sys.argv)")
        self.assertLess(claim, app)

    def test_build_ships_both_icon_files(self):
        # The window uses the .ico, the splash the .png; a missing .png only
        # shows up as a blank splash in the built exe.
        from tools import generate_executable as build
        self.assertIn("app_icon.ico", build.SHIPPED_ICONS)
        self.assertIn("app_icon.png", build.SHIPPED_ICONS)
        for name in build.SHIPPED_ICONS:
            self.assertTrue((ROOT / "assets" / name).exists(), name)
        spec = (ROOT / "tools" / "Immersion Cell Manager.spec").read_text(encoding="utf-8")
        self.assertIn("app_icon.ico", spec)

    def test_splash_fades_the_pixmap_not_the_window(self):
        # setWindowOpacity on the translucent splash renders badly on Windows.
        from PyQt6.QtWidgets import QApplication
        from src.splash import PULSE_PERIOD, Splash
        app = QApplication.instance() or QApplication([])
        splash = Splash()
        for _ in range(PULSE_PERIOD):
            splash._tick()
            self.assertEqual(splash.windowOpacity(), 1.0)
        splash.finish()
        for _ in range(PULSE_PERIOD):
            splash._tick()
            self.assertEqual(splash.windowOpacity(), 1.0)
        self.assertEqual(splash._opacity, 0.0)  # fully faded out
        app.processEvents()

    def test_extra_breath_keeps_window_hidden_until_reveal(self):
        # The window is ready but stays invisible while the splash takes exactly
        # one more full breath; then it's revealed and the fade runs.
        from PyQt6.QtWidgets import QApplication, QWidget
        from src.splash import FADE_TICKS, PULSE_PERIOD, Splash
        app = QApplication.instance() or QApplication([])
        splash, window = Splash(), QWidget()
        for _ in range(7):  # mid-breath
            splash._tick()
        window.setWindowOpacity(0.0)
        splash.finish(window, extra_breaths=1)
        held = 0
        while not splash._closing:
            self.assertEqual(window.windowOpacity(), 0.0)
            splash._tick()
            held += 1
        self.assertEqual(held, PULSE_PERIOD)  # exactly one whole breath
        self.assertEqual(window.windowOpacity(), 1.0)
        for _ in range(FADE_TICKS):
            splash._tick()
        self.assertEqual(splash._opacity, 0.0)
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
