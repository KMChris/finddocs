"""Testy parsera archiwow ZIP.

Parser jest rejestrowany wylacznie po wlaczeniu opcji indeksowania archiwow.
Testy sprawdzaja spis zawartosci, rozpakowywanie wpisow do zalacznikow,
limity chroniace pamiec oraz zachowanie przy plikach zaszyfrowanych
i uszkodzonych.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from parser_data import POLISH_SAMPLE

from finddocs.errors import CorruptedFileError, EmptyDocumentError
from finddocs.extractors.archive import MAX_MEMBERS, ZipArchiveExtractor
from finddocs.extractors.base import ExtractionContext
from finddocs.extractors.registry import build_default_registry


def test_spis_zawartosci_i_zalaczniki(
    make_zip: Callable[..., Path], context: ExtractionContext
) -> None:
    """Archiwum dostaje spis nazw plikow, a wpisy trafiaja do zalacznikow."""
    path = make_zip(
        entries=[
            ("raporty/styczen.txt", f"Raport za styczeń. {POLISH_SAMPLE}".encode()),
            ("umowa.csv", b"data;kwota\n2015-07-24;1234,56\n"),
        ]
    )

    result = ZipArchiveExtractor().extract(path, context)

    assert result.parser_name == "zip"
    listing = result.all_text()
    assert "raporty/styczen.txt" in listing
    assert "umowa.csv" in listing
    assert result.sections[0].heading == "Spis zawartości archiwum"

    names = {attachment.name for attachment in result.attachments}
    assert names == {"raporty/styczen.txt", "umowa.csv"}
    csv = next(a for a in result.attachments if a.name == "umowa.csv")
    assert csv.mime_type == "text/csv"
    assert b"1234,56" in csv.data


def test_katalogi_i_smieci_systemowe_sa_pomijane(
    make_zip: Callable[..., Path], context: ExtractionContext
) -> None:
    """Wpisy katalogow i pliki systemowe nie staja sie dokumentami."""
    path = make_zip(
        entries=[
            ("katalog/", b""),
            ("__MACOSX/._plik.txt", b"smieci"),
            ("katalog/.DS_Store", b"smieci"),
            ("katalog/dokument.txt", b"Wlasciwa tresc."),
        ]
    )

    result = ZipArchiveExtractor().extract(path, context)

    names = {attachment.name for attachment in result.attachments}
    assert names == {"katalog/dokument.txt"}


def test_limit_zagniezdzenia_zostawia_sam_spis(
    make_zip: Callable[..., Path], context: ExtractionContext
) -> None:
    """Bez zgody na zalaczniki archiwum daje spis tresci i ostrzezenie."""
    path = make_zip(entries=[("dokument.txt", b"Tresc.")])
    context.extract_attachments = False

    result = ZipArchiveExtractor().extract(path, context)

    assert result.attachments == []
    assert "dokument.txt" in result.all_text()
    assert any("zagnieżdżenia" in warning for warning in result.warnings)


def test_puste_archiwum_konczy_sie_wyjatkiem(
    make_zip: Callable[..., Path], context: ExtractionContext
) -> None:
    """Archiwum bez plikow to dokument pusty, a nie blad parsera."""
    path = make_zip(entries=[("katalog/", b"")])

    with pytest.raises(EmptyDocumentError):
        ZipArchiveExtractor().extract(path, context)


def test_uszkodzone_archiwum_konczy_sie_wyjatkiem(
    write_file: Callable[[str, bytes], Path], context: ExtractionContext
) -> None:
    """Plik z sygnatura ZIP, ale bez poprawnej struktury, to plik uszkodzony."""
    path = write_file("zepsute.zip", b"PK\x03\x04" + b"\x00" * 64)

    with pytest.raises(CorruptedFileError):
        ZipArchiveExtractor().extract(path, context)


def test_zaszyfrowane_wpisy_sa_pomijane_z_ostrzezeniem(
    make_protected_zip: Callable[..., Path], context: ExtractionContext
) -> None:
    """Wpis zaszyfrowany nie zatrzymuje archiwum, tylko zostawia ostrzezenie."""
    path = make_protected_zip(entries=[("raport.txt", b"Tajne dane testowe.")])

    result = ZipArchiveExtractor().extract(path, context)

    assert result.attachments == []
    assert any("zaszyfrowany" in warning for warning in result.warnings)
    assert "raport.txt" in result.all_text()


def test_wpis_ponad_limit_rozmiaru_jest_pomijany(
    make_zip: Callable[..., Path],
) -> None:
    """Wpis wiekszy niz limit pliku nie trafia do pamieci."""
    path = make_zip(entries=[("duzy.txt", b"x" * 4096), ("maly.txt", b"Krotka tresc dokumentu.")])
    limited = ExtractionContext(max_bytes=1024, max_chars=200_000)

    result = ZipArchiveExtractor().extract(path, limited)

    names = {attachment.name for attachment in result.attachments}
    assert names == {"maly.txt"}
    assert any("limit rozmiaru" in warning for warning in result.warnings)


def test_limit_liczby_wpisow(make_zip: Callable[..., Path], context: ExtractionContext) -> None:
    """Powyzej limitu wpisow reszta jest pomijana z ostrzezeniem."""
    entries = [(f"plik-{index:03}.txt", b"tresc") for index in range(MAX_MEMBERS + 5)]
    path = make_zip(entries=entries)

    result = ZipArchiveExtractor().extract(path, context)

    assert len(result.attachments) == MAX_MEMBERS
    assert any("więcej plików niż limit" in warning for warning in result.warnings)


def test_rejestr_bez_opcji_nie_obsluguje_zip(
    make_zip: Callable[..., Path], context: ExtractionContext
) -> None:
    """Domyslny rejestr nie ma parsera ZIP, z opcja go rejestruje."""
    path = make_zip(entries=[("dokument.txt", b"Tresc.")])
    from finddocs.errors import UnsupportedFormatError

    with pytest.raises(UnsupportedFormatError):
        build_default_registry().extract(path, context)

    result, info = build_default_registry(archives_enabled=True).extract(path, context)
    assert result.parser_name == "zip"
    assert info.mime_type == "application/zip"
    assert info.is_container is True
