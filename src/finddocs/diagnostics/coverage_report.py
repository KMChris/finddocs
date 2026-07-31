"""Raport pokrycia zbioru dokumentów.

Raport odpowiada na jedno pytanie: czy to, co uzytkownik widzi w wynikach, jest
calym zbiorem. Dlatego liczy nie tylko sukcesy, ale przede wszystkim dokumenty,
ktorych nie da sie wyszukac, i nazywa powod dla kazdego z nich.

Zasada nadrzedna: dopoki istnieje choc jeden dokument niewyszukiwalny, tekst
podsumowania nie moze sugerowac kompletnosci wyszukiwania.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from collections.abc import Iterable
from typing import TYPE_CHECKING

from finddocs.errors import FindDocsError
from finddocs.indexing.repository import from_iso
from finddocs.indexing.schema import (
    META_EMBEDDING_DIM,
    META_LAST_FULL_INDEX_AT,
    META_LAST_SCAN_AT,
    META_MODEL_KEY,
    META_SCHEMA_VERSION,
)
from finddocs.logging_setup import get_logger
from finddocs.ocr.detector import RASTERIZABLE_MIME_TYPES
from finddocs.types import CoverageReport, DocumentStatus
from finddocs.version import APP_VERSION, SCHEMA_VERSION

if TYPE_CHECKING:  # pragma: no cover - tylko dla kontroli typow
    from finddocs.indexing.service import IndexService

log = get_logger(__name__)

#: Rozszerzenia plikow, ktore potrafimy zrasteryzowac i podac silnikowi OCR.
RASTERIZABLE_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
)

#: Statusy oznaczajace, ze z dokumentu nie udalo sie wydobyc tekstu.
NO_TEXT_STATUSES: frozenset[DocumentStatus] = frozenset({DocumentStatus.EMPTY})

#: Etap zapisywany w dzienniku bledow przez warstwe OCR.
OCR_STAGE = "ocr"

#: Zapytanie liczace dokumenty, dla ktorych OCR byl potrzebny albo zostal uruchomiony.
#: Listy dopuszczalnych wartosci sa przekazywane jako parametry, nie sklejane w SQL.
_REQUIRING_OCR_SQL = """
    SELECT COUNT(*) FROM documents d
    WHERE d.used_ocr = 1
       OR EXISTS (SELECT 1 FROM error_log e WHERE e.doc_id = d.doc_id AND e.stage = ?)
       OR (
            INSTR(?, '|' || LOWER(COALESCE(d.status, '')) || '|') > 0
            AND (
                 INSTR(?, '|' || LOWER(COALESCE(d.extension, '')) || '|') > 0
              OR INSTR(?, '|' || LOWER(COALESCE(d.mime_type, '')) || '|') > 0
            )
          )
