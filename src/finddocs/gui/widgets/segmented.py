"""Segmentowany wybor jednej opcji z kilku.

Trzy osobne przyciski obok siebie czyta sie jak trzy niezalezne akcje.
Zlaczone w jedna kontrolke czyta sie jak jeden wybor, a tak wlasnie dziala
tryb wyszukiwania. Zaokraglenia skrajnych segmentow i wspolne obramowanie
ustawia arkusz stylow po wlasciwosci ``segmentPos``.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from finddocs.gui.widgets.page import repolish

#: Zapas na obramowanie i wypelnienie segmentu, doliczany do szerokosci napisu.
SEGMENT_PADDING = 44


class SegmentedControl(QWidget):
    """Grupa wykluczajacych sie przyciskow o jednakowej szerokosci."""

    #: Numer segmentu wybranego przez uzytkownika (nie przy zmianie z kodu).
    changed = Signal(int)

    def __init__(
        self,
        labels: Sequence[str],
        *,
        hints: Sequence[str] | None = None,
        checked: int = 0,
    ) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        # Segmenty musza sie stykac, wspolne obramowanie rysuje arkusz stylow.
        row.setSpacing(0)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        width = self._segment_width(labels)
        last = len(labels) - 1
        for index, label in enumerate(labels):
            button = QPushButton(label)
            button.setObjectName("Segment")
            button.setProperty("segmentPos", _position(index, last))
            button.setCheckable(True)
            button.setChecked(index == checked)
            button.setMinimumWidth(width)
            if hints is not None and index < len(hints):
                button.setToolTip(hints[index])
            repolish(button)
            self.group.addButton(button, index)
            row.addWidget(button)
        self.group.idClicked.connect(self.changed.emit)

    def _segment_width(self, labels: Sequence[str]) -> int:
        """Wspolna szerokosc segmentow, liczona pismem pogrubionym.

        Wybrany segment jest pisany pogrubieniem, wiec jego napis jest szerszy
        niz w chwili, gdy Qt liczylo rozmiar przycisku. Bez tego zabiegu
        pierwsza litera dluzszego napisu znika po wybraniu segmentu.
        """
        bold = QFont(self.font())
        bold.setBold(True)
        metrics = QFontMetrics(bold)
        widest = max((metrics.horizontalAdvance(label) for label in labels), default=0)
        return widest + SEGMENT_PADDING

    def buttons(self) -> list[QPushButton]:
        return [button for button in self.group.buttons() if isinstance(button, QPushButton)]

    def checked_index(self) -> int:
        """Numer wybranego segmentu albo -1, gdy zaden nie jest wybrany."""
        return self.group.checkedId()

    def set_checked_index(self, index: int) -> None:
        button = self.group.button(index)
        if button is not None:
            button.setChecked(True)


def _position(index: int, last: int) -> str:
    """Nazwa polozenia segmentu uzywana przez arkusz stylow."""
    if last <= 0:
        return "only"
    if index == 0:
        return "first"
    if index == last:
        return "last"
    return "middle"


__all__ = ["SEGMENT_PADDING", "SegmentedControl"]
