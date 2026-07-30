"""Custom ΔV%-vs-resistance plot with the acceptance band drawn as borders.

The six measured ΔV% points are connected (interpolated) and coloured green when
inside their band / red when outside. The band is the shaded region between the
per-resistance min and max limits, so a human can see at a glance how close each
reading sits to the edges.
"""

import math

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPolygonF, QPainterPath,
)


def _pt_seg_dist(p, a, b) -> float:
    """Distance from point ``p`` to segment ``a``-``b`` (all QPointF)."""
    ax, ay, bx, by = a.x(), a.y(), b.x(), b.y()
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(p.x() - ax, p.y() - ay)
    t = ((p.x() - ax) * dx + (p.y() - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(p.x() - (ax + t * dx), p.y() - (ay + t * dy))


def _dist_to_polyline(p, poly) -> float:
    """Smallest distance from ``p`` to any segment of the polyline ``poly``."""
    best = float("inf")
    for a, b in zip(poly, poly[1:]):
        best = min(best, _pt_seg_dist(p, a, b))
    return best


def smooth_path(points: list) -> QPainterPath:
    """A Catmull-Rom smooth path through ``points`` (list of QPointF).

    Gives the "interpolated" look (soft curve through the points) instead of
    straight segments. Handles non-uniform x spacing (e.g. the 2→3.3 gap).
    """
    path = QPainterPath()
    if not points:
        return path
    path.moveTo(points[0])
    n = len(points)
    for i in range(n - 1):
        p0 = points[i - 1] if i > 0 else points[0]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[i + 2] if i + 2 < n else points[n - 1]
        c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6.0,
                     p1.y() + (p2.y() - p0.y()) / 6.0)
        c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6.0,
                     p2.y() - (p3.y() - p1.y()) / 6.0)
        path.cubicTo(c1, c2, p2)
    return path