"""

#: Czytelne nazwy statusow uzywane w raportach i eksportach.
STATUS_LABELS: dict[str, str] = {
    DocumentStatus.PENDING.value: "Oczekuje na przetworzenie",
    DocumentStatus.INDEXED.value: "Zaindeksowany",
    DocumentStatus.PARTIAL.value: "Zaindeksowany częściowo",
    DocumentStatus.SKIPPED.value: "Pominięty",
    DocumentStatus.UNSUPPORTED.value: "Format nieobsługiwany",
    DocumentStatus.CORRUPTED.value: "Plik uszkodzony",
    DocumentStatus.PASSWORD_PROTECTED.value: "Zabezpieczony hasłem",
    DocumentStatus.EMPTY.value: "Brak treści do zaindeksowania",
    DocumentStatus.DOWNLOAD_FAILED.value: "Nie udało się pobrać pliku",
    DocumentStatus.ERROR.value: "Błąd przetwarzania",
    DocumentStatus.DELETED.value: "Usunięty ze źródła",
}


def status_label(status: DocumentStatus | str) -> str:
    """Czytelna nazwa statusu dokumentu."""
    key = status.value if isinstance(status, DocumentStatus) else str(status)
    return STATUS_LABELS.get(key, key)


# --- budowa raportu ------------------------------------------------------------


def build_coverage_report(index: IndexService) -> CoverageReport:
    """Buduje pelny raport pokrycia na podstawie stanu indeksu."""
    try:
        return _build(index)
    except sqlite3.DatabaseError as exc:
        raise FindDocsError(
            "Nie udało się zbudować raportu pokrycia, baza metadanych nie odpowiada.",
            cause=exc,
        ) from exc


def _build(index: IndexService) -> CoverageReport:
    repository = index.repository
    by_status = repository.status_counts()
    discovered = sum(by_status.values())

    requiring_ocr = _count_requiring_ocr(index)
    ocr_succeeded = _count_ocr_succeeded(index)
    ocr_failed = max(0, requiring_ocr - ocr_succeeded)

    vectors = (
        index.vector_store.count() if index.vector_store is not None else repository.count_vectors()
    )
    dimension = (
        index.provider.dimension
        if index.provider is not None
        else _optional_int(repository.get_meta(META_EMBEDDING_DIM))
    )
    model_key = (
        index.provider.info.model_key
        if index.provider is not None
        else repository.get_meta(META_MODEL_KEY)
    )

    report = CoverageReport(
        generated_at=_dt.datetime.now().astimezone(),
        discovered=discovered,
        indexed=by_status.get(DocumentStatus.INDEXED.value, 0),
        partial=by_status.get(DocumentStatus.PARTIAL.value, 0),
        requiring_ocr=requiring_ocr,
        ocr_succeeded=ocr_succeeded,
        ocr_failed=ocr_failed,
        skipped=by_status.get(DocumentStatus.SKIPPED.value, 0),
        unsupported=by_status.get(DocumentStatus.UNSUPPORTED.value, 0),
        corrupted=by_status.get(DocumentStatus.CORRUPTED.value, 0),
        password_protected=by_status.get(DocumentStatus.PASSWORD_PROTECTED.value, 0),
        empty=by_status.get(DocumentStatus.EMPTY.value, 0),
        download_errors=by_status.get(DocumentStatus.DOWNLOAD_FAILED.value, 0),
        other_errors=by_status.get(DocumentStatus.ERROR.value, 0),
        total_chunks=repository.count_chunks(),
        total_vectors=vectors,
        last_scan_at=from_iso(repository.get_meta(META_LAST_SCAN_AT)),
        last_full_index_at=from_iso(repository.get_meta(META_LAST_FULL_INDEX_AT)),
        schema_version=repository.get_meta_int(META_SCHEMA_VERSION, SCHEMA_VERSION),
        app_version=APP_VERSION,
        model_key=model_key,
        model_dimension=dimension,
        index_size_bytes=index.paths.index_size_bytes(),
        non_searchable=repository.non_searchable_documents(),
        by_extension=dict(repository.extension_counts()),
        by_status=dict(by_status),
        parser_errors=dict(repository.parser_error_counts()),
    )
    log.info(
        "coverage.report_built",
        discovered=report.discovered,
        indexed=report.indexed,
        non_searchable=len(report.non_searchable),
    )
    return report


def _count_requiring_ocr(index: IndexService) -> int:
    """Dokumenty, dla ktorych OCR byl potrzebny albo zostal uruchomiony.

    Liczymy trzy przeslanki: wpis o etapie OCR w dzienniku bledow, znacznik
    ``used_ocr`` na dokumencie oraz brak tekstu przy formacie, ktory da sie
    zrasteryzowac. Dokument spelniajacy kilka warunkow liczy sie raz.
    """
    params = (
        OCR_STAGE,
        _pipe_list(s.value for s in NO_TEXT_STATUSES),
        _pipe_list(RASTERIZABLE_EXTENSIONS),
        _pipe_list(RASTERIZABLE_MIME_TYPES),
    )
    return int(index.db.query_scalar(_REQUIRING_OCR_SQL, params, 0))


def _pipe_list(values: Iterable[str]) -> str:
    """Buduje liste wartosci w postaci "|a|b|c|" na potrzeby dopasowania przez INSTR.

    Dzieki temu zapytanie jest w calosci parametryzowane, mimo zmiennej liczby
    dopuszczalnych wartosci. Zadna z wartosci nie jest pusta, wiec pusty tekst
    z bazy nigdy nie pasuje.
    """
    return "|" + "|".join(sorted(values)) + "|"


def _count_ocr_succeeded(index: IndexService) -> int:
    """Dokumenty, w ktorych OCR dostarczyl tekst trafiajacy do indeksu."""
    return int(
        index.db.query_scalar(
            "SELECT COUNT(*) FROM documents WHERE used_ocr = 1 AND status IN (?, ?)",
            (DocumentStatus.INDEXED.value, DocumentStatus.PARTIAL.value),
            0,
        )
    )


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


# --- podsumowanie tekstowe -----------------------------------------------------


def non_searchable_count(report: CoverageReport) -> int:
    """Liczba dokumentów, ktorych nie da sie wyszukac.

    Liczba jest wyprowadzana ze statusow, wiec pozostaje poprawna takze wtedy,
    gdy lista szczegolowa zostala ograniczona limitem.
    """
    from_statuses = report.discovered - report.indexed - report.partial
    return max(from_statuses, len(report.non_searchable))


def _plural(count: int, one: str, few: str, many: str) -> str:
    """Dobiera polska forme rzeczownika do liczby."""
    if count == 1:
        return one
    rest_ten = count % 10
    rest_hundred = count % 100
    if 2 <= rest_ten <= 4 and not 12 <= rest_hundred <= 14:
        return few
    return many


def _documents(count: int) -> str:
    return f"{count} {_plural(count, 'dokument', 'dokumenty', 'dokumentów')}"


def _stamp(value: _dt.datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value is not None else "brak danych"


def coverage_summary_text(report: CoverageReport) -> str:
    """Czytelne podsumowanie raportu po polsku, kilka linii.

    Gdy istnieja dokumenty niewyszukiwalne, tekst wprost stwierdza, ze zbior nie
    jest kompletny, i podaje ich liczbe. Kompletnosc jest deklarowana wylacznie
    wtedy, gdy kazdy wykryty dokument trafil do indeksu.
    """
    missing = non_searchable_count(report)
    lines = [
        f"Raport pokrycia z {_stamp(report.generated_at)}, wersja aplikacji {report.app_version}.",
        f"Wykryto {_documents(report.discovered)}: zaindeksowano {report.indexed}, "
        f"częściowo {report.partial}, niewyszukiwalnych {missing}.",
        f"Fragmenty w indeksie: {report.total_chunks}, wektory: {report.total_vectors}.",
        f"OCR: wymagany dla {report.requiring_ocr}, udany dla {report.ocr_succeeded}, "
        f"nieudany dla {report.ocr_failed}.",
        f"Pominięte: {report.skipped}, nieobsługiwane: {report.unsupported}, "
        f"uszkodzone: {report.corrupted}, zabezpieczone hasłem: {report.password_protected}, "
        f"bez treści: {report.empty}.",
        f"Błędy pobierania: {report.download_errors}, inne błędy: {report.other_errors}.",
        f"Ostatnie skanowanie: {_stamp(report.last_scan_at)}. "
        f"Ostatnie pelne indeksowanie: {_stamp(report.last_full_index_at)}.",
    ]

    if report.discovered == 0:
        lines.append(
            "Indeks jest pusty, żadne źródło nie zostało jeszcze przeskanowane. "
            "Wyniki wyszukiwania beda puste, co nie oznacza braku dokumentów w zrodle."
        )
        return "\n".join(lines)

    if missing > 0:
        lines.append(
            f"UWAGA: zbiór NIE jest kompletny. {_documents(missing)} nie da sie wyszukac, "
            "więc wyniki mogą pomijać istotne treści."
        )
        lines.append(
            "Szczegóły każdego takiego dokumentu wraz z powodem znajdują się na liście "
            "dokumentów niewyszukiwalnych."
        )
    else:
        lines.append(
            "Wszystkie wykryte dokumenty sa wyszukiwalne, zbior jest kompletny "
            "w zakresie objętym skonfigurowanymi źródłami."
        )
    return "\n".join(lines)


__all__ = [
    "NO_TEXT_STATUSES",
    "OCR_STAGE",
    "RASTERIZABLE_EXTENSIONS",
    "STATUS_LABELS",
    "build_coverage_report",
    "coverage_summary_text",
    "non_searchable_count",
    "status_label",
]
