"""Testy parsera PDF oraz funkcji pomocniczych warstwy OCR."""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable
from pathlib import Path

import pytest
from parser_data import DISCLAIMER, POLISH_SAMPLE, assert_polish

from finddocs.errors import CorruptedFileError, ExtractionError
from finddocs.extractors.base import ExtractionContext
from finddocs.extractors.pdf import (
    MIN_CHARS_PER_PAGE,
    PdfExtractor,
    parse_pdf_date,
    pdf_page_count,
    pdf_page_image_dpi,
    render_pdf_page,
)
from finddocs.types import SupportLevel, TextOrigin


def test_tekst_i_polskie_znaki(text_pdf: Path, context: ExtractionContext) -> None:
    """PDF z warstwa tekstowa zwraca tekst z zachowanymi polskimi znakami."""
    result = PdfExtractor().extract(text_pdf, context)

    assert result.sections, "parser nie zwrocil zadnej sekcji"
    text = result.all_text()
    assert_polish(text)
    assert DISCLAIMER in text
    assert "00 1234 5678 9012 3456 7890 1234" in text
    assert result.needs_ocr is False
    assert result.origin is TextOrigin.NATIVE
    assert result.parser_name == "pdf"
    assert result.support_level is SupportLevel.FULL


def test_sekcje_odpowiadaja_stronom(multipage_pdf: Path, context: ExtractionContext) -> None:
    """Kazda strona trafia do osobnej sekcji z numerem strony liczonym od jedynki."""
    result = PdfExtractor().extract(multipage_pdf, context)

    assert result.total_pages >= 2
    assert result.metadata.page_count == result.total_pages
    assert all(section.kind == "page" for section in result.sections)
    assert [section.page for section in result.sections] == list(range(1, len(result.sections) + 1))
    assert_polish(result.all_text())


def test_metadane_dokumentu(text_pdf: Path, context: ExtractionContext) -> None:
    """Slownik Info dokumentu trafia do metadanych wyniku."""
    result = PdfExtractor().extract(text_pdf, context)

    assert result.metadata.title == "Umowa testowa"
    assert result.metadata.author == "Zespol FindDocs"
    assert result.metadata.producer == "FindDocs demo"
    created = result.metadata.created_at
    assert created is not None
    assert (created.year, created.month, created.day) == (2024, 3, 15)
    assert (created.hour, created.minute, created.second) == (10, 20, 30)


def test_metadane_z_polskim_tytulem(
    make_text_pdf: Callable[..., Path], context: ExtractionContext
) -> None:
    """Tytul zapisany jako UTF-16BE zachowuje polskie znaki."""
    path = make_text_pdf("tytul.pdf", None, title=POLISH_SAMPLE)
    result = PdfExtractor().extract(path, context)

    assert result.metadata.title == POLISH_SAMPLE


def test_skan_wymaga_ocr(scan_pdf: Path, context: ExtractionContext) -> None:
    """PDF zlozony z samego obrazu nie ma warstwy tekstowej i kwalifikuje sie do OCR."""
    result = PdfExtractor().extract(scan_pdf, context)

    assert result.needs_ocr is True
    assert result.sections == []
    assert result.total_pages == 1
    assert any("OCR" in warning for warning in result.warnings)


def test_uboga_warstwa_tekstowa_wymaga_ocr(
    make_text_pdf: Callable[..., Path], context: ExtractionContext
) -> None:
    """Kilka znakow na strone to za malo, zeby uznac warstwe tekstowa za uzyteczna."""
    path = make_text_pdf("ubogi.pdf", ["Zażółć"])
    result = PdfExtractor().extract(path, context)

    assert result.needs_ocr is True
    assert result.text_length < MIN_CHARS_PER_PAGE
    assert_polish(result.all_text() + " gęślą jaźń")


def test_uszkodzony_plik(broken_pdf: Path, context: ExtractionContext) -> None:
    """Plik z sygnatura PDF, ale bez struktury obiektow, jest raportowany jako uszkodzony."""
    with pytest.raises(CorruptedFileError) as info:
        PdfExtractor().extract(broken_pdf, context)

    assert info.value.code == "FD-3002"