class CalibrationPlot(QWidget):
    """Paints ΔV% (y) against the six reference resistances (x)."""

    BAND_FILL = QColor(0, 158, 115, 40)     # translucent bluish-green
    BAND_LINE = QColor(0, 158, 115, 170)
    OK_POINT = QColor(0, 140, 90)
    BAD_POINT = QColor(213, 94, 0)          # vermillion
    LINE_COLOR = QColor(31, 78, 140)        # measured line
    AXIS = QColor(120, 135, 145)
    GRID = QColor(228, 234, 238)
    TEXT = QColor(74, 90, 102)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._resistances = []
        self._bounds = []
        self._deltas = []
        self.setMinimumHeight(240)

    def set_data(self, resistances, bounds, deltas) -> None:
        self._resistances = list(resistances or [])
        self._bounds = list(bounds or [])
        self._deltas = list(deltas or [])
        self.update()

    def _y_range(self):
        vals = []
        for lo, hi in self._bounds:
            if lo is not None:
                vals.append(lo)
            if hi is not None:
                vals.append(hi)
        vals += [d for d in self._deltas if d is not None]
        if not vals:
            return -1.5, 0.6
        lo, hi = min(vals), max(vals)
        if lo == hi:
            lo, hi = lo - 0.5, hi + 0.5
        pad = (hi - lo) * 0.18 or 0.2
        return lo - pad, hi + pad

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#FFFFFF"))

        n = len(self._resistances)
        if n == 0:
            return

        left, right, top, bottom = 56, 18, 14, 36
        plot = QRectF(left, top, w - left - right, h - top - bottom)
        ylo, yhi = self._y_range()

        def xpos(i):
            return plot.center().x() if n == 1 else plot.left() + i * plot.width() / (n - 1)

        def ypos(v):
            return plot.bottom() - (v - ylo) / (yhi - ylo) * plot.height()

        # y grid + labels
        p.setFont(QFont("Segoe UI", 8))
        steps = 6
        for k in range(steps + 1):
            v = ylo + (yhi - ylo) * k / steps
            y = ypos(v)
            p.setPen(QPen(self.GRID, 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QPen(self.TEXT, 1))
            p.drawText(QRectF(0, y - 8, left - 8, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{v:.2f}")

        # acceptance band (only if every resistance has both bounds)
        have_band = bool(self._bounds) and all(
            b[0] is not None and b[1] is not None for b in self._bounds
        )
        if have_band:
            poly = QPolygonF()
            for i, (lo, hi) in enumerate(self._bounds):
                poly.append(QPointF(xpos(i), ypos(hi)))
            for i in range(n - 1, -1, -1):
                poly.append(QPointF(xpos(i), ypos(self._bounds[i][0])))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(self.BAND_FILL))
            p.drawPolygon(poly)

            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(self.BAND_LINE, 1.4))
            for idx in (0, 1):  # min line, then max line
                border = QPolygonF()
                for i, b in enumerate(self._bounds):
                    border.append(QPointF(xpos(i), ypos(b[idx])))
                p.drawPolyline(border)

        # measured line (interpolated across present points)
        p.setPen(QPen(self.LINE_COLOR, 2))
        prev = None
        for i, d in enumerate(self._deltas):
            if d is None:
                prev = None
                continue
            pt = QPointF(xpos(i), ypos(d))
            if prev is not None:
                p.drawLine(prev, pt)
            prev = pt

        # points, coloured by inside/outside their band
        for i, d in enumerate(self._deltas):
            if d is None:
                continue
            lo, hi = self._bounds[i] if i < len(self._bounds) else (None, None)
            inside = (lo is None or d >= lo) and (hi is None or d <= hi)
            p.setBrush(QBrush(self.OK_POINT if inside else self.BAD_POINT))
            p.setPen(QPen(QColor("#FFFFFF"), 1.4))
            p.drawEllipse(QPointF(xpos(i), ypos(d)), 4.6, 4.6)

        # x labels (resistances)
        p.setPen(QPen(self.TEXT, 1))
        for i, r in enumerate(self._resistances):
            p.drawText(QRectF(xpos(i) - 26, plot.bottom() + 5, 52, 18),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       f"{r:g} Ω")


class CalibrationCurvesPlot(QWidget):
    """Overlays every channel's latest ΔV% curve on a real resistance axis.

    Mirrors the spreadsheet's "IC channel calibration curves" chart: one smooth,
    interpolated curve per channel, x = resistance [ohm] (linear, so the 2→3.3
    gap shows), y = difference from theoretical potential [%].
    """

    AXIS = QColor(120, 135, 145)
    GRID = QColor(230, 236, 240)
    TEXT = QColor(74, 90, 102)
    _PALETTE = [
        "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD",
        "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF",
        "#3FA3A3", "#E0734D",
    ]

    # Fraction of the acceptance-band height added as padding above/below the
    # band when fixing the y-axis (so lines just outside the band still show).
    Y_BAND_PADDING = 0.5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._resistances = []
        self._series = []  # list of {"channel", "status", "deltas"}
        self._bounds = []  # per-resistance (lo, hi) acceptance limits
        self._hover_idx = None
        self._hover_pos = None
        self._hit_polylines = []  # [(index, [QPointF, ...])] from the last paint
        self.setMinimumSize(360, 300)
        self.setMouseTracking(True)

    def set_data(self, resistances, series, bounds=None) -> None:
        """``series``: list of ``{"channel", "status", "deltas"}`` dicts.

        ``bounds``: per-resistance ``(lo, hi)`` acceptance limits; when given, the
        y-axis is fixed around them (+padding) instead of auto-scaling to data.
        """
        self._resistances = [float(r) for r in resistances]
        self._series = list(series or [])
        self._bounds = list(bounds or [])
        self._hover_idx = None
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#FFFFFF"))

        res = self._resistances
        if len(res) < 2:
            return
        rmin, rmax = min(res), max(res)

        # Fix the y-axis around the acceptance bounds (+padding) so a few extreme
        # test values can't blow up the scale and hide the real curves. Fall back
        # to the data range only when no bounds are configured.
        los = [b[0] for b in self._bounds if b and b[0] is not None]
        his = [b[1] for b in self._bounds if b and b[1] is not None]
        if los and his:
            blo, bhi = min(los), max(his)
            pad = (bhi - blo) * self.Y_BAND_PADDING or 0.2
            ylo, yhi = blo - pad, bhi + pad
        else:
            vals = [d for s in self._series for d in s["deltas"] if d is not None]
            if vals:
                ylo, yhi = min(vals), max(vals)
            else:
                ylo, yhi = -1.3, 0.4
            if ylo == yhi:
                ylo, yhi = ylo - 0.5, yhi + 0.5
            pad = (yhi - ylo) * 0.10 or 0.2
            ylo, yhi = ylo - pad, yhi + pad

        left, right, top, bottom = 64, 18, 38, 50
        plot = QRectF(left, top, w - left - right, h - top - bottom)

        def xpos(r):
            return plot.left() + (r - rmin) / (rmax - rmin) * plot.width()

        def ypos(v):
            return plot.bottom() - (v - ylo) / (yhi - ylo) * plot.height()

        # Title.
        p.setPen(QPen(self.TEXT))
        p.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, 8, w, 22), Qt.AlignmentFlag.AlignHCenter,
                   "IC channel calibration curves")

        # y grid + labels.
        p.setFont(QFont("Segoe UI", 8))
        steps = 6
        for k in range(steps + 1):
            v = ylo + (yhi - ylo) * k / steps
            y = ypos(v)
            p.setPen(QPen(self.GRID, 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QPen(self.TEXT, 1))
            p.drawText(QRectF(0, y - 8, left - 8, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{v:.2f}")

        # x grid + labels (one gridline per resistance, at its real position).
        for r in res:
            x = xpos(r)
            p.setPen(QPen(self.GRID, 1))
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            p.setPen(QPen(self.TEXT, 1))
            p.drawText(QRectF(x - 24, plot.bottom() + 4, 48, 16),
                       Qt.AlignmentFlag.AlignHCenter, f"{r:g}")

        # Axis titles.
        p.setPen(QPen(self.TEXT))
        p.drawText(QRectF(plot.left(), h - 20, plot.width(), 16),
                   Qt.AlignmentFlag.AlignHCenter, "Resistance [ohm]")
        p.save()
        p.translate(16, plot.center().y())
        p.rotate(-90)
        p.drawText(QRectF(-plot.height() / 2, -14, plot.height(), 16),
                   Qt.AlignmentFlag.AlignHCenter,
                   "Difference from theoretical potential [%]")
        p.restore()

        # One smooth curve per channel. Also sample each into a polyline for
        # hover hit-testing (recomputed here so it tracks resize / data changes).
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setClipRect(plot)
        self._hit_polylines = []
        paths = []
        for i, rec in enumerate(self._series):
            pts = [QPointF(xpos(r), ypos(d))
                   for r, d in zip(res, rec["deltas"]) if d is not None]
            if len(pts) < 2:
                continue
            path = smooth_path(pts)
            paths.append((i, path))
            self._hit_polylines.append((i, self._sample_path(path)))

        hover = self._hover_idx
        # Non-hovered curves first (dimmed when a line is hovered).
        for i, path in paths:
            if i == hover:
                continue
            color = QColor(self._PALETTE[i % len(self._PALETTE)])
            if hover is None:
                color.setAlpha(200)
                width = 1.6
            else:
                color.setAlpha(55)
                width = 1.2
            p.setPen(QPen(color, width))
            p.drawPath(path)
        # Hovered curve drawn last (on top), opaque and thicker.
        for i, path in paths:
            if i == hover:
                color = QColor(self._PALETTE[i % len(self._PALETTE)])
                p.setPen(QPen(color, 2.6))
                p.drawPath(path)
        p.setClipping(False)

        # Hover label: "channel · status" near the cursor.
        if hover is not None and 0 <= hover < len(self._series) and self._hover_pos:
            rec = self._series[hover]
            self._draw_hover_label(p, f"Channel {rec['channel']} · {rec['status']}")

    # -------------------------------------------------------------- Hover
    @staticmethod
    def _sample_path(path, n: int = 48) -> list:
        """Sample a QPainterPath into ``n+1`` evenly-spaced screen points."""
        return [path.pointAtPercent(k / n) for k in range(n + 1)]

    def _curve_at(self, pos):
        """Index of the nearest curve within the hit threshold, else None."""
        best_i, best_d = None, 6.0  # px threshold
        for i, poly in self._hit_polylines:
            d = _dist_to_polyline(pos, poly)
            if d < best_d:
                best_d, best_i = d, i
        return best_i

    def _draw_hover_label(self, p, text: str) -> None:
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        fm = p.fontMetrics()
        pad = 7
        w = fm.horizontalAdvance(text) + 2 * pad
        h = fm.height() + 2 * pad
        x = min(max(4.0, self._hover_pos.x() + 14), self.width() - w - 4)
        y = min(max(4.0, self._hover_pos.y() - h - 8), self.height() - h - 4)
        rect = QRectF(x, y, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(31, 42, 51, 236))
        p.drawRoundedRect(rect, 5, 5)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def mouseMoveEvent(self, event):
        pos = event.position()
        idx = self._curve_at(pos)
        changed = idx != self._hover_idx
        self._hover_idx = idx
        self._hover_pos = pos
        if changed or idx is not None:
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover_idx is not None:
            self._hover_idx = None
            self.update()
        super().leaveEvent(event)
