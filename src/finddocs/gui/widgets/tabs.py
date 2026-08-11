"""Pasek zakladek z miejscem na kontrolke po prawej stronie.

``QTabWidget.setCornerWidget`` przycina kontrolke w rogu z prawej strony,
takze poza trybem dokumentowym: geometria rogu w stylu arkuszowym nie zgadza
sie z szerokoscia kontrolki. Osobny :class:`QTabBar` w zwyklym wierszu ukladu
nad :class:`QStackedWidget` nie ma tego problemu, a wyglada tak samo, bo
arkusz stylow motywu styluje kazdy ``QTabBar``.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QTabBar, QVBoxLayout, QWidget

from finddocs.gui.theme import SPACE_MD


class TabPanel(QWidget):
    """Zakladki pivot ze stosem stron i opcjonalna kontrolka po prawej."""

    currentChanged = Signal(int)

    def __init__(self, side_widget: QWidget | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_MD)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE_MD)
        self.bar = QTabBar()
        # Bez rozciagania zakladki maja szerokosc napisu, jak pivot Windows 11.
        # Linia bazowa paska bywa zrodlem szczatkowych ramek, wiec jest wylaczona.
        self.bar.setExpanding(False)
        self.bar.setDrawBase(False)
        row.addWidget(self.bar)
        row.addStretch(1)
        if side_widget is not None:
            row.addWidget(side_widget)
        layout.addLayout(row)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, stretch=1)
        self.bar.currentChanged.connect(self._on_current_changed)

    # --- API zgodne w uzyciu z QTabWidget ---------------------------------

    def addTab(self, widget: QWidget, label: str) -> int:
        self.stack.addWidget(widget)
        return self.bar.addTab(label)

    def tabText(self, index: int) -> str:
        return self.bar.tabText(index)

    def setTabText(self, index: int, text: str) -> None:
        self.bar.setTabText(index, text)

    def currentIndex(self) -> int:
        return self.bar.currentIndex()

    def setCurrentIndex(self, index: int) -> None:
        self.bar.setCurrentIndex(index)

    def currentWidget(self) -> QWidget | None:
        return self.stack.currentWidget()

    def setCurrentWidget(self, widget: QWidget) -> None:
        self.bar.setCurrentIndex(self.stack.indexOf(widget))

    def count(self) -> int:
        return self.stack.count()

    def widget(self, index: int) -> QWidget | None:
        return self.stack.widget(index)

    # --- wewnetrzne -------------------------------------------------------

    def _on_current_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        # Wybrana zakladka jest pogrubiona, wiec pasek robi sie o pare pikseli
        # szerszy. Bez przeliczenia geometrii uklad zostawia stara szerokosc,
        # a pasek wlacza strzalki przewijania mimo wolnego miejsca obok.
        self.bar.updateGeometry()
        self.currentChanged.emit(index)


__all__ = ["TabPanel"]
