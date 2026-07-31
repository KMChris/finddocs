"""Testy parsera plikow rozdzielanych separatorem: CSV oraz TSV."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from parser_data import DISCLAIMER, POLISH_SAMPLE, assert_polish

from finddocs.errors import EmptyDocumentError
from finddocs.extractors.base import ExtractionContext
from finddocs.extractors.csv_table import CsvExtractor

#: Wiersze uzywane w wiekszosci testow: naglowek i dwa wiersze danych.
ROWS: list[list[str]] = [
    ["Opis", "Kwota", "Data"],
    ["Wpłata gotówkowa", "1234,56", "2024-03-15"],
    [POLISH_SAMPLE, "99,00", "2024-03-16"],
]

#: Te same dane z kropka dziesietna, zeby przecinek mogl byc separatorem kolumn.
ROWS_DOT: list[list[str]] = [
    ["Opis", "Kwota", "Data"],
    ["Wpłata gotówkowa", "1234.56", "2024-03-15"],
    [POLISH_SAMPLE, "99.00", "2024-03-16"],
]


@pytest.mark.parametrize(
    ("delimiter", "name"),
    [(",", "przecinek.csv"), (";", "srednik.csv"), ("\t", "tabulator.tsv"), ("|", "kreska.csv")],
)
def test_separatory(
    make_csv: Callable[..., Path], context: ExtractionContext, delimiter: str, name: str
) -> None:
    """Parser rozpoznaje wszystkie cztery obslugiwane separatory kolumn."""
    path = make_csv(name, ROWS_DOT, delimiter=delimiter)

    result = CsvExtractor().extract(path, context)

    assert result.metadata.extra["delimiter"] == delimiter
    assert result.metadata.extra["has_header"] is True
    assert result.metadata.extra["columns"] == 3
    assert result.metadata.extra["data_rows"] == 2
    assert_polish(result.all_text())


@pytest.mark.parametrize(
    ("encoding", "name"),
    [
        ("utf-8", "utf8.csv"),
        ("utf-8-sig", "utf8-bom.csv"),
        ("cp1250", "cp1250.csv"),
        ("utf-16", "utf16.csv"),
    ],
)
def test_kodowania(
    make_csv: Callable[..., Path], context: ExtractionContext, encoding: str, name: str
) -> None:
    """Polskie znaki sa odczytywane poprawnie w kazdym obslugiwanym kodowaniu."""
    rows = [*ROWS, [DISCLAIMER, "0,00", "2024-03-17"]]
    path = make_csv(name, rows, encoding=encoding)

    result = CsvExtractor().extract(path, context)

    text = result.all_text()
    assert_polish(text)
    assert "Wpłata gotówkowa" in text
    assert DISCLAIMER in text
    assert result.metadata.extra["encoding"]


def test_znak_bom_nie_trafia_do_naglowka(
    make_csv: Callable[..., Path], context: ExtractionContext
) -> None:
    """Znacznik kolejnosci bajtow jest usuwany, wiec nazwa pierwszej kolumny jest czysta."""
    path = make_csv("bom.csv", ROWS, encoding="utf-8-sig")

    result = CsvExtractor().extract(path, context)

    header = next(section for section in result.sections if section.kind == "table_header")
    assert header.text.startswith("Opis |")
    assert "﻿" not in result.all_text()


def test_naglowek_i_wiersze(make_csv: Callable[..., Path], context: ExtractionContext) -> None:
    """Naglowek dostaje wlasna sekcje, a wartosci sa opisane nazwami kolumn."""
    path = make_csv("dane.csv", ROWS)

    result = CsvExtractor().extract(path, context)

    header = next(section for section in result.sections if section.kind == "table_header")
    rows = [section for section in result.sections if section.kind == "table_row"]
    assert header.text == "Opis | Kwota | Data"
    assert header.row == 1
    assert rows[0].text == "Opis: Wpłata gotówkowa | Kwota: 1234,56 | Data: 2024-03-15"
    assert [row.row for row in rows] == [2, 3]
    assert all(row.heading == header.text for row in rows)


def test_brak_naglowka(make_csv: Callable[..., Path], context: ExtractionContext) -> None:
    """Plik zaczynajacy sie od liczb nie ma naglowka, wszystkie wiersze sa danymi."""
    path = make_csv("liczby.csv", [["1", "2", "3"], ["4", "5", "6"]])

    result = CsvExtractor().extract(path, context)

    assert result.metadata.extra["has_header"] is False
    assert [section.kind for section in result.sections] == ["table_row", "table_row"]
    assert result.sections[0].text == "1 | 2 | 3"


def test_wiersze_o_roznej_liczbie_pol(
    make_csv: Callable[..., Path], context: ExtractionContext
) -> None:
    """Wiersz dluzszy albo krotszy od naglowka nie przerywa odczytu pliku.

    Naglowek jest rozpoznawany po porownaniu dwoch pierwszych wierszy, wiec musza
    one miec te sama liczbe pol. Rozjezdzaja sie dopiero kolejne wiersze danych.
    """
    rows = [
        ["Opis", "Kwota", "Data"],
        ["Wpłata gotówkowa", "1234,56", "2024-03-15"],
        ["Przelew wychodzący", "99,00", "2024-03-16", "nadmiarowe pole"],
        [POLISH_SAMPLE, "5,00"],
    ]
    path = make_csv("nierowne.csv", rows)

    result = CsvExtractor().extract(path, context)

    data = [section.text for section in result.sections if section.kind == "table_row"]
    assert len(data) == 3
    assert data[1].endswith("| nadmiarowe pole")
    assert data[2] == f"Opis: {POLISH_SAMPLE} | Kwota: 5,00"
    assert result.metadata.extra["data_rows"] == 3


def test_pusty_plik(make_csv: Callable[..., Path], context: ExtractionContext) -> None:
    """Plik o zerowej dlugosci konczy sie wyjatkiem EmptyDocumentError."""
    path = make_csv("pusty.csv", [], newline="")

    with pytest.raises(EmptyDocumentError) as info:
        CsvExtractor().extract(path, context)

    assert info.value.code == "FD-3004"


def test_plik_z_samymi_separatorami(
    make_csv: Callable[..., Path], context: ExtractionContext
) -> None:
    """Plik bez tresci w komorkach nie zawiera wierszy do zaindeksowania."""
    path = make_csv("puste-pola.csv", [[";", ";"], [";", ";"]], delimiter=";")

    with pytest.raises(EmptyDocumentError):
        CsvExtractor().extract(path, context)


def test_limit_wierszy(make_csv: Callable[..., Path]) -> None:
    """Limit csv_max_rows przerywa odczyt i dodaje ostrzezenie."""
    rows = [["Opis", "Numer"]]
    rows.extend([f"{POLISH_SAMPLE} {index}", str(index)] for index in range(20))
    path = make_csv("duzy.csv", rows)

    result = CsvExtractor().extract(path, ExtractionContext(csv_max_rows=4))

    assert len([s for s in result.sections if s.kind == "table_row"]) == 4
    assert any("limit 4 wierszy" in warning for warning in result.warnings)
    assert result.metadata.extra["data_rows"] == 4


def test_pola_w_cudzyslowie(make_csv: Callable[..., Path], context: ExtractionContext) -> None:
    """Separator wewnatrz pola w cudzyslowie nie dzieli komorki."""
    path = make_csv(
        "cytaty.csv",
        [["Opis", "Uwagi"], ["Wpłata", '"Zażółć gęślą jaźń; ćma"']],
    )

    result = CsvExtractor().extract(path, context)

    row = next(section for section in result.sections if section.kind == "table_row")
    assert row.text == "Opis: Wpłata | Uwagi: Zażółć gęślą jaźń; ćma"
