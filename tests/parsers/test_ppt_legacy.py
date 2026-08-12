"""Testy adapterow starego formatu PowerPoint 97-2003.

Pliki testowe buduje ``parser_data.build_legacy_ppt``, wiec repozytorium nie
zawiera binariow. Testy pokrywaja czytnik zapasowy (OLE): atomy tekstowe obu
kodowan, szyfrowanie, pliki uszkodzone i puste. Adapter COM jest sprawdzany
introspekcyjnie, bez uruchamiania PowerPointa, tak jak adapter Worda.
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
from finddocs.extractors.detect import detect_file_type
from finddocs.extractors.ppt_legacy import LegacyPptComExtractor, LegacyPptOleExtractor
from finddocs.extractors.registry import build_default_registry
from finddocs.types import SupportLevel


def test_ppt_odczyt_bez_pakietu_office(
    make_legacy_ppt: Callable[..., Path], context: ExtractionContext
) -> None:
    """Atomy tekstowe obu kodowan trafiaja do sekcji z polskimi znakami."""
    path = make_legacy_ppt()

    result = LegacyPptOleExtractor().extract(path, context)

    text = result.all_text()
    assert "Plan szkolenia." in text
    assert "Sala numer 12" in text
    assert DISCLAIMER in text
    assert_polish(text)
    assert result.parser_name == "ppt_ole"
    assert result.support_level is SupportLevel.EXPERIMENTAL


def test_ppt_znak_konca_akapitu_dzieli_sekcje(
    make_legacy_ppt: Callable[..., Path], context: ExtractionContext
) -> None:
    """Znak CR wewnatrz atomu jest granica akapitu, nie czescia tekstu."""
    path = make_legacy_ppt(texts=[("Pierwszy akapit.\rDrugi akapit.", True)])

    result = LegacyPptOleExtractor().extract(path, context)

    texts = [section.text for section in result.sections]
    assert "Pierwszy akapit." in texts
    assert "Drugi akapit." in texts


def test_ppt_ostrzega_o_odczycie_zapasowym(
    make_legacy_ppt: Callable[..., Path], context: ExtractionContext
) -> None:
    """Uzytkownik ma wiedziec, ze uklad prezentacji nie zostal odtworzony."""
    path = make_legacy_ppt()

    result = LegacyPptOleExtractor().extract(path, context)

    assert result.warnings
    assert any("zapasowym" in w or "formatowan" in w for w in result.warnings)


def test_ppt_zaszyfrowany_naglowek_konczy_sie_wyjatkiem(
    make_legacy_ppt: Callable[..., Path], context: ExtractionContext
) -> None:
    """Znacznik szyfrowania w strumieniu Current User zatrzymuje odczyt."""
    path = make_legacy_ppt("tajna.ppt", encrypted=True)

    with pytest.raises(PasswordProtectedError):
        LegacyPptOleExtractor().extract(path, context)


def test_ppt_atom_szyfrowania_konczy_sie_wyjatkiem(
    make_legacy_ppt: Callable[..., Path], context: ExtractionContext
) -> None:
    """Rekord DocumentEncryptionAtom w dokumencie oznacza plik chroniony."""
    path = make_legacy_ppt("tajna.ppt", encryption_atom=True)

    with pytest.raises(PasswordProtectedError):
        LegacyPptOleExtractor().extract(path, context)


def test_ppt_bez_kontenera_ole_jest_odrzucany(
    write_file: Callable[[str, bytes], Path], context: ExtractionContext
) -> None:
    """Plik z rozszerzeniem ppt, ktory nie jest OLE, nie jest prezentacja."""
    path = write_file("nie-ppt.ppt", b"To jest zwykly tekst, nie prezentacja." * 20)

    with pytest.raises(UnsupportedFormatError):
        LegacyPptOleExtractor().extract(path, context)


def test_ppt_bez_tekstu_konczy_sie_wyjatkiem(
    make_legacy_ppt: Callable[..., Path], context: ExtractionContext
) -> None:
    """Prezentacja bez atomow tekstowych to dokument pusty."""
    path = make_legacy_ppt("pusta.ppt", texts=[("   \r", True)])

    with pytest.raises(EmptyDocumentError):
        LegacyPptOleExtractor().extract(path, context)


def test_ppt_com_jest_pomijany_gdy_brak_powerpointa() -> None:
    """Adapter oparty o automatyzacje Office sam zglasza swoja niedostepnosc."""
    extractor = LegacyPptComExtractor()

    if extractor.is_available():
        assert extractor.unavailable_reason() == ""
    else:
        assert extractor.unavailable_reason()
        assert "PowerPoint" in extractor.unavailable_reason()


def test_kolejnosc_adapterow_ppt_faworyzuje_office() -> None:
    """Gdy PowerPoint jest dostepny, wygrywa on, bo zna podzial na slajdy."""
    assert LegacyPptComExtractor.priority > LegacyPptOleExtractor.priority


def test_ppt_przechodzi_przez_rejestr(
    make_legacy_ppt: Callable[..., Path], context: ExtractionContext
) -> None:
    """Plik .ppt jest rozpoznawany po strumieniu OLE i parsowany zapasowo."""
    path = make_legacy_ppt()

    info = detect_file_type(path)
    assert info.mime_type == "application/vnd.ms-powerpoint"

    result, _info = build_default_registry(office_com_enabled=False).extract(path, context)
    assert result.parser_name == "ppt_ole"
    assert POLISH_SAMPLE in result.all_text()
