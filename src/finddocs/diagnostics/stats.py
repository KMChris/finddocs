"""Statystyki indeksu, srodowiska uruchomieniowego i komponentow wymiennych.

Modul zbiera wylacznie fakty o dzialaniu aplikacji: liczby, rozmiary, wersje
bibliotek i dostepnosc komponentow. Nie siega po tresc dokumentow, fragmentow
ani po zapytania uzytkownika, wiec wynik mozna bezpiecznie pokazac na ekranie
diagnostyki i dolaczyc do zgloszenia serwisowego.
"""

from __future__ import annotations

import ctypes
import os
import platform
import sqlite3
import sys
from typing import TYPE_CHECKING, Any

from finddocs.app_paths import AppPaths
from finddocs.config import AppConfig
from finddocs.errors import CredentialStoreError, FindDocsError
from finddocs.extractors.registry import build_default_registry
from finddocs.indexing.db import check_fts5
from finddocs.indexing.schema import (
    META_EMBEDDING_DIM,
    META_LAST_FULL_INDEX_AT,
    META_LAST_SCAN_AT,
    META_MODEL_KEY,
    META_MODEL_VERSION,
    META_SCHEMA_VERSION,
)
from finddocs.logging_setup import get_logger
from finddocs.ocr import describe_engines
from finddocs.security.credentials import create_credential_store
from finddocs.security.network import get_policy
from finddocs.version import (
    APP_NAME,
    APP_VERSION,
    CHUNKING_VERSION,
    NORMALIZATION_VERSION,
    SCHEMA_VERSION,
)

if TYPE_CHECKING:  # pragma: no cover - tylko dla kontroli typow
    from finddocs.indexing.service import IndexService

log = get_logger(__name__)

#: Jednostki rozmiaru uzywane przez ``format_bytes``.
SIZE_UNITS: tuple[str, ...] = ("B", "KB", "MB", "GB", "TB", "PB")


def format_bytes(value: int) -> str:
    """Zwraca rozmiar w postaci czytelnej po polsku, na przyklad "12,3 MB".

    Separatorem dziesietnym jest przecinek, bo taka jest polska konwencja
    i taki zapis rozumie polski Excel.
    """
    if value <= 0:
        return "0 B"
    size = float(value)
    unit = 0
    while size >= 1024.0 and unit < len(SIZE_UNITS) - 1:
        size /= 1024.0
        unit += 1
    if unit == 0:
        return f"{int(size)} B"
    return f"{size:.1f}".replace(".", ",") + f" {SIZE_UNITS[unit]}"


# --- statystyki indeksu --------------------------------------------------------


def collect_index_stats(index: IndexService) -> dict[str, Any]:
    """Zbiera liczbowy obraz indeksu: dokumenty, fragmenty, wektory, rozmiary."""
    repository = index.repository
    by_status = repository.status_counts()
    by_extension = repository.extension_counts()
    ocr_documents, ocr_pages = repository.ocr_stats()

    chunks = repository.count_chunks()
    vectors_in_db = repository.count_vectors()
    vectors_in_store = index.vector_store.count() if index.vector_store is not None else 0
    average_chunk_chars = _average_chunk_chars(index)

    database_bytes = index.db.size_bytes()
    vector_bytes = _vector_index_bytes(index)

    model_key = (
        index.provider.info.model_key
        if index.provider is not None
        else repository.get_meta(META_MODEL_KEY)
    )
    dimension = (
        index.provider.dimension
        if index.provider is not None
        else _optional_int(repository.get_meta(META_EMBEDDING_DIM))
    )

    return {
        "dokumenty_wszystkie": sum(by_status.values()),
        "dokumenty_wg_statusu": dict(by_status),
        "dokumenty_wg_rozszerzenia": dict(by_extension),
        "dokumenty_z_ocr": ocr_documents,
        "strony_ocr": ocr_pages,
        "fragmenty": chunks,
        "wektory_w_bazie": vectors_in_db,
        "wektory_w_indeksie": vectors_in_store,
        "sredni_rozmiar_fragmentu_znaki": average_chunk_chars,
        "rozmiar_bazy_bajty": database_bytes,
        "rozmiar_bazy_czytelnie": format_bytes(database_bytes),
        "rozmiar_indeksu_wektorowego_bajty": vector_bytes,
        "rozmiar_indeksu_wektorowego_czytelnie": format_bytes(vector_bytes),
        "rozmiar_calego_indeksu_bajty": index.paths.index_size_bytes(),
        "wersja_schematu": repository.get_meta_int(META_SCHEMA_VERSION, SCHEMA_VERSION),
        "wersja_normalizacji": NORMALIZATION_VERSION,
        "wersja_fragmentacji": CHUNKING_VERSION,
        "model": model_key,
        "wersja_modelu": repository.get_meta(META_MODEL_VERSION),
        "wymiar_wektora": dimension,
        "semantyka_dostepna": index.semantic_available,
        "ostatnie_skanowanie": repository.get_meta(META_LAST_SCAN_AT),
        "ostatnie_pelne_indeksowanie": repository.get_meta(META_LAST_FULL_INDEX_AT),
    }


