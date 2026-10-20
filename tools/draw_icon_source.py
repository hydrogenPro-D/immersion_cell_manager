"""Draw the master icon artwork into assets/.

app_icon_source.png: a glossy amber-orange disc with a white inner ring and
near-black "ICM", in the style of the Production Data Manager icon.
app_icon_small_source.png: the same disc without glow or ring and with bigger
letters, for the 16-32 px icon sizes where the full design turns to mush.

Run this only to change the design; tools/generate_icon.py turns the masters
into the shipped .png and .ico.

    python tools/draw_icon_source.py
"""

import sys
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen,
    QRadialGradient, QLinearGradient,
)

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

SIZE = 1024
C = SIZE / 2
R_OUTER = 440          # rim
R_FACE = 372           # yellow face inside the rim
R_RING = 352           # white ring, just inside the face edge
TEXT = "ICM"
TEXT_COLOR = QColor("#FFFFFF")
OUTLINE_COLOR = QColor(26, 26, 26, 200)   # light black border keeps white legible on orange


def _circle(r: float) -> QRectF:
    return QRectF(C - r, C - r, 2 * r, 2 * r)


def draw(small: bool = False) -> QImage:
    img = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setPen(Qt.PenStyle.NoPen)

    # Soft outer glow (left out when small: it would only shrink the disc).
    if not small:
        glow = QRadialGradient(QPointF(C, C), R_OUTER + 60)
        glow.setColorAt(0.80, QColor(240, 130, 0, 120))
        glow.setColorAt(1.00, QColor(240, 130, 0, 0))
        p.setBrush(QBrush(glow))
        p.drawEllipse(_circle(R_OUTER + 60))

    # Rim: lighter on top, deeper amber at the bottom for depth.
    rim = QLinearGradient(0, C - R_OUTER, 0, C + R_OUTER)
    rim.setColorAt(0.0, QColor("#FFB347"))
    rim.setColorAt(0.55, QColor("#E57C00"))
    rim.setColorAt(1.0, QColor("#A85300"))
    p.setBrush(QBrush(rim))
    p.drawEllipse(_circle(R_OUTER))

    # Face: amber-orange, lit from the top left.
    face = QRadialGradient(QPointF(C - 120, C - 140), R_FACE * 1.35)
    face.setColorAt(0.0, QColor("#FFB443"))
    face.setColorAt(0.55, QColor("#F28A00"))
    face.setColorAt(1.0, QColor("#D96C00"))
    p.setBrush(QBrush(face))
    p.drawEllipse(_circle(R_FACE))

    # White ring with a soft glow underneath it.
    if not small:
        p.setBrush(Qt.BrushStyle.NoBrush)
        for width, alpha in ((34, 40), (24, 70), (16, 120)):
            p.setPen(QPen(QColor(255, 255, 255, alpha), width))
            p.drawEllipse(_circle(R_RING))
        p.setPen(QPen(QColor(255, 255, 255), 11))
        p.drawEllipse(_circle(R_RING))
        p.setPen(Qt.PenStyle.NoPen)

    # Gloss: a faint highlight over the upper-left of the face.
    clip = QPainterPath()
    clip.addEllipse(_circle(R_RING - 8))
    p.save()
    p.setClipPath(clip)
    gloss = QLinearGradient(C - 260, C - 300, C + 60, C + 40)
    gloss.setColorAt(0.0, QColor(255, 255, 255, 95))
    gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(QBrush(gloss))
    p.drawEllipse(QRectF(C - 420, C - 470, 700, 560))
    p.restore()

    # Lettering, sized to a fixed share of the ring's width.
    font = QFont("Segoe UI", 10, QFont.Weight.Black)
    font.setPixelSize(100)
    p.setFont(font)
    target = 2 * R_RING * (0.88 if small else 0.72)
    scale = target / p.fontMetrics().horizontalAdvance(TEXT)
    font.setPixelSize(int(100 * scale))
    p.setFont(font)
    fm = p.fontMetrics()
    w = fm.horizontalAdvance(TEXT)
    baseline = C + fm.capHeight() / 2
    path = QPainterPath()
    path.addText(QPointF(C - w / 2, baseline), font, TEXT)
    if not small:
        p.setBrush(QColor(0, 0, 0, 45))           # soft drop shadow
        p.drawPath(path.translated(0, 8))
    # Outline first, then the white fill over it, so only the outer half shows.
    # Heavier when small: those masters are shrunk to 16-32 px.
    outline = QPen(OUTLINE_COLOR, 36 if small else 18)
    outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.strokePath(path, outline)
    p.setBrush(TEXT_COLOR)
    p.drawPath(path)

    p.end()
    return img


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    ASSETS.mkdir(parents=True, exist_ok=True)
    for name, small in (("app_icon_source.png", False), ("app_icon_small_source.png", True)):
        out = ASSETS / name
        if not draw(small).save(str(out)):
            sys.exit(f"Could not write {out}")
        print(f"Wrote {out}")
