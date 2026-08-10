"""Wskaznik zaznaczenia w panelu nawigacji.

Zaznaczona pozycja panelu ma zaokraglone tlo, a przy jej lewej krawedzi lezy
pigulka w kolorze akcentu. Wczesniej zaznaczenie rysowala lewa krawedz
obramowania, ale arkusz stylow zaokragla rogi pozycji, wiec ta krawedz byla
przycinana lukiem i wygladala jak zakrzywiony pasek, a nie jak wskaznik.

Arkusz stylow nie umie narysowac prostokata wewnatrz pozycji listy, dlatego
pigulke rysuje delegat. Pozostaly wyglad pozycji (tlo, zaokraglenie, odstepy,
ikona, napis) nadal pochodzi z arkusza stylow.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QListWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from finddocs.gui.theme import Palette

#: Szerokosc pigulki w pikselach.
PILL_WIDTH = 3

#: Wysokosc pigulki. Krotsza niz pozycja, zeby czytala sie jako wskaznik,
#: a nie jako obramowanie.
PILL_HEIGHT = 16

#: Odstep pigulki od lewej krawedzi pozycji. Musi byc wiekszy niz margines
#: pozycji z arkusza stylow, inaczej pigulka wypadnie poza jej tlo.
PILL_INSET = 11


class NavDelegate(QStyledItemDelegate):
    """Delegat pozycji nawigacji: dorysowuje pigulke zaznaczenia."""

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._accent = QColor(palette.accent)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        if not option.state & QStyle.StateFlag.State_Selected:
            return
        rect = option.rect
        height = min(PILL_HEIGHT, rect.height())
        if height <= 0:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._accent)
        radius = PILL_WIDTH / 2
        painter.drawRoundedRect(
            QRectF(
                rect.left() + PILL_INSET,
                rect.top() + (rect.height() - height) / 2,
                PILL_WIDTH,
                height,
            ),
            radius,
            radius,
        )
        painter.restore()


def install_nav_delegate(nav: QListWidget, palette: Palette) -> NavDelegate:
    """Podlacza delegata do listy nawigacji i zwraca go.

    Delegat musi zyc tak dlugo, jak lista, dlatego jego rodzicem jest lista.
    """
    delegate = NavDelegate(palette, nav)
    nav.setItemDelegate(delegate)
    return delegate


__all__ = ["PILL_HEIGHT", "PILL_INSET", "PILL_WIDTH", "NavDelegate", "install_nav_delegate"]
