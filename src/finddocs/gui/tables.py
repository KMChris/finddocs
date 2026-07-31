"""Wspolne ustawienia tabel interfejsu.

Domyslne zachowanie Qt daje kazdej kolumnie te sama szerokosc, a nadmiar oddaje
ostatniej. W praktyce konczy sie to tak, ze kolumna z data zajmuje polowe tabeli,
a nazwa pliku i komunikat bledu sa przyciete do kilkunastu znakow. Modul ustawia
to raz i tak samo we wszystkich widokach.
"""

from __future__ import annotations

import datetime as _dt

from PySide6.QtWidgets import QHeaderView, QTableWidget

#: Minimalna szerokosc kolumny opisowej, zeby naglowek zawsze byl czytelny.
MIN_STRETCH_WIDTH = 140


def configure_columns(table: QTableWidget, stretch: tuple[int, ...]) -> None:
    """Kolumny z ``stretch`` dziela wolne miejsce, pozostale dostaja tyle, ile trzeba.

    Uzytkownik moze potem zmienic szerokosc recznie: kolumny opisowe pozostaja
    rozciagliwe, a krotkie przechodza w tryb interaktywny po pierwszym ulozeniu.
    """
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    for column in range(table.columnCount()):
        if column in stretch:
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
            header.setMinimumSectionSize(min(header.minimumSectionSize(), MIN_STRETCH_WIDTH))
        else:
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)


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


__all__ = ["MIN_STRETCH_WIDTH", "configure_columns", "format_stamp"]
