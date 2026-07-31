"""Testy parsera dokumentow Word w formacie Office Open XML."""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from parser_data import DISCLAIMER, OLE_SIGNATURE, POLISH_SAMPLE, assert_polish

from finddocs.errors import CorruptedFileError, EmptyDocumentError, PasswordProtectedError
from finddocs.extractors.base import ExtractionContext
from finddocs.extractors.docx import DocxExtractor
from finddocs.types import SupportLevel


def test_kolejnosc_akapitow_i_tabeli(sample_docx: Path, context: ExtractionContext) -> None:
    """Akapity i tabela trafiaja do sekcji w kolejnosci wystapienia w dokumencie."""
    result = DocxExtractor().extract(sample_docx, context)

    kinds = [section.kind for section in result.sections]
    texts = [section.text for section in result.sections]
    assert kinds[0] == "text"
    assert texts[0] == "Procedura przelewów"
    assert texts[1] == POLISH_SAMPLE
    assert texts[2] == DISCLAIMER
    assert "table_header" in kinds
    assert kinds.index("table_header") > kinds.index("text")
    assert kinds.count("table_row") == 2
    assert [section.order for section in result.sections] == list(range(len(result.sections)))


def test_polskie_znaki_w_tabeli(sample_docx: Path, context: ExtractionContext) -> None:
    """Komorki tabeli zachowuja polskie znaki i sa opisane nazwa kolumny."""
    result = DocxExtractor().extract(sample_docx, context)

    rows = [section for section in result.sections if section.kind == "table_row"]
    assert rows[0].text == "Kolumna: Wpłata gotówkowa | Kwota: 1 234,56 | Waluta: PLN"
    assert rows[1].text.startswith("Kolumna: Przelew wychodzący")
    assert_polish(result.all_text())


def test_naglowek_tabeli_i_numeracja_wierszy(
    sample_docx: Path, context: ExtractionContext
) -> None:
    """Pierwszy wiersz tabeli jest naglowkiem, a wiersze danych numerowane od dwojki."""
    result = DocxExtractor().extract(sample_docx, context)

    header = next(section for section in result.sections if section.kind == "table_header")
    rows = [section for section in result.sections if section.kind == "table_row"]
    assert header.text == "Kolumna | Kwota | Waluta"
    assert header.row == 1
    assert [row.row for row in rows] == [2, 3]


def test_naglowek_dokumentu_jest_dziedziczony(
    make_docx: Callable[..., Path], context: ExtractionContext
) -> None:
    """Akapit ze stylem Heading ustawia kontekst naglowka dla kolejnych sekcji."""
    path = make_docx("naglowki.docx", heading="Rozdział pierwszy", paragraphs=[POLISH_SAMPLE])
    result = DocxExtractor().extract(path, context)

    heading_section = result.sections[0]
    assert heading_section.extra.get("styl", "").startswith("Heading")
    assert heading_section.heading == "Rozdział pierwszy"
    assert result.sections[1].heading == "Rozdział pierwszy"


def test_metadane_z_core_properties(sample_docx: Path, context: ExtractionContext) -> None:
    """Wlasciwosci pakietu trafiaja do metadanych wyniku wraz z polskimi znakami."""
    result = DocxExtractor().extract(sample_docx, context)
    metadata = result.metadata

    assert metadata.title == "Procedura przelewów krajowych"
    assert metadata.author == "Łucja Żółw"
    assert metadata.subject == "Obsługa klienta"
    assert metadata.keywords is not None and "ćwiczenie" in metadata.keywords
    assert metadata.language == "pl-PL"
    assert metadata.created_at is not None
    assert metadata.created_at.year == 2024
    assert result.parser_name == "docx"
    assert result.support_level is SupportLevel.FULL


def test_pusty_dokument(make_docx: Callable[..., Path], context: ExtractionContext) -> None:
    """Dokument bez tresci tekstowej konczy sie wyjatkiem EmptyDocumentError."""
    path = make_docx("pusty.docx", heading=None, paragraphs=[])

    with pytest.raises(EmptyDocumentError) as info:
        DocxExtractor().extract(path, context)

    assert info.value.code == "FD-3004"
    assert info.value.details["obrazy"] == 0


def test_uszkodzony_zip(
    write_file: Callable[[str, bytes], Path], context: ExtractionContext
) -> None:
    """Plik z sygnatura ZIP, ale bez struktury archiwum, jest raportowany jako uszkodzony."""
    path = write_file("uszkodzony.docx", b"PK\x03\x04" + b"\x00" * 128)

    with pytest.raises(CorruptedFileError) as info:
        DocxExtractor().extract(path, context)

    assert info.value.code == "FD-3002"


def test_archiwum_bez_czesci_worda(
    docs_dir: Path, context: ExtractionContext
) -> None:
    """Poprawne archiwum ZIP bez czesci word/document.xml nie jest pakietem Word."""
    path = docs_dir / "obce.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("dane.txt", "Zażółć gęślą jaźń")

    with pytest.raises(CorruptedFileError):
        DocxExtractor().extract(path, context)


def test_dokument_zaszyfrowany(
    write_file: Callable[[str, bytes], Path], context: ExtractionContext
) -> None:
    """Zaszyfrowany plik docx jest zapisany jako kontener OLE, nie jako archiwum ZIP."""
    path = write_file("zaszyfrowany.docx", OLE_SIGNATURE + b"\x00" * 512)

    with pytest.raises(PasswordProtectedError) as info:
        DocxExtractor().extract(path, context)

    assert info.value.code == "FD-3003"


def test_tabela_bez_naglowka(make_docx: Callable[..., Path], context: ExtractionContext) -> None:
    """Tabela z samymi liczbami w pierwszym wierszu nie dostaje sekcji naglowka."""
    path = make_docx(
        "liczby.docx",
        heading=None,
        paragraphs=[POLISH_SAMPLE],
        table=(["1 234,56", "99,00"], [["12,00", "13,00"]]),
    )
    result = DocxExtractor().extract(path, context)

    kinds = [section.kind for section in result.sections]
    assert "table_header" not in kinds
    assert kinds.count("table_row") == 2
