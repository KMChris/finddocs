"""Testy parserow archiwow 7z i RAR.

Archiwa 7z buduje biblioteka py7zr, archiwa RAR reczny builder z wpisami
bez kompresji: takie wpisy rarfile czyta samodzielnie, wiec testy nie
wymagaja zainstalowanego programu unrar. Oba adaptery dziela z parserem ZIP
logike spisu tresci i limitow, sprawdzana w testach ZIP; tutaj sa przypadki
wlasciwe dla kazdego formatu.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from parser_data import POLISH_SAMPLE

from finddocs.errors import CorruptedFileError, PasswordProtectedError
from finddocs.extractors.archive import RarArchiveExtractor, SevenZipArchiveExtractor
from finddocs.extractors.base import ExtractionContext
from finddocs.extractors.registry import build_default_registry

# --- 7z ---------------------------------------------------------------------------


def test_7z_spis_zawartosci_i_zalaczniki(
    make_7z: Callable[..., Path], context: ExtractionContext
) -> None:
    """Archiwum 7z dostaje spis nazw plikow, a wpisy trafiaja do zalacznikow."""
    path = make_7z(
        entries=[
            ("raporty/styczen.txt", f"Raport za styczeń. {POLISH_SAMPLE}".encode()),
            ("umowa.csv", b"data;kwota\n2015-07-24;1234,56\n"),
        ]
    )

    result = SevenZipArchiveExtractor().extract(path, context)

    assert result.parser_name == "7z"
    listing = result.all_text()
    assert "raporty/styczen.txt" in listing
    assert "umowa.csv" in listing

    names = {attachment.name for attachment in result.attachments}
    assert names == {"raporty/styczen.txt", "umowa.csv"}
    report = next(a for a in result.attachments if a.name == "raporty/styczen.txt")
    assert POLISH_SAMPLE.encode() in report.data


def test_7z_z_haslem_daje_sam_spis(
    make_7z: Callable[..., Path], context: ExtractionContext
) -> None:
    """Zaszyfrowana tresc nie zatrzymuje archiwum: zostaje spis i ostrzezenie."""
    path = make_7z("tajne.7z", entries=[("sekret.txt", b"sekret")], password="tajne-haslo")

    result = SevenZipArchiveExtractor().extract(path, context)

    assert result.attachments == []
    assert "sekret.txt" in result.all_text()
    assert any("zaszyfrowane" in warning for warning in result.warnings)


def test_7z_zaszyfrowany_naglowek_konczy_sie_wyjatkiem(
    make_7z: Callable[..., Path], context: ExtractionContext
) -> None:
    """Archiwum z zaszyfrowanym spisem tresci to plik chroniony haslem."""
    path = make_7z(
        "tajne.7z",
        entries=[("sekret.txt", b"sekret")],
        password="tajne-haslo",
        encrypted_header=True,
    )

    with pytest.raises(PasswordProtectedError):
        SevenZipArchiveExtractor().extract(path, context)


def test_7z_uszkodzone_archiwum_konczy_sie_wyjatkiem(
    write_file: Callable[[str, bytes], Path], context: ExtractionContext
) -> None:
    """Plik z sygnatura 7z, ale bez poprawnej struktury, to plik uszkodzony."""
    path = write_file("zepsute.7z", b"7z\xbc\xaf\x27\x1c" + b"\x00" * 64)

    with pytest.raises(CorruptedFileError):
        SevenZipArchiveExtractor().extract(path, context)


def test_7z_limit_zagniezdzenia_zostawia_sam_spis(
    make_7z: Callable[..., Path], context: ExtractionContext
) -> None:
    """Bez zgody na zalaczniki archiwum daje spis tresci i ostrzezenie."""
    path = make_7z(entries=[("dokument.txt", b"Tresc.")])
    context.extract_attachments = False

    result = SevenZipArchiveExtractor().extract(path, context)

    assert result.attachments == []
    assert any("zagnieżdżenia" in warning for warning in result.warnings)


# --- RAR --------------------------------------------------------------------------


def test_rar_spis_zawartosci_i_zalaczniki(
    make_rar: Callable[..., Path], context: ExtractionContext
) -> None:
    """Wpisy bez kompresji sa czytane wprost, bez zewnetrznego narzedzia."""
    path = make_rar(
        entries=[
            ("raporty/styczen.txt", f"Raport za styczeń. {POLISH_SAMPLE}".encode()),
            ("umowa.csv", b"data;kwota\n2015-07-24;1234,56\n"),
        ]
    )

    result = RarArchiveExtractor().extract(path, context)

    assert result.parser_name == "rar"
    listing = result.all_text()
    assert "raporty/styczen.txt" in listing
    assert "umowa.csv" in listing

    names = {attachment.name for attachment in result.attachments}
    assert names == {"raporty/styczen.txt", "umowa.csv"}
    report = next(a for a in result.attachments if a.name == "raporty/styczen.txt")
    assert POLISH_SAMPLE.encode() in report.data


def test_rar_zaszyfrowany_wpis_jest_pomijany(
    make_rar: Callable[..., Path], context: ExtractionContext
) -> None:
    """Wpis chroniony haslem nie zatrzymuje archiwum, tylko zostawia ostrzezenie."""
    path = make_rar(
        entries=[("jawny.txt", b"Tresc jawna."), ("sekret.txt", b"sekret")],
        encrypted_names={"sekret.txt"},
    )

    result = RarArchiveExtractor().extract(path, context)

    names = {attachment.name for attachment in result.attachments}
    assert names == {"jawny.txt"}
    assert any("zaszyfrowany" in warning for warning in result.warnings)


def test_rar_bez_narzedzia_daje_spis_z_ostrzezeniem(
    make_rar: Callable[..., Path],
    context: ExtractionContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gdy nie ma unrar, dokument dostaje spis plikow zamiast cichego pominiecia."""
    import rarfile

    path = make_rar(entries=[("dokument.txt", b"Tresc."), ("drugi.txt", b"Tresc.")])

    def missing_tool(self: object, *args: object, **kwargs: object) -> bytes:
        raise rarfile.RarCannotExec("Cannot find working tool")

    monkeypatch.setattr(rarfile.RarFile, "read", missing_tool)

    result = RarArchiveExtractor().extract(path, context)

    assert result.attachments == []
    assert "dokument.txt" in result.all_text()
    assert sum("Brak narzędzia" in warning for warning in result.warnings) == 1


