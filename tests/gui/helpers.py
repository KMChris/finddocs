"""Pomocnicze funkcje testow interfejsu.

Funkcje odczytujace kolor z narysowanego obrazu sa uzywane w kilku modulach
testowych, wiec leza tutaj, a nie w jednym z nich.
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon


def glyph_color(icon: QIcon, size: int = 16) -> QColor:
    """Kolor najbardziej krycego piksela glifu.

    Glif jest wygladzony, wiec brzegi sa polprzezroczyste. Piksel o najwyzszej
    kryciu ma kolor, ktory zostal glifowi nadany przy generowaniu.
    """
    image = icon.pixmap(QSize(size, size)).toImage()
    best = QColor(0, 0, 0, 0)
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() > best.alpha():
                best = color
    return best


def color_distance(first: QColor, second: QColor) -> int:
    """Odleglosc kolorow w sumie roznic skladowych. Zero oznacza ten sam kolor."""
    return (
        abs(first.red() - second.red())
        + abs(first.green() - second.green())
        + abs(first.blue() - second.blue())
    )


__all__ = ["color_distance", "glyph_color"]
