"""Startup splash: the app icon, pulsing while the GUI loads.

Lives outside ``src.gui`` and imports only Qt, so it can be shown before the
heavy GUI import starts (see main.py). Also holds the small startup helpers:
the asset path resolver and the Windows taskbar identity.
"""

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

APP_USER_MODEL_ID = "HydrogenPro.ImmersionCellManager"

ICON_PX = 240          # on-screen size of the splash icon
PULSE_TICK_MS = 33     # about 30 fps
PULSE_PERIOD = 48      # ticks per cycle, about 1.6 s
MIN_OPACITY = 0.35
FADE_TICKS = 15        # about 0.5 s
# Extra full breaths after the app is ready: startup is quick enough that the
# pulse would barely show, and the breath is what reads as "loading".
EXTRA_BREATHS = 1


def asset_path(name: str) -> Path:
    """Path of a file in assets/. In the frozen build this resolves into
    _internal/assets, where tools/generate_executable.py copies the icons."""
    return Path(__file__).resolve().parents[1] / "assets" / name


def claim_taskbar_identity() -> None:
    """Give the process its own taskbar identity, so a run from source shows the
    app icon instead of python.exe's. Must run before the first window exists."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass  # cosmetic only


class Splash(QWidget):
    """Frameless, transparent window showing the pulsing app icon."""

    def __init__(self):
        # On top, so the closing fade plays over the revealed app, not behind it.
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setStyleSheet("background: transparent; border: none;")

        dpr = self.devicePixelRatioF()
        self._source = QPixmap(str(asset_path("app_icon.png"))).scaled(
            int(ICON_PX * dpr), int(ICON_PX * dpr),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self._source.setDevicePixelRatio(dpr)

        self._icon = QLabel(self)
        self._icon.setStyleSheet("background: transparent; border: none;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._icon)
        self.setFixedSize(ICON_PX, ICON_PX)

        self._frame = 0
        self._opacity = 1.0
        self._closing = False
        self._closing_from = 1.0
        self._closing_ticks = 0
        self._fade_ticks = FADE_TICKS
        self._hold_ticks = None  # extra-breath countdown, see finish()
        self._window = None
        self._apply(1.0)

        self._timer = QTimer(self)
        # Precise: Windows rounds the default coarse 33 ms timer up to ~47 ms.
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(PULSE_TICK_MS)
        self._center_on_cursor_screen()

    # ------------------------------------------------------------ Drawing
    def _apply(self, opacity: float) -> None:
        # Fade the pixmap, not the window: setWindowOpacity on a translucent
        # frameless window composites badly on Windows (greyed art, panel edge).
        self._opacity = opacity
        faded = QPixmap(self._source.size())
        faded.setDevicePixelRatio(self._source.devicePixelRatio())
        faded.fill(QColor(0, 0, 0, 0))
        painter = QPainter(faded)
        painter.setOpacity(opacity)
        painter.drawPixmap(0, 0, self._source)
        painter.end()
        self._icon.setPixmap(faded)

    def _tick(self) -> None:
        if self._closing:
            self._closing_ticks += 1
            t = min(1.0, self._closing_ticks / self._fade_ticks)
            self._apply(self._closing_from * (1.0 - t))
            if t >= 1.0:
                self._timer.stop()
                self.close()
                self.deleteLater()
            return
        # Triangle wave: reads as breathing (a square wave would blink).
        self._frame = (self._frame + 1) % PULSE_PERIOD
        half = PULSE_PERIOD / 2
        strength = abs(self._frame - half) / half      # 1 at the ends, 0 mid
        self._apply(MIN_OPACITY + (1.0 - MIN_OPACITY) * strength)
        if self._hold_ticks is not None:
            self._hold_ticks -= 1
            if self._hold_ticks <= 0:
                self._hold_ticks = None
                self._start_fade()

    # ------------------------------------------------------------ Closing
    def finish(self, window=None, extra_breaths: int = 0) -> None:
        """Reveal ``window`` and fade out. With ``extra_breaths`` the splash first
        pulses that many more full breaths (purely for the look; the app is
        ready), always the same length. A window shown at opacity 0 to stay
        hidden meanwhile is made opaque at the reveal."""
        if self._closing or self._hold_ticks is not None:
            return
        self._window = window
        if extra_breaths > 0:
            self._hold_ticks = extra_breaths * PULSE_PERIOD
            return
        self._start_fade()

    def _start_fade(self) -> None:
        window = self._window
        if window is not None:
            window.setWindowOpacity(1.0)
            window.raise_()
            window.activateWindow()
            self.raise_()  # keep the fade above the app
        self._closing = True
        self._closing_from = max(MIN_OPACITY, self._opacity)
        self._closing_ticks = 0
        self._fade_ticks = FADE_TICKS

    def close_now(self) -> None:
        """Close immediately, e.g. before an error dialog it could cover."""
        self._timer.stop()
        self.close()

    # ------------------------------------------------------------ Window
    def _center_on_cursor_screen(self) -> None:
        # The main window opens where the cursor is, so the splash does too.
        screen = QGuiApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2,
                  area.center().y() - self.height() // 2)

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform != "win32":
            return
        # Windows 11 adds a shadow and rounded corners to frameless windows; turn
        # both off. Needs the native window, so it can't happen in __init__.
        try:
            import ctypes
            handle = int(self.winId())
            dwm = ctypes.windll.dwmapi
            for attribute, value in ((2, 1),      # NCRENDERING_POLICY: no shadow
                                     (33, 1)):    # CORNER_PREFERENCE: do not round
                dwm.DwmSetWindowAttribute(
                    handle, attribute,
                    ctypes.byref(ctypes.c_int(value)), ctypes.sizeof(ctypes.c_int))
        except Exception:
            pass  # cosmetic only
