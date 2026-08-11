"""Zarysy kart wynikow pokazywane w czasie wyszukiwania.

Pusta lista z samym napisem ,,Wyszukiwanie w toku'' nie zapowiada, co sie
pojawi. Dwa lub trzy szare zarysy kart robia to lepiej i sa statyczne:
zadnego migotania, wiec dzialaja tak samo przy systemowym ograniczeniu
animacji i w testach na platformie offscreen.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout

from finddocs.gui.theme import SPACE_LG, SPACE_SM

#: Wysokosci paskow zarysu: tytul i dwie linie tresci.
_BAR_HEIGHTS = (16, 12, 12)

#: Udzial szerokosci paska w wierszu: (wypelnienie, wolne miejsce).
_BAR_SPANS = ((2, 3), (9, 1), (7, 3))


class SkeletonCard(QFrame):
    """Statyczny zarys karty wyniku: ramka karty i trzy szare paski."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("SkeletonCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_LG, SPACE_LG, SPACE_LG, SPACE_LG)
        layout.setSpacing(SPACE_SM + 2)
        for height, (fill, rest) in zip(_BAR_HEIGHTS, _BAR_SPANS, strict=True):
            bar = QFrame()
            bar.setObjectName("SkeletonBar")
            bar.setFixedHeight(height)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(bar, stretch=fill)
            row.addStretch(rest)
            layout.addLayout(row)


__all__ = ["SkeletonCard"]
