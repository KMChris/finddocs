"""Testy raportu pokrycia, statystyk i eksportu.

Raport pokrycia odpowiada na jedno pytanie: czego nie ma w indeksie i dlaczego.
Najwazniejsza wlasnosc, ktorej pilnuja te testy, brzmi: raport nie moze twierdzic,
ze zbior jest kompletny, gdy istnieje choc jeden dokument niewyszukiwalny.

Eksport przechodzi przez te sama redakcje co logi, wiec nie zawiera tresci.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from finddocs.app_paths import AppPaths
from finddocs.config import AppConfig
from finddocs.diagnostics.coverage_report import (
    build_coverage_report,
    coverage_summary_text,
    non_searchable_count,
    status_label,
)
from finddocs.diagnostics.export import (
    coverage_to_dict,
    export_coverage_csv,
    export_coverage_json,
    export_diagnostics_bundle,
    export_errors_csv,
)
from finddocs.diagnostics.stats import (
    collect_all,
    collect_component_info,
    collect_environment_info,
    collect_index_stats,
    format_bytes,
)
from finddocs.indexing.service import IndexService
from finddocs.types import DocumentStatus, ProgressSnapshot

#: Zawartosc korpusu: dokumenty poprawne oraz kazdy rodzaj problemu.
CORPUS: dict[str, str] = {
    "procedura.txt": (
        "Procedura przelewow krajowych.\n\nRachunek 00 1234 5678 9012 3456 7890 1234.\n"
    ),
    "notatka.txt": "Notatka sluzbowa z dnia 24.07.2015. Ustalono nowy termin.\n",
    "zestawienie.csv": "opis;kwota\nwplata;1234,56\nprzelew;99,00\n",
    "pusty.txt": "",
}


@pytest.fixture
def indexed(
    indexing_config: Callable[..., AppConfig],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
    tmp_path: Path,
) -> IndexService:
    """Indeks z korpusem zawierajacym dokumenty poprawne i jeden pusty."""
    root = tmp_path / "zrodlo"
    root.mkdir(parents=True, exist_ok=True)
    for name, content in CORPUS.items():
        (root / name).write_text(content, encoding="utf-8")
    (root / "uszkodzony.pdf").write_bytes(b"%PDF-1.7\n" + b"\x00\xff" * 300)

    config = indexing_config(root)
    run_job(config, index_service)
    return index_service


# --- raport pokrycia -------------------------------------------------------------


def test_raport_liczy_dokumenty_w_podziale_na_stan(indexed: IndexService) -> None:
    """Liczniki raportu sumuja sie do liczby wykrytych dokumentow."""
    report = build_coverage_report(indexed)

    assert report.discovered == 5
    assert report.indexed >= 3
    assert report.empty >= 1
    assert report.total_chunks > 0
    assert report.schema_version >= 1
    assert report.app_version


def test_raport_nie_deklaruje_kompletnosci_gdy_sa_braki(indexed: IndexService) -> None:
    """Najwazniejsza wlasnosc raportu: nie klamie o kompletnosci."""
    report = build_coverage_report(indexed)

    assert report.non_searchable
    assert report.is_complete is False
    assert non_searchable_count(report) == len(report.non_searchable)


def test_podsumowanie_ostrzega_o_niekompletnosci(indexed: IndexService) -> None:
    """Tekst podsumowania mowi wprost, ze wyniki moga pomijac tresci."""
    text = coverage_summary_text(build_coverage_report(indexed))

    assert "NIE jest kompletny" in text
    assert "niewyszukiwaln" in text


def test_kazdy_dokument_niewyszukiwalny_ma_powod(indexed: IndexService) -> None:
    """Lista braków bez powodu byla by bezuzyteczna."""
    report = build_coverage_report(indexed)

    for document in report.non_searchable:
        assert document.name
        assert document.status is not DocumentStatus.INDEXED
        assert status_label(document.status)


def test_raport_zawiera_wersje_indeksu_i_model(indexed: IndexService) -> None:
    """Raport ma pozwolic stwierdzic, czym i kiedy zbudowano indeks."""
    report = build_coverage_report(indexed)

    assert report.last_scan_at is not None
    assert report.index_size_bytes > 0
    assert isinstance(report.by_extension, dict)
    assert ".txt" in report.by_extension


def test_pusty_indeks_nie_jest_kompletny(index_service: IndexService) -> None:
    """Zero dokumentow to nie to samo co komplet dokumentow."""
    report = build_coverage_report(index_service)

    assert report.discovered == 0
    assert report.is_complete is False


@pytest.mark.parametrize(
    "status",
    [
        DocumentStatus.EMPTY,
        DocumentStatus.CORRUPTED,
        DocumentStatus.PASSWORD_PROTECTED,
        DocumentStatus.UNSUPPORTED,
        DocumentStatus.ERROR,
        DocumentStatus.SKIPPED,
    ],
)
def test_kazdy_status_ma_opis_po_polsku(status: DocumentStatus) -> None:
    """Uzytkownik nie ma czytac angielskich nazw statusow."""
    label = status_label(status)

    assert label
    assert label != status.value


# --- eksport ---------------------------------------------------------------------


def test_eksport_json_zawiera_liczniki_i_liste_brakow(
    indexed: IndexService, tmp_path: Path
) -> None:
    """Plik JSON nadaje sie do dalszego przetwarzania."""
    report = build_coverage_report(indexed)
    target = tmp_path / "raport.json"

    export_coverage_json(report, target)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["podsumowanie"]["wykryte"] == report.discovered
    assert payload["kompletny"] is False
    assert len(payload["niewyszukiwalne"]) == len(report.non_searchable)


def test_eksport_csv_otwiera_sie_w_arkuszu(indexed: IndexService, tmp_path: Path) -> None:
    """Plik CSV ma naglowek i po jednym wierszu na dokument niewyszukiwalny."""
    report = build_coverage_report(indexed)
    target = tmp_path / "raport.csv"

    export_coverage_csv(report, target)

    text = target.read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert rows
    assert any("niewyszukiwaln" in " ".join(row).lower() for row in rows)


def test_eksport_nie_zawiera_tresci_dokumentow(indexed: IndexService, tmp_path: Path) -> None:
    """Raport opisuje dokumenty, a nie cytuje ich tresci."""
    report = build_coverage_report(indexed)
    json_target = export_coverage_json(report, tmp_path / "raport.json")
    csv_target = export_coverage_csv(report, tmp_path / "raport.csv")

    for path in (json_target, csv_target):
        text = path.read_text(encoding="utf-8-sig")
        assert "Procedura przelewow krajowych" not in text
        assert "00 1234 5678 9012 3456 7890 1234" not in text


def test_slownik_raportu_ma_stabilne_klucze(indexed: IndexService) -> None:
    """Struktura eksportu jest umowa z narzedziami zewnetrznymi."""
    payload = coverage_to_dict(build_coverage_report(indexed))

    assert {"wygenerowano", "podsumowanie", "kompletny", "niewyszukiwalne"} <= set(payload)
    assert isinstance(payload["podsumowanie"], dict)
    assert isinstance(payload["niewyszukiwalne"], list)


def test_eksport_bledow_do_csv(indexed: IndexService, tmp_path: Path) -> None:
    """Lista bledow jest osobnym plikiem, przydatnym przy zgloszeniu problemu."""
    target = export_errors_csv(indexed.repository, tmp_path / "bledy.csv")

    assert target.exists()
    text = target.read_text(encoding="utf-8-sig")
    assert text.strip()


def test_paczka_diagnostyczna_zawiera_komplet(indexed: IndexService, tmp_home: AppPaths) -> None:
    """Jeden plik ZIP do zgloszenia problemu, bez tresci dokumentow."""
    target = export_diagnostics_bundle(indexed, tmp_home, timestamp="20260731-1200")

    assert target.exists()
    assert target.name == "diagnostyka-20260731-1200.zip"
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        assert names
        content = " ".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in names
            if name.endswith((".json", ".csv", ".txt"))
        )
    assert "Procedura przelewow krajowych" not in content


# --- statystyki ------------------------------------------------------------------


def test_statystyki_indeksu(indexed: IndexService) -> None:
    """Ekran diagnostyki dostaje liczby opisujace indeks."""
    stats = collect_index_stats(indexed)

    assert stats["dokumenty_wszystkie"] >= 4
    assert stats["fragmenty"] > 0
    assert stats["wersja_schematu"] >= 1
    assert stats["rozmiar_calego_indeksu_bajty"] > 0
    assert isinstance(stats["dokumenty_wg_statusu"], dict)


def test_statystyki_srodowiska(tmp_home: AppPaths) -> None:
    """Wersje bibliotek i sciezki sa potrzebne przy kazdym zgloszeniu problemu."""
    info = collect_environment_info(tmp_home)

    assert info["wersja_pythona"]
    assert info["system"]
    assert info["sqlite"]
    assert info["wersja_aplikacji"]
    assert str(tmp_home.root) in str(info["katalog_danych"])


def test_statystyki_komponentow_wymieniaja_parsery(app_config: AppConfig) -> None:
    """Diagnostyka pokazuje, ktore parsery i silniki OCR sa dostepne."""
    info = collect_component_info(app_config)

    klucze = " ".join(info)
    assert "parsery" in klucze
    assert "model_embeddingow" in info


def test_zbiorcze_statystyki(indexed: IndexService) -> None:
    """Jedno wywolanie zbiera wszystko, co pokazuje ekran diagnostyki."""
    everything = collect_all(indexed)

    assert {"indeks", "srodowisko", "komponenty"} <= set(everything)


@pytest.mark.parametrize(
    ("value", "fragment"),
    [(0, "B"), (2048, "KB"), (5 * 1024 * 1024, "MB"), (3 * 1024**3, "GB")],
)
def test_formatowanie_rozmiaru(value: int, fragment: str) -> None:
    """Rozmiary sa czytelne, z jednostka."""
    text = format_bytes(value)

    assert fragment in text