def _average_chunk_chars(index: IndexService) -> int:
    """Sredni rozmiar fragmentu w znakach. Liczona jest sama dlugosc, nie tresc."""
    raw = index.db.query_scalar("SELECT AVG(LENGTH(text)) FROM chunks", (), None)
    if raw is None:
        return 0
    try:
        return round(float(raw))
    except (TypeError, ValueError):  # pragma: no cover - SQLite zwraca liczbe albo NULL
        return 0


def _vector_index_bytes(index: IndexService) -> int:
    """Rozmiar plikow indeksu wektorowego, takze gdy indeks nie zostal otwarty."""
    if index.vector_store is not None:
        return index.vector_store.size_bytes()
    total = 0
    for path in (index.paths.vector_file, index.paths.vector_meta_file):
        if path.exists():
            total += path.stat().st_size
    return total


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


# --- srodowisko uruchomieniowe -------------------------------------------------


class _MemoryStatusEx(ctypes.Structure):
    """Odpowiednik struktury MEMORYSTATUSEX z Windows API."""

    _fields_ = (
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    )


def memory_status() -> tuple[int, int] | None:
    """Zwraca pare (pamiec calkowita, pamiec dostepna) w bajtach.

    Poza Windows zwraca None, bo GlobalMemoryStatusEx jest funkcja Windows API,
    a aplikacja nie doklada zaleznosci tylko po to, zeby pokazac liczbe w diagnostyce.
    """
    if sys.platform != "win32":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) == 0:
            return None
    except OSError:  # pragma: no cover - brak kernel32 jest sytuacja teoretyczna
        log.warning("diagnostics.memory_status_unavailable")
        return None
    return int(status.ullTotalPhys), int(status.ullAvailPhys)


def _sqlite_info() -> dict[str, Any]:
    """Wersja biblioteki SQLite i dostepnosc modulu FTS5."""
    connection = sqlite3.connect(":memory:")
    try:
        fts5 = check_fts5(connection)
    finally:
        connection.close()
    return {
        "wersja_sqlite": sqlite3.sqlite_version,
        "fts5_dostepne": fts5,
    }


def _onnxruntime_info() -> dict[str, Any]:
    """Wersja ONNX Runtime i lista providerow widocznych w tym srodowisku.

    Lista jest informacja o srodowisku, a nie o wyborze aplikacji: sesje powstaja
    zawsze z jawnej listy providerow liczacych lokalnie (CPU, DirectML, CUDA).
    """
    from finddocs.providers.onnx_local import (
        ALLOWED_EXECUTION_PROVIDERS,
        DEVICE_LABELS,
        available_devices,
    )

    try:
        import onnxruntime
    except ImportError:
        return {"wersja": None, "providery_w_srodowisku": [], "dostępny": False}
    providers = list(onnxruntime.get_available_providers())
    devices = available_devices()
    return {
        "wersja": str(getattr(onnxruntime, "__version__", "")),
        "providery_w_srodowisku": providers,
        "providery_dozwolone": ", ".join(ALLOWED_EXECUTION_PROVIDERS),
        "dostępny": True,
        "urzadzenia_dostepne": [DEVICE_LABELS[d] for d, ok in devices.items() if ok],
        "srodowisko_ma_tylko_cpu": not any(ok for d, ok in devices.items() if d != "cpu"),
    }


