"""Testy regresyjne parsera prezentacji PowerPoint (.pptx, .ppsx).

Kazdy test buduje prezentacje od zera biblioteka python-pptx, wiec repozytorium
nie zawiera zadnych binariow. Sprawdzana jest kolejnosc slajdow, numeracja stron,
tabele, notatki prelegenta, metadane i obsluga plikow zabezpieczonych haslem.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from parser_data import DISCLAIMER, POLISH_SAMPLE, assert_polish, build_ole_container

from finddocs.errors import EmptyDocumentError, PasswordProtectedError
from finddocs.extractors.base import ExtractionContext
from finddocs.extractors.detect import detect_file_type
from finddocs.extractors.pptx import PptxExtractor
from finddocs.extractors.registry import build_default_registry
from finddocs.types import SupportLevel, TextOrigin


def test_slajdy_zachowuja_kolejnosc_i_numeracje(
    make_pptx: Callable[..., Path], context: ExtractionContext
) -> None:
    """Tresc slajdow trafia do sekcji w kolejnosci pokazu, z numerem slajdu."""
    path = make_pptx(
        slides=[
            ("Wprowadzenie", [POLISH_SAMPLE]),
            ("Procedura", [DISCLAIMER, "Krok pierwszy: weryfikacja klienta."]),
        ]
    )

    result = PptxExtractor().extract(path, context)

    assert result.parser_name == "pptx"
    assert result.support_level is SupportLevel.FULL
    assert result.origin is TextOrigin.NATIVE
    assert result.needs_ocr is False
    assert result.total_pages == 2
    assert_polish(result.all_text())

    pages = [section.page for section in result.sections]
    assert pages == sorted(pages)
    first = [s for s in result.sections if s.page == 1]
    second = [s for s in result.sections if s.page == 2]
    assert any(POLISH_SAMPLE in s.text for s in first)
    assert any("Krok pierwszy" in s.text for s in second)


def test_tytul_slajdu_jest_naglowkiem_sekcji(
    make_pptx: Callable[..., Path], context: ExtractionContext
) -> None:
    """Sekcje slajdu dziedzicza jego tytul, jak akapity pod naglowkiem w Wordzie."""
    path = make_pptx(slides=[("Plan naprawczy", [POLISH_SAMPLE])])

    result = PptxExtractor().extract(path, context)

    body = [s for s in result.sections if POLISH_SAMPLE in s.text]
    assert body and body[0].heading == "Plan naprawczy"


def test_tabela_slajdu_zachowuje_naglowek_i_wiersze(
    make_pptx: Callable[..., Path], context: ExtractionContext
) -> None:
    """Tabela daje sekcje naglowka kolumn i wierszy z nazwami kolumn."""
    path = make_pptx(
        slides=[("Cennik", ["Obowiązuje od marca."])],
        table=(
            ["Opis", "Kwota"],
            [["Wpłata gotówkowa", "1 234,56"], ["Przelew wychodzący", "99,00"]],
        ),
    )

    result = PptxExtractor().extract(path, context)

    kinds = {section.kind for section in result.sections}
    assert "table_header" in kinds
    assert "table_row" in kinds
    rows = [s for s in result.sections if s.kind == "table_row"]
    assert any("Opis: Wpłata gotówkowa" in s.text for s in rows)
    assert any("Kwota: 99,00" in s.text for s in rows)


def test_notatki_prelegenta_sa_indeksowane(
    make_pptx: Callable[..., Path], context: ExtractionContext
) -> None:
    """Notatki pod slajdem trafiaja do sekcji tego samego slajdu."""
    path = make_pptx(
        slides=[("Slajd", ["Treść widoczna."])],
        notes=[f"Notatka prelegenta: {DISCLAIMER}"],
    )

    result = PptxExtractor().extract(path, context)

    notes = [s for s in result.sections if s.extra.get("zrodlo") == "notatki prelegenta"]
    assert notes and DISCLAIMER in notes[0].text
    assert notes[0].page == 1


def test_metadane_prezentacji(make_pptx: Callable[..., Path], context: ExtractionContext) -> None:
    """Tytul, autor i slowa kluczowe pakietu trafiaja do metadanych."""
    path = make_pptx(slides=[("Agenda", [POLISH_SAMPLE])])

    result = PptxExtractor().extract(path, context)

    assert result.metadata.title == "Szkolenie z przelewów"
    assert result.metadata.author == "Łucja Żółw"
    assert result.metadata.keywords == "przelew; szkolenie"
    assert result.metadata.page_count == 1


def test_pusta_prezentacja_konczy_sie_wyjatkiem(
    make_pptx: Callable[..., Path], context: ExtractionContext
) -> None:
    """Prezentacja bez tekstu to dokument pusty, a nie blad parsera."""
    path = make_pptx(slides=[])

    with pytest.raises(EmptyDocumentError):
        PptxExtractor().extract(path, context)


def test_zaszyfrowana_prezentacja_to_kontener_ole(
    write_file: Callable[[str, bytes], Path], context: ExtractionContext
) -> None:
    """Plik .pptx zapisany jako kontener OLE oznacza ochrone haslem."""
    path = write_file("tajna.pptx", build_ole_container([(("EncryptedPackage",), b"\x00" * 64)]))

    with pytest.raises(PasswordProtectedError):
        PptxExtractor().extract(path, context)


def test_ppsx_przechodzi_przez_rejestr(
    make_pptx: Callable[..., Path], context: ExtractionContext
) -> None:
    """Pokaz slajdow .ppsx jest rozpoznawany po tresci i parsowany jak .pptx."""
    path = make_pptx("pokaz.ppsx", slides=[("Pokaz", [POLISH_SAMPLE])])

    info = detect_file_type(path)
    assert info.mime_type.endswith("presentationml.presentation")

    result, _info = build_default_registry().extract(path, context)
    assert result.parser_name == "pptx"
    assert POLISH_SAMPLE in result.all_text()
