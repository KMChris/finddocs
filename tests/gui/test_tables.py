"""Testy wspolnych ustawien tabel: sortowanie i szerokosci kolumn.

Kazda tabela interfejsu ma sortowac sie po kliknieciu naglowka i pozwalac
na reczna zmiane szerokosci kolumn. Uklad automatyczny dziala do pierwszej
recznej zmiany, a wybrany porzadek sortowania przezywa odswiezenie danych.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableWidget

from finddocs.gui.tables import (
    MIN_STRETCH_WIDTH,
    autosize_columns,
    configure_columns,
    populate_rows,
    text_item,
)


def _make_table(qtbot: object, rows: list[list[str]], *, stretch: tuple[int, ...]) -> QTableWidget:
    table = QTableWidget(0, len(rows[0]) if rows else 2)
    table.setHorizontalHeaderLabels([f"Kolumna {i}" for i in range(table.columnCount())])
    qtbot.addWidget(table)  # type: ignore[attr-defined]
    configure_columns(table, stretch)
    with populate_rows(table):
        for row in rows:
            position = table.rowCount()
            table.insertRow(position)
            for column, value in enumerate(row):
                table.setItem(position, column, text_item(value))
    return table


def _column_values(table: QTableWidget, column: int) -> list[str]:
    return [table.item(row, column).text() for row in range(table.rowCount())]


@pytest.mark.gui
def test_tabela_ma_wlaczone_sortowanie_bez_poczatkowego_porzadku(qtbot: object) -> None:
    """Sortowanie jest dostepne, ale dane startuja w naturalnej kolejnosci."""
    table = _make_table(qtbot, [["b", "1"], ["a", "2"], ["c", "0"]], stretch=(0,))

    assert table.isSortingEnabled() is True
    assert table.horizontalHeader().sortIndicatorSection() == -1
    assert _column_values(table, 0) == ["b", "a", "c"]


@pytest.mark.gui
def test_kolumny_sa_interaktywne_dla_uzytkownika(qtbot: object) -> None:
    """Kazda kolumne mozna zwezic i poszerzyc przeciagnieciem naglowka."""
    table = _make_table(qtbot, [["a", "b", "c"]], stretch=(1,))
    header = table.horizontalHeader()

    for column in range(table.columnCount()):
        assert header.sectionResizeMode(column) is QHeaderView.ResizeMode.Interactive


@pytest.mark.gui
def test_sortowanie_zna_polskie_znaki_i_liczby(qtbot: object) -> None:
    """Porzadek jest naturalny: plik-9 przed plik-10, litery po polsku."""
    table = _make_table(
        qtbot,
        [["plik-10"], ["żaba"], ["plik-9"], ["ćma"], ["ala"]],
        stretch=(0,),
    )

    table.sortItems(0, Qt.SortOrder.AscendingOrder)

    assert _column_values(table, 0) == ["ala", "ćma", "plik-9", "plik-10", "żaba"]


@pytest.mark.gui
def test_porzadek_sortowania_przezywa_odswiezenie_danych(qtbot: object) -> None:
    """Po ponownym wypelnieniu tabela wraca do porzadku wybranego przez uzytkownika."""
    table = _make_table(qtbot, [["b"], ["a"], ["c"]], stretch=(0,))

    table.sortItems(0, Qt.SortOrder.DescendingOrder)
    table.horizontalHeader().setSortIndicator(0, Qt.SortOrder.DescendingOrder)
    assert _column_values(table, 0) == ["c", "b", "a"]

    with populate_rows(table):
        assert table.isSortingEnabled() is False
        table.setRowCount(0)
        for value in ["d", "b", "e"]:
            position = table.rowCount()
            table.insertRow(position)
            table.setItem(position, 0, text_item(value))

    assert table.isSortingEnabled() is True
    assert _column_values(table, 0) == ["e", "d", "b"]


@pytest.mark.gui
def test_wiersze_nie_rozjezdzaja_sie_przy_wypelnianiu_posortowanej_tabeli(
    qtbot: object,
) -> None:
    """Wartosci jednego wiersza zostaja razem takze przy aktywnym sortowaniu."""
    table = _make_table(qtbot, [["b", "2"], ["a", "1"]], stretch=(0,))
    table.sortItems(0, Qt.SortOrder.AscendingOrder)
    table.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)

    with populate_rows(table):
        table.setRowCount(0)
        for name, number in [("c", "3"), ("a", "1"), ("b", "2")]:
            position = table.rowCount()
            table.insertRow(position)
            table.setItem(position, 0, text_item(name))
            table.setItem(position, 1, text_item(number))

    assert _column_values(table, 0) == ["a", "b", "c"]
    assert _column_values(table, 1) == ["1", "2", "3"]


@pytest.mark.gui
def test_kolumna_opisowa_dostaje_wolne_miejsce(qtbot: object) -> None:
    """Kolumny spoza stretch maja szerokosc tresci, opisowa reszte tabeli."""
    table = _make_table(
        qtbot,
        [["a", "krótki", "x"], ["b", "opis", "y"]],
        stretch=(0,),
    )
    table.resize(900, 200)
    table.show()
    autosize_columns(table)

    widths = [table.columnWidth(column) for column in range(3)]
    assert widths[0] >= MIN_STRETCH_WIDTH
    assert widths[0] > widths[1]
    assert widths[0] > widths[2]


@pytest.mark.gui
def test_reczna_szerokosc_nie_jest_nadpisywana(qtbot: object) -> None:
    """Po recznej zmianie szerokosci automat zostawia kolumny w spokoju."""
    table = _make_table(qtbot, [["a", "b"], ["c", "d"]], stretch=(1,))
    table.resize(600, 200)
    table.show()

    table.setProperty("fdManualColumns", True)
    table.setColumnWidth(0, 222)
    autosize_columns(table)

    assert table.columnWidth(0) == 222
