"""Generuje male ikony motywu: znacznik wyboru i strzalke listy rozwijanej.

Arkusz stylow Qt nie potrafi narysowac znacznika wyboru ani strzalki, wiec
aplikacja dostarcza je jako male obrazki PNG. Pliki trafiaja do
``src/finddocs/resources/theme``. Warianty ``@2x`` sa dla ekranow o podwojnej
gestosci pikseli, Qt wybiera je automatycznie.

Kolory odpowiadaja paletom z ``finddocs.gui.theme``: znacznik wyboru lezy na
tle akcentu, strzalka na tle pola. Skrypt uruchamia sie tylko przy zmianie
motywu:

    .venv/Scripts/python.exe tools/make_theme_icons.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "src" / "finddocs" / "resources" / "theme"

#: Lamana znacznika wyboru w ukladzie logicznym 12 na 12 pikseli.
CHECK_POINTS = ((2.6, 6.4), (4.9, 8.7), (9.4, 3.4))
CHECK_SIZE = 12

#: Lamana strzalki w dol w ukladzie logicznym 16 na 16 pikseli.
CHEVRON_POINTS = ((4.2, 6.4), (8.0, 10.2), (11.8, 6.4))
CHEVRON_SIZE = 16

#: Nazwa pliku, punkty, rozmiar logiczny, grubosc linii i kolor linii.
#: Wariant jasny to kolor dla jasnej palety, ciemny dla ciemnej.
ICONS: tuple[tuple[str, tuple[tuple[float, float], ...], int, float, str], ...] = (
    ("check-light", CHECK_POINTS, CHECK_SIZE, 1.7, "#ffffff"),
    ("check-dark", CHECK_POINTS, CHECK_SIZE, 1.7, "#0b1e28"),
    ("chevron-light", CHEVRON_POINTS, CHEVRON_SIZE, 1.6, "#5d5d5d"),
    ("chevron-dark", CHEVRON_POINTS, CHEVRON_SIZE, 1.6, "#b0b0b0"),
)


def draw_icon(
    points: tuple[tuple[float, float], ...],
    size: int,
    scale: int,
    line_width: float,
    color: str,
) -> QImage:
    """Rysuje lamana na przezroczystym tle w podanej skali."""
    image = QImage(size * scale, size * scale, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(line_width * scale)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawPolyline([QPointF(x * scale, y * scale) for x, y in points])
    painter.end()
    return image


def main() -> int:
    app = QGuiApplication(sys.argv[:1])
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, points, size, line_width, color in ICONS:
        for suffix, scale in (("", 1), ("@2x", 2)):
            image = draw_icon(points, size, scale, line_width, color)
            target = OUTPUT_DIR / f"{name}{suffix}.png"
            if not image.save(str(target)):
                print(f"BLAD: nie udalo sie zapisac {target}", file=sys.stderr)
                return 1
            written.append(target.name)
    del app
    print(f"Zapisano {len(written)} plikow w {OUTPUT_DIR}:")
    for name in written:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
