"""Wspolne ustawienia tabel interfejsu.

Domyslne zachowanie Qt daje kazdej kolumnie te sama szerokosc, a nadmiar oddaje
ostatniej. W praktyce konczy sie to tak, ze kolumna z data zajmuje polowe tabeli,
a nazwa pliku i komunikat bledu sa przyciete do kilkunastu znakow. Modul ustawia
to raz i tak samo we wszystkich widokach.

Kazda tabela obsluguje sortowanie po kliknieciu naglowka kolumny oraz reczna
zmiane szerokosci kolumn. Poki uzytkownik nie zmieni szerokosci samodzielnie,
uklad dopasowuje sie automatycznie: kolumny opisowe (``stretch``) dziela wolne
miejsce, pozostale dostaja tyle, ile potrzebuje ich tresc. Pierwsze reczne
przesuniecie krawedzi wylacza automat, zeby nie nadpisywac wyboru uzytkownika.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterator
from contextlib import contextmanager

from PySide6.QtCore import QCollator, QEvent, QLocale, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)

#: Minimalna szerokosc kolumny opisowej, zeby naglowek zawsze byl czytelny.
MIN_STRETCH_WIDTH = 140

#: Najmniejsza szerokosc, do jakiej uzytkownik moze recznie zwezic kolumne.
MIN_SECTION_WIDTH = 56

#: Gorny limit szerokosci wyliczonej z tresci. Bez niego jedna dluga sciezka
#: rozpycha kolumne na pol ekranu; pelna tresc jest zawsze w podpowiedzi.
MAX_CONTENT_WIDTH = 420

#: Zapas na marginesy komorki i strzalke sortowania w naglowku.
CONTENT_PADDING = 18

#: Wysokosc wiersza tabeli. Odrobina luzu nad i pod tekstem ulatwia czytanie.
ROW_HEIGHT = 34

#: Wlasciwosci dynamiczne tabeli sterujace automatycznym ukladem kolumn.
_STRETCH_PROP = "fdStretchColumns"
_MANUAL_PROP = "fdManualColumns"
_AUTOSIZING_PROP = "fdAutosizing"

#: Porzadek sortowania swiadomy polskich znakow i liczb w tekscie
#: (``plik-9`` przed ``plik-10``). Uzywany przez wszystkie komorki tabel.
_COLLATOR = QCollator(QLocale("pl_PL"))
_COLLATOR.setNumericMode(True)
_COLLATOR.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)


class SortableItem(QTableWidgetItem):
    """Komorka tabeli porownywana porzadkiem naturalnym, nie kodami znakow."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        return _COLLATOR.compare(self.text(), other.text()) < 0


class _AutoFitFilter(QObject):
    """Dopasowuje kolumny do nowej szerokosci okna, poki dziala automat."""

    def __init__(self, table: QTableWidget) -> None:
        super().__init__(table)
        self._table = table

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize:
            autosize_columns(self._table)
        return False


def configure_columns(table: QTableWidget, stretch: tuple[int, ...]) -> None:
    """Kolumny z ``stretch`` dziela wolne miejsce, pozostale dostaja tyle, ile trzeba.

    Wszystkie kolumny sa w trybie interaktywnym, wiec uzytkownik moze zmienic
    ich szerokosc przeciagnieciem krawedzi naglowka. Klikniecie naglowka
    sortuje tabele; ponowne klikniecie odwraca porzadek.
    """
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setMinimumSectionSize(MIN_SECTION_WIDTH)
    table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
    # Domyslnie Qt przewija w poziomie skokami po calych kolumnach, co przy
    # szerokich kolumnach opisowych wyglada jak przeskakiwanie. Przewijanie
    # po pikselach jest plynne.
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    table.setProperty(_STRETCH_PROP, tuple(stretch))
    table.setProperty(_MANUAL_PROP, False)
    table.setProperty(_AUTOSIZING_PROP, False)

    # Sortowanie startuje bez wskazanej kolumny: tabela zachowuje naturalny
    # porzadek danych, dopoki uzytkownik nie kliknie naglowka. Wybrany
    # porzadek przezywa odswiezenie danych.
    header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
    table.setSortingEnabled(True)

    # Reczna zmiana szerokosci wylacza automat. Zmiane reczna poznajemy po
    # tym, ze w chwili zdarzenia lewy przycisk myszy jest wcisniety nad
    # naglowkiem; programowe ustawienia szerokosci tego nie spelniaja.
    def _mark_manual(_index: int, _old: int, _new: int) -> None:
        if table.property(_AUTOSIZING_PROP):
            return
        buttons = QApplication.mouseButtons()
        if buttons & Qt.MouseButton.LeftButton and header.underMouse():
            table.setProperty(_MANUAL_PROP, True)

    header.sectionResized.connect(_mark_manual)
    table.viewport().installEventFilter(_AutoFitFilter(table))
    autosize_columns(table)


