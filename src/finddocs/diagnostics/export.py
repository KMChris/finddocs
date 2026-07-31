"""Eksport raportow diagnostycznych do plikow.

Formaty sa dobrane pod polskiego odbiorce: CSV ma separator srednika i kodowanie
utf-8-sig, dzieki czemu Excel otwiera plik bez kreatora importu i bez rozsypanych
polskich znakow. JSON sluzy do przetwarzania maszynowego.

Zawartosc eksportow jest ograniczona do faktow o przetwarzaniu: nazwy plikow,
sciezki logiczne, statusy, kody bledow, liczby i wersje. Tresc dokumentow ani
fragmentow nie trafia do zadnego pliku, a pola tekstowe pochodzace z wyjatkow
przechodza przez redakcje.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import json
import sqlite3
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from finddocs.app_paths import AppPaths
from finddocs.diagnostics.coverage_report import (
    build_coverage_report,
    coverage_summary_text,
    non_searchable_count,
    status_label,
)
from finddocs.diagnostics.stats import collect_all, format_bytes
from finddocs.errors import FindDocsError
from finddocs.logging_setup import get_logger
from finddocs.security.redaction import redact_text
from finddocs.types import CoverageReport

if TYPE_CHECKING:  # pragma: no cover - tylko dla kontroli typow
    from finddocs.indexing.repository import Repository
    from finddocs.indexing.service import IndexService

log = get_logger(__name__)

#: Separator kolumn. Polski Excel oczekuje srednika.
CSV_DELIMITER = ";"

#: Kodowanie ze znacznikiem BOM, zeby Excel rozpoznal UTF-8.
CSV_ENCODING = "utf-8-sig"

#: Zakonczenie wiersza wymagane przez Excel.
CSV_LINE_TERMINATOR = "\r\n"

#: Ile bajtow konca pliku logu trafia do paczki diagnostycznej.
MAX_LOG_BYTES = 8 * 1024 * 1024

#: Nazwy plikow w paczce diagnostycznej.
BUNDLE_COVERAGE_JSON = "raport-pokrycia.json"
BUNDLE_COVERAGE_CSV = "raport-pokrycia.csv"
BUNDLE_ERRORS_CSV = "bledy.csv"
BUNDLE_ENVIRONMENT_JSON = "srodowisko.json"
BUNDLE_LOG = "finddocs.log"


# --- pomocnicze ----------------------------------------------------------------


def _json_default(value: Any) -> str:
    """Zamienia typy nieobslugiwane przez JSON na czytelny tekst."""
    if isinstance(value, _dt.datetime | _dt.date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set | frozenset):
        return ", ".join(sorted(str(item) for item in value))
    return str(value)


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)


def _write_text(path: Path, text: str, encoding: str) -> Path:
    """Zapisuje plik, tworzac katalog docelowy. Tlumaczy bledy wejscia i wyjscia."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=encoding, newline="")
    except OSError as exc:
        raise FindDocsError(
            f"Nie udalo sie zapisac pliku raportu {path.name}. Sprawdz uprawnienia "
            "do katalogu i ilosc wolnego miejsca.",
            details={"sciezka": str(path)},
            cause=exc,
        ) from exc
    return path


def _new_csv_writer(buffer: io.StringIO) -> Any:
    return csv.writer(
        buffer,
        delimiter=CSV_DELIMITER,
        lineterminator=CSV_LINE_TERMINATOR,
        quoting=csv.QUOTE_MINIMAL,
    )


def _safe(value: str | None) -> str:
    """Przygotowuje tekst pochodzacy z wyjatku do zapisu w raporcie."""
    return redact_text(value) if value else ""


