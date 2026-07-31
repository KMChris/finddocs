"""Testy kwalifikowania dokumentow do OCR.

OCR na CPU jest najdrozszym etapem indeksowania, wiec decyzja musi byc jednoznaczna
i uzasadniona kodem powodu, ktory trafia do raportu pokrycia.
"""

from __future__ import annotations

import pytest

from finddocs.config import OcrSettings
from finddocs.extractors.detect import FileTypeInfo
from finddocs.ocr.detector import OcrReason, can_rasterize, decide, pages_needing_ocr
from finddocs.types import ExtractedSection, ExtractionResult

OBRAZ = FileTypeInfo(mime_type="image/png", extension=".png", detected_by="magic")
PDF = FileTypeInfo(mime_type="application/pdf", extension=".pdf", detected_by="magic")
DOCX = FileTypeInfo(
    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    extension=".docx",
    detected_by="zip_entry",
)


def wynik(*sekcje: ExtractedSection, stron: int = 1, needs_ocr: bool = False) -> ExtractionResult:
    """Wynik ekstrakcji z podanymi sekcjami."""
    return ExtractionResult(sections=list(sekcje), total_pages=stron, needs_ocr=needs_ocr)


def dobry_tekst(strona: int = 1) -> ExtractedSection:
    return ExtractedSection(text="Poprawny tekst dokumentu bankowego. " * 20, page=strona)


# --- decyzja o OCR -------------------------------------------------------------


def test_plik_obrazu_zawsze_idzie_do_ocr():
    decyzja = decide(wynik(ExtractedSection(text="")), OBRAZ, OcrSettings())

    assert decyzja.needed is True
    assert decyzja.reason is OcrReason.IMAGE_FILE
    assert "obrazem" in decyzja.describe()


def test_pdf_bez_warstwy_tekstowej():
    decyzja = decide(wynik(stron=3), PDF, OcrSettings())

    assert decyzja.needed is True
    assert decyzja.reason is OcrReason.NO_TEXT_LAYER
    assert "3" in decyzja.detail


def test_pdf_z_dobrym_tekstem_nie_wymaga_ocr():
    decyzja = decide(wynik(dobry_tekst()), PDF, OcrSettings())

    assert decyzja.needed is False
    assert decyzja.reason is OcrReason.NOT_NEEDED


def test_pdf_z_uboga_warstwa_tekstowa():
    decyzja = decide(wynik(ExtractedSection(text="strona 1", page=1), stron=1), PDF, OcrSettings())

    assert decyzja.needed is True
    assert decyzja.reason is OcrReason.TOO_FEW_CHARACTERS


def test_pdf_z_tekstem_uszkodzonym():
    smieci = ExtractedSection(text="#$%^&*()_+ " * 40, page=1)
    decyzja = decide(wynik(smieci), PDF, OcrSettings())

    assert decyzja.needed is True
    assert decyzja.reason is OcrReason.GARBLED_TEXT
    assert "uszkodzony" in decyzja.describe()


def test_parser_moze_sam_zglosic_potrzebe_ocr():
    decyzja = decide(wynik(dobry_tekst(), needs_ocr=True), PDF, OcrSettings())

    assert decyzja.needed is True
    assert decyzja.reason is OcrReason.PARSER_REQUESTED


def test_nieudana_ekstrakcja_kwalifikuje_do_ocr():
    decyzja = decide(None, PDF, OcrSettings(), extraction_failed=True)

    assert decyzja.needed is True
    assert decyzja.reason is OcrReason.EXTRACTION_FAILED


@pytest.mark.parametrize(
    "ustawienia",
    [OcrSettings(enabled=False), OcrSettings(engine="none")],
)
def test_ocr_wylaczony_w_ustawieniach(ustawienia):
    decyzja = decide(wynik(stron=5), PDF, ustawienia)

    assert decyzja.needed is False
    assert decyzja.reason is OcrReason.DISABLED
    assert "wylaczony" in decyzja.describe()


def test_format_nierasteryzowalny_nie_idzie_do_ocr():
    decyzja = decide(wynik(ExtractedSection(text="x"), needs_ocr=True), DOCX, OcrSettings())

    assert decyzja.needed is False
    assert decyzja.reason is OcrReason.UNSUPPORTED_FOR_OCR
    assert DOCX.mime_type in decyzja.detail


def test_format_nierasteryzowalny_z_dobrym_tekstem():
    decyzja = decide(wynik(dobry_tekst()), DOCX, OcrSettings())

    assert decyzja.needed is False
    assert decyzja.reason is OcrReason.NOT_NEEDED


def test_can_rasterize():
    assert can_rasterize(OBRAZ) is True
    assert can_rasterize(PDF) is True
    assert can_rasterize(DOCX) is False


def test_prog_znakow_na_strone_jest_konfigurowalny():
    krotki = wynik(ExtractedSection(text="Krotka notatka na stronie.", page=1))

    assert decide(krotki, PDF, OcrSettings(min_chars_per_page=90)).needed is True
    assert decide(krotki, PDF, OcrSettings(min_chars_per_page=10)).needed is False


# --- wybor stron ---------------------------------------------------------------


def test_pages_needing_ocr_wybiera_tylko_strony_ubogie_w_tekst():
    rezultat = ExtractionResult(
        sections=[
            ExtractedSection(text="A" * 500, page=1),
            ExtractedSection(text="", page=2),
            ExtractedSection(text="B" * 500, page=3),
        ],
        total_pages=4,
    )
    assert pages_needing_ocr(rezultat, OcrSettings(), total_pages=4) == [2, 4]


def test_pages_needing_ocr_sumuje_sekcje_tej_samej_strony():
    rezultat = ExtractionResult(
        sections=[
            ExtractedSection(text="A" * 50, page=1),
            ExtractedSection(text="B" * 50, page=1),
        ],
        total_pages=1,
    )
    assert pages_needing_ocr(rezultat, OcrSettings(min_chars_per_page=90), total_pages=1) == []


def test_pages_needing_ocr_gdy_brak_informacji_o_stronach():
    rezultat = ExtractionResult(sections=[ExtractedSection(text="tekst bez numeru strony")])
    assert pages_needing_ocr(rezultat, OcrSettings(), total_pages=2) == [1, 2]


def test_pages_needing_ocr_dla_zerowej_liczby_stron():
    rezultat = ExtractionResult(sections=[ExtractedSection(text="cokolwiek", page=1)])
    assert pages_needing_ocr(rezultat, OcrSettings(), total_pages=0) == []
