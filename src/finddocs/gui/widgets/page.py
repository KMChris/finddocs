"""Elementy wspolne dla wszystkich ekranow: naglowek, baner, kropka stanu.

Kazdy ekran ma taki sam poczatek: marginesy, tytul, ewentualna informacja
o stanie. Wczesniej kazdy widok budowal to sam, wiec odstepy rozjezdzaly sie
przy kazdej zmianie. Tutaj sa raz i biora wartosci ze skali odstepow motywu.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from finddocs.gui.theme import PAGE_MARGINS, SPACE_MD, SPACE_SM
from finddocs.gui.widgets.motion import fade_in

#: Dozwolone role banera. Kolory sa w ``theme.BANNER_COLORS``.
BANNER_ROLES = ("success", "warning", "info")

#: Dozwolone role kropki stanu. Kolory sa w ``theme.DOT_COLORS``.
DOT_ROLES = ("ok", "warn", "off")


def page_layout(page: QWidget) -> QVBoxLayout:
    """Pionowy uklad ekranu z marginesami i odstepem z motywu."""
    layout = QVBoxLayout(page)
    layout.setContentsMargins(*PAGE_MARGINS)
    layout.setSpacing(SPACE_MD)
    return layout


def repolish(widget: QWidget) -> None:
    """Kaze Qt policzyc styl ponownie po zmianie wlasciwosci dynamicznej.

    Selektory w rodzaju ``[bannerRole="warning"]`` sa dopasowywane w chwili
    obliczania stylu. Bez tego wywolania zmiana wlasciwosci nie zmienia wygladu.
    """
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)


class PageHeader(QWidget):
    """Tytul ekranu oraz krotka informacja przy prawej krawedzi.

    Prawa strona wiersza tytulu jest zwykle pusta, a jednoczesnie kazdy ekran
    ma cos, co warto tam pokazac: liczbe wynikow, czas ostatniego odswiezenia.
    Dzieki temu podsumowanie nie zabiera osobnego wiersza nad trescia.
    """

    def __init__(self, title: str, *, meta: str = "") -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE_MD)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("PageTitle")
        row.addWidget(self.title_label)
        row.addStretch(1)

        self.meta_label = QLabel(meta)
        self.meta_label.setObjectName("PageMeta")
        self.meta_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.meta_label.setVisible(bool(meta))
        row.addWidget(self.meta_label)

    def set_meta(self, text: str) -> None:
        """Ustawia informacje po prawej. Puste napis ukrywa etykiete."""
        self.meta_label.setText(text)
        self.meta_label.setVisible(bool(text))


class Banner(QFrame):
    """Pasek z jednym zdaniem o stanie ekranu.

    Uwagi o niekompletnosci wynikow musza byc widoczne. Wyciszony, szary tekst
    pod paskiem trybow czytelnik pomija, kolorowy pasek nad lista wynikow nie.
    Baner bez tresci jest ukryty i nie zajmuje miejsca w ukladzie.
    """

    def __init__(self, *, role: str = "info") -> None:
        super().__init__()
        self.setObjectName("Banner")
        self.setFrameShape(QFrame.Shape.NoFrame)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACE_MD, SPACE_SM, SPACE_MD, SPACE_SM)
        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._label)
        self._set_role(role)
        self.setVisible(False)

    def _set_role(self, role: str) -> None:
        self.setProperty("bannerRole", role if role in BANNER_ROLES else "info")
        repolish(self)
        repolish(self._label)

    def show_message(self, text: str, role: str = "info") -> None:
        """Pokazuje tresc w podanej roli. Pusty napis ukrywa baner."""
        if not text:
            self.hide_message()
            return
        self._set_role(role)
        self._label.setText(text)
        was_hidden = self.isHidden()
        self.setVisible(True)
        if was_hidden:
            fade_in(self)

    def hide_message(self) -> None:
        self._label.setText("")
        self.setVisible(False)

    def text(self) -> str:
        return self._label.text()


class StatusDot(QLabel):
    """Kolorowa kropka: stan skladnika czytany bez czytania tekstu."""

    def __init__(self, role: str = "off") -> None:
        super().__init__()
        self.setObjectName("StatusDot")
        self.set_role(role)

    def set_role(self, role: str) -> None:
        self.setProperty("dotRole", role if role in DOT_ROLES else "off")
        repolish(self)


__all__ = [
    "BANNER_ROLES",
    "DOT_ROLES",
    "Banner",
    "PageHeader",
    "StatusDot",
    "page_layout",
    "repolish",
]
