"""Siatka liczb: podpis nad wartoscia, kilka kolumn w wierszu.

Ekran indeksowania i raport pokrycia pokazuja to samo: zestaw nazwanych liczb.
Oba liczyly numery wierszy tak samo (``wiersz * 3`` plus pusty wiersz na
odstep), oba ustawialy te same nazwy stylow. Tutaj ta arytmetyka jest raz.

Struktura siatki jest stala, zmieniaja sie tylko wartosci. Dzieki temu
odswiezenie nie tworzy kontrolek od nowa.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from finddocs.gui.theme import SPACE_MD, SPACE_XL
from finddocs.gui.widgets.page import repolish

#: Odstep pionowy miedzy podpisem i jego wartoscia. Ma byc maly, zeby para
#: czytala sie jako jedna calosc.
CAPTION_GAP = 2

#: Wysokosc pustego wiersza rozdzielajacego kolejne rzedy par.
ROW_GAP = SPACE_MD


class StatGrid(QWidget):
    """Pary podpis/wartosc uporzadkowane w kolumnach."""

    def __init__(self, entries: Sequence[tuple[str, str]], *, columns: int = 4) -> None:
        """``entries`` to pary (klucz, podpis). Klucz sluzy do zmiany wartosci."""
        super().__init__()
        self.labels: dict[str, QLabel] = {}
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(SPACE_XL)
        grid.setVerticalSpacing(CAPTION_GAP)
        for column in range(columns):
            grid.setColumnStretch(column, 1)

        for position, (key, caption_text) in enumerate(entries):
            row = position // columns
            column = position % columns
            caption = QLabel(caption_text)
            caption.setObjectName("StatCaption")
            value = QLabel("")
            value.setObjectName("StatValue")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(caption, row * 3, column)
            grid.addWidget(value, row * 3 + 1, column)
            self.labels[key] = value

        rows = -(-len(entries) // columns)
        for row in range(rows - 1):
            grid.setRowMinimumHeight(row * 3 + 2, ROW_GAP)

    def set_values(self, values: Mapping[str, object]) -> None:
        """Ustawia wartosci dla podanych kluczy. Nieznane klucze pomija."""
        for key, value in values.items():
            label = self.labels.get(key)
            if label is not None:
                label.setText(str(value))

    def value(self, key: str) -> str:
        label = self.labels.get(key)
        return label.text() if label is not None else ""

    def set_value_role(self, key: str, role: str) -> None:
        """Nadaje wartosci role koloru (np. ``danger``). Pusta rola ja zdejmuje."""
        label = self.labels.get(key)
        if label is None or label.property("valueRole") == role:
            return
        label.setProperty("valueRole", role)
        repolish(label)


__all__ = ["CAPTION_GAP", "ROW_GAP", "StatGrid"]