def test_rar_bez_sygnatury_konczy_sie_wyjatkiem(
    write_file: Callable[[str, bytes], Path], context: ExtractionContext
) -> None:
    """Plik z rozszerzeniem rar, ktory nie jest archiwum RAR, to plik uszkodzony."""
    path = write_file("zepsute.rar", b"to nie jest archiwum rar" * 10)

    with pytest.raises(CorruptedFileError):
        RarArchiveExtractor().extract(path, context)


def test_rar_ze_smieciami_po_sygnaturze_jest_pusty(
    write_file: Callable[[str, bytes], Path], context: ExtractionContext
) -> None:
    """Biblioteka rarfile pomija bledne bloki, wiec zostaje dokument pusty."""
    from finddocs.errors import EmptyDocumentError

    path = write_file("smieci.rar", b"Rar!\x1a\x07\x00" + b"\x00" * 64)

    with pytest.raises(EmptyDocumentError):
        RarArchiveExtractor().extract(path, context)


# --- rejestr ------------------------------------------------------------------------


def test_rejestr_kieruje_7z_i_rar_do_parserow(
    make_7z: Callable[..., Path],
    make_rar: Callable[..., Path],
    context: ExtractionContext,
) -> None:
    """Z wlaczona opcja archiwow oba formaty przechodza przez rejestr."""
    registry = build_default_registry(archives_enabled=True)

    result_7z, info_7z = registry.extract(make_7z(), context)
    assert result_7z.parser_name == "7z"
    assert info_7z.mime_type == "application/x-7z-compressed"

    result_rar, info_rar = registry.extract(make_rar(), context)
    assert result_rar.parser_name == "rar"
    assert info_rar.mime_type == "application/vnd.rar"