def _stamp(value: _dt.datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _yes_no(value: bool) -> str:
    return "tak" if value else "nie"


# --- raport pokrycia -----------------------------------------------------------


def coverage_to_dict(report: CoverageReport) -> dict[str, Any]:
    """Zamienia raport pokrycia na slownik z polskimi kluczami."""
    return {
        "wygenerowano": _stamp(report.generated_at),
        "wersja_aplikacji": report.app_version,
        "wersja_schematu": report.schema_version,
        "model": report.model_key,
        "wymiar_wektora": report.model_dimension,
        "podsumowanie": {
            "wykryte": report.discovered,
            "zaindeksowane": report.indexed,
            "czesciowo_zaindeksowane": report.partial,
            "wymagajace_ocr": report.requiring_ocr,
            "ocr_udany": report.ocr_succeeded,
            "ocr_nieudany": report.ocr_failed,
            "pominiete": report.skipped,
            "nieobslugiwane": report.unsupported,
            "uszkodzone": report.corrupted,
            "zabezpieczone_haslem": report.password_protected,
            "bez_tresci": report.empty,
            "bledy_pobierania": report.download_errors,
            "inne_bledy": report.other_errors,
            "niewyszukiwalne": non_searchable_count(report),
        },
        "indeks": {
            "fragmenty": report.total_chunks,
            "wektory": report.total_vectors,
            "rozmiar_bajty": report.index_size_bytes,
            "rozmiar_czytelnie": format_bytes(report.index_size_bytes),
            "ostatnie_skanowanie": _stamp(report.last_scan_at),
            "ostatnie_pelne_indeksowanie": _stamp(report.last_full_index_at),
        },
        "wg_statusu": dict(report.by_status),
        "wg_rozszerzenia": dict(report.by_extension),
        "bledy_parserow": dict(report.parser_errors),
        "kompletny": report.is_complete,
        "opis": coverage_summary_text(report),
        "niewyszukiwalne": [
            {
                "identyfikator": doc.doc_id,
                "nazwa": doc.name,
                "sciezka_logiczna": doc.logical_path,
                "rozszerzenie": doc.extension,
                "status": doc.status.value,
                "status_opis": status_label(doc.status),
                "kod_bledu": doc.error_code or "",
                "komunikat": _safe(doc.error_message),
            }
            for doc in report.non_searchable
        ],
    }


def _coverage_json_text(report: CoverageReport) -> str:
    return _dumps(coverage_to_dict(report))


def _coverage_csv_text(report: CoverageReport) -> str:
    """Buduje tekst CSV z dwiema sekcjami: podsumowaniem i lista problemow."""
    buffer = io.StringIO()
    writer = _new_csv_writer(buffer)

    writer.writerow(["Podsumowanie raportu pokrycia"])
    writer.writerow(["Wskaznik", "Wartosc"])
    summary: list[tuple[str, object]] = [
        ("Data wygenerowania", _stamp(report.generated_at)),
        ("Wersja aplikacji", report.app_version),
        ("Wersja schematu", report.schema_version),
        ("Model embeddingow", report.model_key or "brak"),
        ("Wymiar wektora", report.model_dimension if report.model_dimension else "brak"),
        ("Dokumenty wykryte", report.discovered),
        ("Dokumenty zaindeksowane", report.indexed),
        ("Dokumenty zaindeksowane czesciowo", report.partial),
        ("Dokumenty wymagajace OCR", report.requiring_ocr),
        ("OCR zakonczony powodzeniem", report.ocr_succeeded),
        ("OCR zakonczony niepowodzeniem", report.ocr_failed),
        ("Dokumenty pominiete", report.skipped),
        ("Formaty nieobslugiwane", report.unsupported),
        ("Pliki uszkodzone", report.corrupted),
        ("Pliki zabezpieczone haslem", report.password_protected),
        ("Pliki bez tresci", report.empty),
        ("Bledy pobierania", report.download_errors),
        ("Inne bledy przetwarzania", report.other_errors),
        ("Dokumenty niewyszukiwalne (razem)", non_searchable_count(report)),
        ("Fragmenty w indeksie", report.total_chunks),
        ("Wektory w indeksie", report.total_vectors),
        ("Rozmiar indeksu (bajty)", report.index_size_bytes),
        ("Rozmiar indeksu", format_bytes(report.index_size_bytes)),
        ("Ostatnie skanowanie", _stamp(report.last_scan_at)),
        ("Ostatnie pelne indeksowanie", _stamp(report.last_full_index_at)),
        ("Zbior kompletny", _yes_no(report.is_complete)),
    ]
    for name, value in summary:
        writer.writerow([name, value])

    writer.writerow([])
    writer.writerow(["Dokumenty niewyszukiwalne"])
    writer.writerow(
        [
            "Identyfikator",
            "Nazwa pliku",
            "Sciezka logiczna",
            "Rozszerzenie",
            "Status",
            "Opis statusu",
            "Kod bledu",
            "Komunikat",
        ]
    )
    for doc in report.non_searchable:
        writer.writerow(
            [
                doc.doc_id,
                doc.name,
                doc.logical_path,
                doc.extension,
                doc.status.value,
                status_label(doc.status),
                doc.error_code or "",
                _safe(doc.error_message),
            ]
        )
    return buffer.getvalue()


def export_coverage_json(report: CoverageReport, path: Path) -> Path:
    """Zapisuje raport pokrycia w formacie JSON. Zwraca sciezke pliku."""
    result = _write_text(path, _coverage_json_text(report), "utf-8")
    log.info("diagnostics.coverage_json_exported", path=str(result))
    return result


def export_coverage_csv(report: CoverageReport, path: Path) -> Path:
    """Zapisuje raport pokrycia w formacie CSV dla polskiego Excela."""
    result = _write_text(path, _coverage_csv_text(report), CSV_ENCODING)
    log.info("diagnostics.coverage_csv_exported", path=str(result))
    return result


# --- dziennik bledow -----------------------------------------------------------


def _errors_csv_text(repository: Repository, limit: int) -> str:
    """Buduje tekst CSV z ostatnimi wpisami dziennika bledow."""
    try:
        rows = repository.recent_errors(limit)
    except sqlite3.DatabaseError as exc:
        raise FindDocsError(
            "Nie udalo sie odczytac dziennika bledow z bazy metadanych.", cause=exc
        ) from exc

    buffer = io.StringIO()
    writer = _new_csv_writer(buffer)
    writer.writerow(
        [
            "Data",
            "Zrodlo",
            "Identyfikator dokumentu",
            "Nazwa pliku",
            "Etap",
            "Kod bledu",
            "Wyjatek",
            "Komunikat",
            "Mozna ponowic",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["created_at"] or "",
                row["source_id"] or "",
                row["doc_id"] if row["doc_id"] is not None else "",
                row["file_name"] or "",
                row["stage"],
                row["code"],
                _safe(row["exception"]),
                _safe(row["message"]),
                _yes_no(bool(row["retryable"])),
            ]
        )
    return buffer.getvalue()


def export_errors_csv(repository: Repository, path: Path, limit: int = 5000) -> Path:
    """Zapisuje ostatnie wpisy dziennika bledow do pliku CSV."""
    result = _write_text(path, _errors_csv_text(repository, limit), CSV_ENCODING)
    log.info("diagnostics.errors_csv_exported", path=str(result), limit=limit)
    return result


# --- paczka diagnostyczna ------------------------------------------------------


def _latest_log_file(paths: AppPaths) -> Path | None:
    """Najswiezszy plik logu, takze po rotacji rozmiarowej."""
    if not paths.logs_dir.exists():
        return None
    candidates = [p for p in paths.logs_dir.glob("finddocs.log*") if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _log_tail(path: Path) -> bytes:
    """Koncowka pliku logu, obcieta do pelnych wierszy."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > MAX_LOG_BYTES:
                handle.seek(size - MAX_LOG_BYTES)
                data = handle.read()
                _, separator, rest = data.partition(b"\n")
                return rest if separator else data
            return handle.read()
    except OSError:
        log.warning("diagnostics.log_unreadable")
        return b""


def default_bundle_timestamp() -> str:
    """Znacznik czasu uzywany w nazwie paczki diagnostycznej."""
    return _dt.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def export_diagnostics_bundle(
    index: IndexService,
    paths: AppPaths,
    timestamp: str | None = None,
) -> Path:
    """Tworzy paczke ZIP z kompletem informacji diagnostycznych.

    Paczka zawiera raport pokrycia (JSON i CSV), dziennik bledow (CSV), opis
    srodowiska i komponentow (JSON) oraz koncowke biezacego pliku logu. Nie ma
    w niej tresci dokumentow ani fragmentow.

    Argument ``timestamp`` pozwala ustalic nazwe pliku z gory, dzieki czemu
    wynik jest powtarzalny w testach. Wartosc None oznacza biezacy czas.
    """
    stamp = timestamp or default_bundle_timestamp()
    report = build_coverage_report(index)
    environment = _dumps(collect_all(index))
    coverage_json = _coverage_json_text(report)
    coverage_csv = _coverage_csv_text(report)
    errors_csv = _errors_csv_text(index.repository, 5000)
    log_file = _latest_log_file(paths)

    target = paths.reports_dir / f"diagnostyka-{stamp}.zip"
    try:
        paths.reports_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(BUNDLE_COVERAGE_JSON, coverage_json.encode("utf-8"))
            archive.writestr(BUNDLE_COVERAGE_CSV, coverage_csv.encode(CSV_ENCODING))
            archive.writestr(BUNDLE_ERRORS_CSV, errors_csv.encode(CSV_ENCODING))
            archive.writestr(BUNDLE_ENVIRONMENT_JSON, environment.encode("utf-8"))
            if log_file is not None:
                archive.writestr(BUNDLE_LOG, _log_tail(log_file))
    except OSError as exc:
        raise FindDocsError(
            "Nie udalo sie utworzyc paczki diagnostycznej. Sprawdz uprawnienia "
            "do katalogu raportow i ilosc wolnego miejsca.",
            details={"sciezka": str(target)},
            cause=exc,
        ) from exc

    log.info(
        "diagnostics.bundle_created",
        path=str(target),
        bytes=target.stat().st_size,
        log_included=log_file is not None,
    )
    return target


__all__ = [
    "BUNDLE_COVERAGE_CSV",
    "BUNDLE_COVERAGE_JSON",
    "BUNDLE_ENVIRONMENT_JSON",
    "BUNDLE_ERRORS_CSV",
    "BUNDLE_LOG",
    "CSV_DELIMITER",
    "CSV_ENCODING",
    "MAX_LOG_BYTES",
    "coverage_to_dict",
    "default_bundle_timestamp",
    "export_coverage_csv",
    "export_coverage_json",
    "export_diagnostics_bundle",
    "export_errors_csv",
]
