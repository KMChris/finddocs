"""Testy regresyjne parserow obrazow rastrowych i plikow Word 97-2003.

Obraz nie zawiera warstwy tekstowej, wiec poprawnym wynikiem parsera jest brak
sekcji i ustawiona flaga ``needs_ocr``. Pliki .doc czytamy wprost z kontenera OLE,
bez pakietu Office, bo instalator nie moze go wymagac.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from parser_data import DISCLAIMER, POLISH_SAMPLE, assert_polish

from finddocs.errors import (
    EmptyDocumentError,
    PasswordProtectedError,
    UnsupportedFormatError,
)
from finddocs.extractors.base import ExtractionContext
from finddocs.extractors.doc_legacy import LegacyDocComExtractor, LegacyDocOleExtractor
from finddocs.extractors.image import (
    DEFAULT_MAX_FRAMES,
    ImageExtractor,
    image_frame_count,
    load_image_frames,
)
from finddocs.types import SupportLevel

#: Znacznik EXIF z nazwa programu, ktory zapisal obraz.
EXIF_SOFTWARE = 0x0131

#: Znacznik EXIF z opisem obrazu.
EXIF_DESCRIPTION = 0x010E


# --- obrazy ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "image_format"),
    [
        ("skan.png", "PNG"),
        ("skan.jpg", "JPEG"),
        ("skan.tif", "TIFF"),
        ("skan.bmp", "BMP"),
        ("skan.gif", "GIF"),
    ],
)
def test_obraz_zglasza_potrzebe_ocr(
    make_image: Callable[..., Path],
    context: ExtractionContext,
    name: str,
    image_format: str,
) -> None:
    """Kazdy obslugiwany format rastrowy konczy sie wynikiem bez sekcji i z needs_ocr."""
    path = make_image(name, image_format=image_format)

    result = ImageExtractor().extract(path, context)

    assert result.needs_ocr is True
    assert result.sections == []
    assert result.parser_name == "image"
    assert result.support_level is SupportLevel.LIMITED
    assert result.metadata.extra["width"] == 160
    assert result.metadata.extra["height"] == 90


def test_obraz_wielostronicowy_liczy_klatki(
    make_image: Callable[..., Path], context: ExtractionContext
) -> None:
    """TIFF z kilkoma stronami raportuje liczbe klatek jako liczbe stron."""
    path = make_image("wielostronicowy.tif", image_format="TIFF", frames=3)

    result = ImageExtractor().extract(path, context)

    assert result.metadata.page_count == 3
    assert result.total_pages == 3
    assert image_frame_count(path) == 3


def test_obraz_z_wieloma_klatkami_ostrzega_o_limicie(
    make_image: Callable[..., Path], context: ExtractionContext
) -> None:
    """Powyzej limitu klatek parser uprzedza, ze OCR obejmie tylko poczatek."""
    path = make_image("bardzo-dlugi.tif", image_format="TIFF", frames=DEFAULT_MAX_FRAMES + 2)

    result = ImageExtractor().extract(path, context)

    assert any("klatek" in warning for warning in result.warnings)


def test_wczytywanie_klatek_zwraca_obrazy(make_image: Callable[..., Path]) -> None:
    """Funkcja pomocnicza OCR dostaje kolejne klatki jako obrazy Pillow."""
    path = make_image("klatki.tif", image_format="TIFF", frames=2)

    frames = list(load_image_frames(path, max_frames=2))

    assert len(frames) == 2
    assert all(frame.width == 160 for frame in frames)


def test_metadane_exif_trafiaja_do_wyniku(
    make_image: Callable[..., Path], context: ExtractionContext
) -> None:
    """Program zapisujacy obraz z bloku EXIF trafia do pola producer."""
    path = make_image(
        "z-exif.jpg",
        image_format="JPEG",
        exif={EXIF_SOFTWARE: "Skaner biurowy", EXIF_DESCRIPTION: POLISH_SAMPLE},
    )

    result = ImageExtractor().extract(path, context)

    assert result.metadata.producer == "Skaner biurowy"
    assert result.metadata.extra["format"] == "JPEG"


def test_parser_obrazow_deklaruje_rozszerzenia() -> None:
    """Adapter obsluguje wszystkie formaty skanow wymienione w dokumentacji."""
    extractor = ImageExtractor()

    for suffix in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"):
        assert extractor.supports(Path(f"skan{suffix}"), None) is True
    assert extractor.supports(Path("dokument.pdf"), None) is False


# --- Word 97-2003 ----------------------------------------------------------------


def test_doc_odczyt_bez_pakietu_office(
    make_legacy_doc: Callable[..., Path], context: ExtractionContext
) -> None:
    """Tekst z tablicy fragmentow jest skladany niezaleznie od kodowania fragmentu."""
    path = make_legacy_doc()

    result = LegacyDocOleExtractor().extract(path, context)

    text = result.all_text()
    assert "Pismo okolne numer 00-99" in text
    assert_polish(text)
    assert DISCLAIMER in text
    assert result.parser_name == "doc_ole"
    assert result.support_level is SupportLevel.EXPERIMENTAL


def test_doc_ostrzega_o_odczycie_zapasowym(
    make_legacy_doc: Callable[..., Path], context: ExtractionContext
) -> None:
    """Uzytkownik ma wiedziec, ze uklad dokumentu nie zostal odtworzony."""
    path = make_legacy_doc()

    result = LegacyDocOleExtractor().extract(path, context)

    assert result.warnings
    assert any("uklad" in w.lower() or "formatowan" in w.lower() for w in result.warnings)


def test_doc_zaszyfrowany_konczy_sie_wyjatkiem(
    make_legacy_doc: Callable[..., Path], context: ExtractionContext
) -> None:
    """Dokument z ustawiona flaga szyfrowania nie jest probowany na sile."""
    path = make_legacy_doc("zaszyfrowany.doc", encrypted=True)

    with pytest.raises(PasswordProtectedError):
        LegacyDocOleExtractor().extract(path, context)


def test_doc_bez_kontenera_ole_jest_odrzucany(
    write_file: Callable[[str, bytes], Path], context: ExtractionContext
) -> None:
    """Plik z rozszerzeniem doc, ktory nie jest OLE, nie jest dokumentem Word."""
    path = write_file("nie-word.doc", b"To jest zwykly tekst, nie dokument Word." * 20)

    with pytest.raises(UnsupportedFormatError):
        LegacyDocOleExtractor().extract(path, context)


def test_doc_bez_tekstu_konczy_sie_wyjatkiem(
    make_legacy_doc: Callable[..., Path], context: ExtractionContext
) -> None:
    """Dokument z pustymi fragmentami to dokument pusty, a nie uszkodzony."""
    path = make_legacy_doc("pusty.doc", pieces=[("   \r", True)])

    with pytest.raises(EmptyDocumentError):
        LegacyDocOleExtractor().extract(path, context)


def test_doc_com_jest_pomijany_gdy_brak_worda() -> None:
    """Adapter oparty o automatyzacje Office sam zglasza swoja niedostepnosc."""
    extractor = LegacyDocComExtractor()

    if extractor.is_available():
        assert extractor.unavailable_reason() == ""
    else:
        assert extractor.unavailable_reason()
        assert "Word" in extractor.unavailable_reason()


def test_kolejnosc_adapterow_doc_faworyzuje_office() -> None:
    """Gdy Word jest dostepny, wygrywa on, bo lepiej odtwarza uklad dokumentu."""
    assert LegacyDocComExtractor.priority > LegacyDocOleExtractor.priority
