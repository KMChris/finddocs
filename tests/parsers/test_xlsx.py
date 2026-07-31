"""Testy parsera skoroszytow Excel w formacie Office Open XML."""

from __future__ import annotations

import datetime as _dt
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from parser_data import DISCLAIMER, OLE_SIGNATURE, POLISH_SAMPLE, assert_polish

from finddocs.errors import CorruptedFileError, EmptyDocumentError, PasswordProtectedError
from finddocs.extractors.base import ExtractionContext
from finddocs.extractors.xlsx import XlsxExtractor, format_cell


def test_dwa_arkusze(sample_xlsx: Path, context: ExtractionContext) -> None:
    """Kazdy arkusz dostaje wlasna sekcje naglowkowa, a sekcje znaja nazwe arkusza."""
    result = XlsxExtractor().extract(sample_xlsx, context)

    sheets = [section for section in result.sections if section.kind == "sheet"]
    assert [section.text for section in sheets] == ["Arkusz: Transakcje", "Arkusz: Podsumowanie"]
    assert result.metadata.extra["arkusze"] == ["Transakcje", "Podsumowanie"]
    assert result.metadata.extra["liczba_arkuszy"] == 2
    assert {section.sheet for section in result.sections} == {"Transakcje", "Podsumowanie"}


def test_naglowek_kolumn_i_opis_wartosci(sample_xlsx: Path, context: ExtractionContext) -> None:
    """Pierwszy wiersz tekstowy staje sie naglowkiem, a wartosci dostaja nazwy kolumn."""
    result = XlsxExtractor().extract(sample_xlsx, context)

    header = next(
        section
        for section in result.sections
        if section.kind == "table_header" and section.sheet == "Transakcje"
    )
    assert header.text == "Opis | Kwota | Data | Sztuki"
    rows = [
        section
        for section in result.sections
        if section.kind == "table_row" and section.sheet == "Transakcje"
    ]
    assert rows[0].text.startswith("Opis: Wpłata gotówkowa | Kwota: 1234.56")
    assert rows[0].heading == header.text
    assert_polish(result.all_text())


def test_numeracja_wierszy_zgodna_z_excelem(sample_xlsx: Path, context: ExtractionContext) -> None:
    """Numer wiersza w sekcji odpowiada numerowi widocznemu w Excelu."""
    result = XlsxExtractor().extract(sample_xlsx, context)

    transakcje = [section for section in result.sections if section.sheet == "Transakcje"]
    numbered = [(section.kind, section.row) for section in transakcje if section.row is not None]
    assert numbered == [("table_header", 1), ("table_row", 2), ("table_row", 3)]


def test_numeracja_pomija_puste_wiersze_na_poczatku(
    make_xlsx: Callable[..., Path], context: ExtractionContext
) -> None:
    """Puste wiersze na gorze arkusza nie przesuwaja numeracji wierszy z danymi."""
    path = make_xlsx(
        "przesuniete.xlsx",
        [("Dane", [[], [], ["Opis", "Kwota"], [POLISH_SAMPLE, 42]])],
    )
    result = XlsxExtractor().extract(path, context)

    numbered = [(section.kind, section.row) for section in result.sections if section.row]
    assert numbered == [("table_header", 3), ("table_row", 4)]


def test_daty_i_liczby_calkowite(sample_xlsx: Path, context: ExtractionContext) -> None:
    """Daty sa zapisywane w formacie ISO, a liczby calkowite bez koncowki .0."""
    result = XlsxExtractor().extract(sample_xlsx, context)

    rows = [
        section.text
        for section in result.sections
        if section.kind == "table_row" and section.sheet == "Transakcje"
    ]
    assert "Data: 2024-03-15" in rows[0]
    assert "Sztuki: 7" in rows[0]
    assert "Data: 2024-03-16 08:30" in rows[1]
    assert ".0 " not in " ".join(rows) + " "
    assert not any(part.endswith(".0") for part in " ".join(rows).split())


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (7, "7"),
        (7.0, "7"),
        (1234.56, "1234.56"),
        (True, "PRAWDA"),
        (False, "FALSZ"),
        (None, ""),
        (_dt.date(2024, 3, 15), "2024-03-15"),
        (_dt.datetime(2024, 3, 15, 8, 30), "2024-03-15 08:30"),
        (_dt.datetime(2024, 3, 15, 8, 30, 5), "2024-03-15 08:30:05"),
        (_dt.time(8, 30), "08:30"),
        (POLISH_SAMPLE, POLISH_SAMPLE),
    ],
)
def test_format_cell(value: object, expected: str) -> None:
    """Konwersja wartosci komorki na tekst nie gubi polskich znakow ani precyzji."""
    assert format_cell(value) == expected