def autosize_columns(table: QTableWidget) -> None:
    """Dopasowuje szerokosci kolumn do tresci i szerokosci tabeli.

    Kolumny spoza ``stretch`` dostaja szerokosc swojej tresci (z gornym
    limitem), kolumny opisowe dziela reszte miejsca. Po pierwszej recznej
    zmianie szerokosci funkcja nic nie robi, zeby nie nadpisywac ukladu
    wybranego przez uzytkownika.
    """
    if table.property(_MANUAL_PROP):
        return
    count = table.columnCount()
    available = table.viewport().width()
    if count == 0 or available <= 0:
        return
    header = table.horizontalHeader()
    stretch = table.property(_STRETCH_PROP) or ()
    stretch_columns = [column for column in stretch if 0 <= column < count]
    if not stretch_columns:
        stretch_columns = [count - 1]

    table.setProperty(_AUTOSIZING_PROP, True)
    try:
        content: dict[int, int] = {}
        for column in range(count):
            hint = max(table.sizeHintForColumn(column), header.sectionSizeHint(column))
            width = min(hint + CONTENT_PADDING, MAX_CONTENT_WIDTH)
            content[column] = max(width, MIN_SECTION_WIDTH)
        fixed = sum(content[c] for c in range(count) if c not in stretch_columns)
        remaining = available - fixed
        share = max(MIN_STRETCH_WIDTH, remaining // len(stretch_columns))
        for column in range(count):
            table.setColumnWidth(column, share if column in stretch_columns else content[column])
    finally:
        table.setProperty(_AUTOSIZING_PROP, False)


@contextmanager
def populate_rows(table: QTableWidget) -> Iterator[None]:
    """Wylacza sortowanie na czas wypelniania tabeli i dopasowuje kolumny.

    Wstawianie wierszy przy wlaczonym sortowaniu przestawia je w trakcie
    zapisu i wartosci trafiaja do niewlasciwych wierszy. Po wyjsciu z bloku
    sortowanie wraca, wiec porzadek wybrany przez uzytkownika jest stosowany
    takze do swiezych danych.
    """
    sorting = table.isSortingEnabled()
    table.setSortingEnabled(False)
    try:
        yield
    finally:
        table.setSortingEnabled(sorting)
        autosize_columns(table)


def filter_table_rows(table: QTableWidget, needle: str) -> None:
    """Ukrywa wiersze, w ktorych zadna komorka nie zawiera szukanego tekstu.

    Filtr dziala na tym, co widac, wiec nie wymaga ponownego zapytania do bazy.
    Pusty tekst pokazuje wszystkie wiersze.
    """
    folded = needle.strip().casefold()
    for row in range(table.rowCount()):
        if not folded:
            table.setRowHidden(row, False)
            continue
        match = False
        for column in range(table.columnCount()):
            item = table.item(row, column)
            if item is not None and folded in item.text().casefold():
                match = True
                break
        table.setRowHidden(row, not match)


def text_item(value: str) -> QTableWidgetItem:
    """Komorka tekstowa z podpowiedzia rowna tresci.

    Dlugie komunikaty i sciezki sa przycinane wielokropkiem, a tabela nie ma
    innego sposobu pokazania pelnej tresci niz reczne poszerzanie kolumny.
    """
    item = SortableItem(value)
    if value:
        item.setToolTip(value)
    return item


def format_stamp(value: str) -> str:
    """Data i godzina w postaci czytelnej dla czlowieka.

    Wartosci w bazie sa zapisane w formacie ISO wraz ze strefa i mikrosekundami.
    W tabeli pokazujemy sam dzien i godzine z dokladnoscia do sekundy.
    """
    text = value.strip()
    if not text:
        return ""
    try:
        moment = _dt.datetime.fromisoformat(text)
    except ValueError:
        return text
    return moment.strftime("%Y-%m-%d %H:%M:%S")


__all__ = [
    "MAX_CONTENT_WIDTH",
    "MIN_SECTION_WIDTH",
    "MIN_STRETCH_WIDTH",
    "ROW_HEIGHT",
    "SortableItem",
    "autosize_columns",
    "configure_columns",
    "filter_table_rows",
    "format_stamp",
    "populate_rows",
    "text_item",
]