def _faiss_info() -> dict[str, Any]:
    """Wersja biblioteki FAISS."""
    try:
        import faiss
    except ImportError:
        return {"wersja": None, "dostępny": False}
    return {"wersja": str(getattr(faiss, "__version__", "")), "dostępny": True}


def collect_environment_info(paths: AppPaths | None = None) -> dict[str, Any]:
    """Zbiera opis srodowiska: system, Python, biblioteki, miejsce na dysku."""
    target = paths or AppPaths.default()
    memory = memory_status()
    free = target.free_space_bytes()
    total = target.total_space_bytes()

    return {
        "aplikacja": APP_NAME,
        "wersja_aplikacji": APP_VERSION,
        "wersja_pythona": platform.python_version(),
        "implementacja_pythona": platform.python_implementation(),
        "interpreter": sys.executable,
        "system": platform.system(),
        "wersja_systemu": platform.version(),
        "wydanie_systemu": platform.release(),
        "architektura": platform.machine(),
        "liczba_rdzeni_logicznych": os.cpu_count(),
        "pamiec_calkowita_bajty": memory[0] if memory else None,
        "pamiec_dostepna_bajty": memory[1] if memory else None,
        "pamiec_dostepna_czytelnie": format_bytes(memory[1]) if memory else None,
        "sqlite": _sqlite_info(),
        "onnxruntime": _onnxruntime_info(),
        "faiss": _faiss_info(),
        "katalog_danych": str(target.root),
        "wolne_miejsce_bajty": free,
        "wolne_miejsce_czytelnie": format_bytes(free),
        "pojemnosc_dysku_bajty": total,
    }


# --- komponenty wymienne -------------------------------------------------------


def _credential_store_info(paths: AppPaths) -> dict[str, Any]:
    """Rodzaj magazynu poswiadczen wybranego w tym srodowisku."""
    try:
        store = create_credential_store(paths.config_dir)
    except CredentialStoreError as exc:
        return {"rodzaj": "brak", "trwaly": False, "uwaga": exc.user_message}
    uwaga = (
        ""
        if store.persistent
        else "Magazyn działa w pamięci procesu, poświadczenia giną po zamknięciu aplikacji."
    )
    return {"rodzaj": store.name, "trwaly": store.persistent, "uwaga": uwaga}


def collect_component_info(config: AppConfig) -> dict[str, Any]:
    """Zbiera stan komponentow wymiennych: parsery, silniki OCR, siec, poswiadczenia."""
    paths = config.paths()
    registry = build_default_registry(
        office_com_enabled=config.indexing.office_com_enabled,
        archives_enabled=config.indexing.index_archives,
    )
    parsers = registry.describe()

    engines = [
        {
            "nazwa": info.name,
            "dostępny": info.available,
            "powod_niedostepnosci": info.reason,
            "wersja": info.version,
            "jezyki": list(info.languages),
            "polski_obslugiwany": info.polish_supported,
        }
        for info in describe_engines(config.ocr, paths.models_dir)
    ]

    return {
        "parsery": parsers,
        "obslugiwane_rozszerzenia": sorted(registry.supported_extensions()),
        "silniki_ocr": engines,
        "ocr_wlaczony": config.ocr.enabled,
        "ocr_wybrany_silnik": config.ocr.engine,
        "polityka_sieciowa": get_policy().describe(),
        "magazyn_poswiadczen": _credential_store_info(paths),
        "dostawca_embeddingow": config.embedding.provider,
        "model_embeddingow": config.embedding.model_key,
        "semantyka_wlaczona": config.embedding.semantic_enabled,
    }


def collect_all(index: IndexService) -> dict[str, Any]:
    """Pelny zestaw diagnostyczny: indeks, srodowisko i komponenty."""
    try:
        indeks = collect_index_stats(index)
    except sqlite3.DatabaseError as exc:
        raise FindDocsError(
            "Nie udało się odczytać statystyk indeksu z bazy metadanych.", cause=exc
        ) from exc
    return {
        "indeks": indeks,
        "srodowisko": collect_environment_info(index.paths),
        "komponenty": collect_component_info(index.config),
    }


__all__ = [
    "SIZE_UNITS",
    "collect_all",
    "collect_component_info",
    "collect_environment_info",
    "collect_index_stats",
    "format_bytes",
    "memory_status",
]
