"""Testy parsera starych skoroszytow Excel w formacie BIFF.

Biblioteka xlrd potrafi tylko czytac pliki BIFF, dlatego skoroszyt testowy jest
skladany recznie w module ``parser_data``: naglowek BOF, tablica formatow,
rekordy XF, wymiary arkusza, komorki NUMBER, INTEGER, LABEL i BOOLERR oraz EOF.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from parser_data import BIFF2_DATE_XF, DISCLAIMER, POLISH_SAMPLE, assert_polish

from finddocs.errors import CorruptedFileError, EmptyDocumentError, UnsupportedFormatError
from finddocs.extractors.base import ExtractionContext
from finddocs.extractors.xls_legacy import LegacyXlsExtractor
from finddocs.types import SupportLevel

#: Numer seryjny daty 2024-03-15 w kalendarzu Excela dla systemu 1900.
SERIAL_2024_03_15 = 45366


def _rows() -> list[list[object]]:
    """Wiersze skoroszytu testowego: naglowek oraz dwa wiersze danych roznych typow."""
    return [
        ["Opis", "Kwota", "Sztuki", "Data", "Aktywny"],
        [
            "Wpłata gotówkowa",
            1234.56,
            7,
            (SERIAL_2024_03_15, BIFF2_DATE_XF),
            True,
        ],
        [POLISH_SAMPLE, 99.5, 12, (SERIAL_2024_03_15 + 1, BIFF2_DATE_XF), False],
    ]


@pytest.fixture
def legacy_xls(make_xls: Callable[..., Path]) -> Path:
    """Skoroszyt BIFF2 z naglowkiem kolumn i danymi roznych typow."""
    return make_xls("zestawienie.xls", _rows())


def test_sekcje_arkusza(legacy_xls: Path, context: ExtractionContext) -> None:
    """Wynik zawiera sekcje arkusza, naglowek kolumn i po jednej sekcji na wiersz."""
    result = LegacyXlsExtractor().extract(legacy_xls, context)

    kinds = [section.kind for section in result.sections]
    assert kinds == ["sheet", "table_header", "table_row", "table_row"]
    assert result.sections[0].text == "Arkusz: Sheet 1"
    assert result.sections[1].text == "Opis | Kwota | Sztuki | Data | Aktywny"
    assert [section.row for section in result.sections[1:]] == [1, 2, 3]
    assert all(section.sheet == "Sheet 1" for section in result.sections)
    assert result.parser_name == "xls"
    assert result.support_level is SupportLevel.GOOD


def test_konwersja_typow_komorek(legacy_xls: Path, context: ExtractionContext) -> None:
    """Liczby, daty i wartosci logiczne sa zapisywane w czytelnej postaci."""
    result = LegacyXlsExtractor().extract(legacy_xls, context)
    rows = [section.text for section in result.sections if section.kind == "table_row"]

    assert "Kwota: 1234.56" in rows[0]
    assert "Sztuki: 7" in rows[0]
    assert "Sztuki: 7.0" not in rows[0]
    assert "Data: 2024-03-15" in rows[0]
    assert "Aktywny: prawda" in rows[0]
    assert "Data: 2024-03-16" in rows[1]
    assert "Aktywny: falsz" in rows[1]


def test_polskie_znaki_w_cp1250(legacy_xls: Path, context: ExtractionContext) -> None:
    """Tekst komorek zapisany w cp1250 jest dekodowany bez strat."""
    result = LegacyXlsExtractor().extract(legacy_xls, context)
    text = result.all_text()

    assert_polish(text)
    assert "Wpłata gotówkowa" in text


def test_metadane_skoroszytu(legacy_xls: Path, context: ExtractionContext) -> None:
    """Format BIFF niesie niewiele metadanych: liczbe arkuszy, wersje i kodowanie."""
    result = LegacyXlsExtractor().extract(legacy_xls, context)

    assert result.total_pages == 1
    assert result.metadata.page_count == 1
    assert result.metadata.extra["arkusze"] == ["Sheet 1"]
    assert result.metadata.extra["liczba_arkuszy"] == 1
    assert result.metadata.extra["wersja_biff"] == 21
    assert str(result.metadata.extra["kodowanie_zrodla"]).replace("_", "-") == "cp1250"


def test_arkusz_bez_naglowka(make_xls: Callable[..., Path], context: ExtractionContext) -> None:
    """Gdy pierwszy wiersz zawiera liczby, wartosci nie sa opisywane nazwami kolumn."""
    path = make_xls("liczby.xls", [[1, 2], [3, 4]])
    result = LegacyXlsExtractor().extract(path, context)

    kinds = [section.kind for section in result.sections]
    assert "table_header" not in kinds
    assert [section.text for section in result.sections if section.kind == "table_row"] == [
        "1 | 2",
        "3 | 4",
    ]


def test_limit_wierszy(make_xls: Callable[..., Path]) -> None:
    """Przekroczenie limitu wierszy arkusza konczy sie ostrzezeniem."""
    rows: list[list[object]] = [["Opis", "Numer"]]
    rows.extend([f"{POLISH_SAMPLE} {index}", index] for index in range(10))
    path = make_xls("duzy.xls", rows)

    result = LegacyXlsExtractor().extract(path, ExtractionContext(sheet_max_rows=4))

    assert len([s for s in result.sections if s.kind == "table_row"]) == 3
    assert any("z 11 wierszy" in warning for warning in result.warnings)


def test_pusty_skoroszyt(make_xls: Callable[..., Path], context: ExtractionContext) -> None:
    """Skoroszyt bez komorek konczy sie wyjatkiem EmptyDocumentError."""
    path = make_xls("pusty.xls", [])

    with pytest.raises(EmptyDocumentError) as info:
        LegacyXlsExtractor().extract(path, context)

    assert info.value.code == "FD-3004"


def test_nowszy_format_pod_starym_rozszerzeniem(
    sample_xlsx: Path, write_file: Callable[[str, bytes], Path], context: ExtractionContext
) -> None:
    """Plik XLSX nazwany .xls jest raportowany jako format nieobslugiwany przez ten parser."""
    path = write_file("podszywacz.xls", sample_xlsx.read_bytes())

    with pytest.raises(UnsupportedFormatError) as info:
        LegacyXlsExtractor().extract(path, context)

    assert info.value.code == "FD-3001"


def test_plik_uszkodzony(
    write_file: Callable[[str, bytes], Path], context: ExtractionContext
) -> None:
    """Dane bez naglowka BOF nie sa skoroszytem BIFF."""
    path = write_file("uszkodzony.xls", DISCLAIMER.encode("cp1250") * 20)

    with pytest.raises(CorruptedFileError) as info:
        LegacyXlsExtractor().extract(path, context)

    assert info.value.code == "FD-3002"


def test_adapter_jest_dostepny() -> None:
    """Biblioteka xlrd jest zaleznoscia obowiazkowa projektu."""
    extractor = LegacyXlsExtractor()

    assert extractor.is_available() is True
    assert extractor.unavailable_reason() == ""
    assert extractor.extensions == (".xls", ".xlt")