def test_limit_wierszy(make_xlsx: Callable[..., Path]) -> None:
    """Przekroczenie limitu wierszy przerywa odczyt arkusza i dodaje ostrzezenie."""
    rows: list[list[object]] = [["Opis", "Kwota"]]
    rows.extend([f"{POLISH_SAMPLE} {index}", index] for index in range(20))
    path = make_xlsx("duzy.xlsx", [("Dane", rows)])
    context = ExtractionContext(sheet_max_rows=5)

    result = XlsxExtractor().extract(path, context)

    content = [section for section in result.sections if section.kind != "sheet"]
    assert len(content) == 5
    assert any("limit 5 wierszy" in warning for warning in result.warnings)


def test_pusty_skoroszyt(make_xlsx: Callable[..., Path], context: ExtractionContext) -> None:
    """Skoroszyt bez danych konczy sie wyjatkiem EmptyDocumentError."""
    path = make_xlsx("pusty.xlsx", [("Arkusz1", [])])

    with pytest.raises(EmptyDocumentError) as info:
        XlsxExtractor().extract(path, context)

    assert info.value.code == "FD-3004"
    assert info.value.details["arkusze"] == ["Arkusz1"]


def test_metadane_skoroszytu(sample_xlsx: Path, context: ExtractionContext) -> None:
    """Wlasciwosci skoroszytu trafiaja do metadanych wyniku."""
    result = XlsxExtractor().extract(sample_xlsx, context)

    assert result.metadata.title == "Zestawienie transakcji"
    assert result.metadata.author == "Łucja Żółw"
    assert result.metadata.subject == "Rozliczenia"
    assert result.needs_ocr is False


def test_arkusz_bez_naglowka(make_xlsx: Callable[..., Path], context: ExtractionContext) -> None:
    """Arkusz zaczynajacy sie od liczb nie dostaje sekcji naglowka kolumn."""
    path = make_xlsx("liczby.xlsx", [("Dane", [[1, 2, 3], [4, 5, 6]])])
    result = XlsxExtractor().extract(path, context)

    kinds = [section.kind for section in result.sections]
    assert "table_header" not in kinds
    assert kinds.count("table_row") == 2


def test_drugi_arkusz_z_polskim_zdaniem(sample_xlsx: Path, context: ExtractionContext) -> None:
    """Tresc drugiego arkusza tez trafia do wyniku."""
    result = XlsxExtractor().extract(sample_xlsx, context)

    podsumowanie = " ".join(
        section.text for section in result.sections if section.sheet == "Podsumowanie"
    )
    assert "Razem" in podsumowanie
    assert DISCLAIMER in podsumowanie


def test_uszkodzone_archiwum(
    write_file: Callable[[str, bytes], Path], context: ExtractionContext
) -> None:
    """Plik z sygnatura ZIP bez struktury archiwum jest raportowany jako uszkodzony."""
    path = write_file("uszkodzony.xlsx", b"PK\x03\x04" + b"\x11" * 200)

    with pytest.raises(CorruptedFileError) as info:
        XlsxExtractor().extract(path, context)

    assert info.value.code == "FD-3002"


def test_skoroszyt_zaszyfrowany(
    write_file: Callable[[str, bytes], Path], context: ExtractionContext
) -> None:
    """Skoroszyt zabezpieczony haslem jest kontenerem OLE, a nie archiwum ZIP."""
    path = write_file("zaszyfrowany.xlsx", OLE_SIGNATURE + b"\x00" * 512)

    with pytest.raises(PasswordProtectedError) as info:
        XlsxExtractor().extract(path, context)

    assert info.value.code == "FD-3003"


def test_archiwum_bez_skoroszytu(docs_dir: Path, context: ExtractionContext) -> None:
    """Poprawny plik ZIP bez czesci xl/workbook.xml nie jest skoroszytem."""
    path = docs_dir / "obce.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("dane.txt", POLISH_SAMPLE)

    with pytest.raises((CorruptedFileError, EmptyDocumentError)):
        XlsxExtractor().extract(path, context)