def test_pusty_plik(write_file: Callable[[str, bytes], Path], context: ExtractionContext) -> None:
    """Plik zerowej dlugosci z rozszerzeniem pdf tez jest bledem odczytu."""
    path = write_file("pusty.pdf", b"")

    with pytest.raises(CorruptedFileError):
        PdfExtractor().extract(path, context)


def test_pdf_page_count(text_pdf: Path, multipage_pdf: Path) -> None:
    """Funkcja pomocnicza zwraca liczbe stron bez odczytu tekstu."""
    assert pdf_page_count(text_pdf) == 1
    assert pdf_page_count(multipage_pdf) >= 2


def test_pdf_page_image_dpi_dla_czystego_skanu(scan_pdf: Path) -> None:
    """Strona bedaca jednym obrazem zwraca wlasna gestosc pikseli obrazu."""
    dpi = pdf_page_image_dpi(scan_pdf, 0)

    # Obraz 420x594 px lezy na stronie A4 (595x842 pt), czyli okolo 51 dpi.
    assert dpi is not None
    assert dpi == pytest.approx(420 / (595.0 / 72.0), rel=0.05)


def test_pdf_page_image_dpi_strony_tekstowej(text_pdf: Path) -> None:
    """Strona z trescia inna niz obraz nie dostaje ograniczenia."""
    assert pdf_page_image_dpi(text_pdf, 0) is None


def test_pdf_page_image_dpi_poza_zakresem_i_uszkodzony(scan_pdf: Path, broken_pdf: Path) -> None:
    """Zla strona albo nieczytelny plik oznacza brak oceny, nie wyjatek."""
    assert pdf_page_image_dpi(scan_pdf, 5) is None
    assert pdf_page_image_dpi(scan_pdf, -1) is None
    assert pdf_page_image_dpi(broken_pdf, 0) is None


def test_render_pdf_page_rozsadny_rozmiar(text_pdf: Path) -> None:
    """Rasteryzacja strony A4 przy 150 dpi daje obraz o oczekiwanych proporcjach."""
    image = render_pdf_page(text_pdf, 0, dpi=150)

    assert image.mode in {"L", "RGB"}
    assert 1000 < image.width < 1600
    assert 1400 < image.height < 2200
    assert image.height > image.width


def test_render_pdf_page_ogranicza_liczbe_pikseli(text_pdf: Path) -> None:
    """Limit pikseli zmniejsza skale renderowania, a nie przerywa rasteryzacji."""
    image = render_pdf_page(text_pdf, 0, dpi=600, max_pixels=200_000)

    assert image.width * image.height <= 200_000
    assert image.width > 0 and image.height > 0


@pytest.mark.parametrize(
    ("page_index", "dpi"),
    [(-1, 220), (5, 220), (0, 0)],
)
def test_render_pdf_page_bledne_argumenty(text_pdf: Path, page_index: int, dpi: int) -> None:
    """Ujemna strona, strona spoza zakresu i niedodatnie dpi konczy sie bledem ekstrakcji."""
    with pytest.raises(ExtractionError):
        render_pdf_page(text_pdf, page_index, dpi=dpi)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("D:20240315102030", _dt.datetime(2024, 3, 15, 10, 20, 30)),
        ("D:20240315", _dt.datetime(2024, 3, 15)),
        (
            "D:20240315102030+02'00'",
            _dt.datetime(2024, 3, 15, 10, 20, 30, tzinfo=_dt.timezone(_dt.timedelta(hours=2))),
        ),
        ("D:20240315102030Z", _dt.datetime(2024, 3, 15, 10, 20, 30, tzinfo=_dt.UTC)),
    ],
)
def test_parse_pdf_date(raw: str, expected: _dt.datetime) -> None:
    """Data w formacie PDF jest rozkladana wraz ze strefa czasowa."""
    assert parse_pdf_date(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "brak daty", "D:20241332999999"])
def test_parse_pdf_date_wartosci_bledne(raw: str | None) -> None:
    """Wartosc pusta albo niezgodna z formatem nie przerywa ekstrakcji."""
    assert parse_pdf_date(raw) is None
