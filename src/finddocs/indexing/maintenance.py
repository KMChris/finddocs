"""Konserwacja indeksu: kontrola spojnosci, kopia zapasowa, przebudowa, kompaktacja.

Zasada: nie usuwamy dzialajacego indeksu, zanim nowy nie bedzie gotowy, o ile
pozwala na to miejsce na dysku. Przebudowa buduje nowy plik obok starego
i podmienia go dopiero na koncu.
"""

from __future__ import annotations

import datetime as _dt
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from finddocs.app_paths import AppPaths
from finddocs.errors import StorageSpaceError
from finddocs.indexing.db import Database
from finddocs.indexing.repository import Repository
from finddocs.indexing.schema import (
    META_EMBEDDING_DIM,
    META_INDEX_COMPAT,
    META_MODEL_KEY,
    META_MODEL_VERSION,
    META_SCHEMA_VERSION,
    META_VECTOR_COMPAT,
)
from finddocs.indexing.vector import VectorStore
from finddocs.logging_setup import get_logger
from finddocs.types import CancellationToken, DocumentStatus
from finddocs.version import SCHEMA_VERSION

log = get_logger(__name__)

#: Margines bezpieczenstwa przy sprawdzaniu miejsca na dysku.
SPACE_SAFETY_FACTOR = 1.3


@dataclass(slots=True)
class ConsistencyReport:
    """Wynik kontroli spojnosci indeksu."""

    checked_at: _dt.datetime
    database_ok: bool
    fts_ok: bool
    vector_ok: bool
    schema_version: int
    expected_schema_version: int
    documents: int
    chunks: int
    vectors_in_db: int
    vectors_in_store: int
    orphan_chunks: int
    documents_without_chunks: int
    chunks_without_vectors: int
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_healthy(self) -> bool:
        return self.database_ok and self.fts_ok and self.vector_ok and not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "sprawdzono": self.checked_at.isoformat(),
            "baza_ok": self.database_ok,
            "fts_ok": self.fts_ok,
            "wektory_ok": self.vector_ok,
            "wersja_schematu": self.schema_version,
            "oczekiwana_wersja_schematu": self.expected_schema_version,
            "dokumenty": self.documents,
            "fragmenty": self.chunks,
            "wektory_w_bazie": self.vectors_in_db,
            "wektory_w_indeksie": self.vectors_in_store,
            "osierocone_fragmenty": self.orphan_chunks,
            "dokumenty_bez_fragmentow": self.documents_without_chunks,
            "fragmenty_bez_wektorow": self.chunks_without_vectors,
            "problemy": self.problems,
            "ostrzezenia": self.warnings,
        }


def check_consistency(
    db: Database, repository: Repository, vector_store: VectorStore | None
) -> ConsistencyReport:
    """Sprawdza spojnosc bazy, indeksu FTS i indeksu wektorowego."""
    problems: list[str] = []
    warnings: list[str] = []

    db_problems = db.integrity_check()
    if db_problems:
        problems.extend(f"baza: {p}" for p in db_problems[:5])

    fts_problems = db.fts_integrity_check()
    if fts_problems:
        problems.extend(f"fts: {p}" for p in fts_problems[:5])

    documents = int(db.query_scalar("SELECT COUNT(*) FROM documents", (), 0))
    chunks = repository.count_chunks()
    vectors_in_db = repository.count_vectors()
    orphans = int(
        db.query_scalar(
            "SELECT COUNT(*) FROM chunks c LEFT JOIN documents d ON d.doc_id = c.doc_id "
            "WHERE d.doc_id IS NULL",
            (),
            0,
        )
    )
    without_chunks = int(
        db.query_scalar(
            "SELECT COUNT(*) FROM documents WHERE status = ? AND chunk_count = 0",
            (DocumentStatus.INDEXED.value,),
            0,
        )
    )
    chunks_without_vectors = int(
        db.query_scalar("SELECT COUNT(*) FROM chunks WHERE has_vector = 0", (), 0)
    )

    if orphans:
        problems.append(f"Znaleziono {orphans} fragmentow bez dokumentu nadrzednego.")
    if without_chunks:
        warnings.append(
            f"{without_chunks} dokumentow ma status 'zaindeksowany', ale nie ma fragmentow."
        )

    vectors_in_store = 0
    vector_ok = True
    if vector_store is not None and vector_store.is_open:
        vectors_in_store = vector_store.count()
        if abs(vectors_in_store - vectors_in_db) > 0:
            vector_ok = False
            warnings.append(
                f"Indeks wektorowy ma {vectors_in_store} wektorow, "
                f"a baza oznacza {vectors_in_db} fragmentow jako zwektoryzowane."
            )
        if vector_store.needs_compaction():
            warnings.append(
                "Indeks wektorowy zawiera duzo usunietych wpisow. Zalecana kompaktacja."
            )
    elif chunks_without_vectors:
        warnings.append(
            f"{chunks_without_vectors} fragmentow nie ma wektora. "
            "Wyszukiwanie semantyczne moze byc niepelne."
        )

    schema_version = repository.get_meta_int(META_SCHEMA_VERSION, 0)
    if schema_version != SCHEMA_VERSION:
        problems.append(
            f"Wersja schematu w bazie to {schema_version}, aplikacja oczekuje {SCHEMA_VERSION}."
        )

    return ConsistencyReport(
        checked_at=_dt.datetime.now().astimezone(),
        database_ok=not db_problems,
        fts_ok=not fts_problems,
        vector_ok=vector_ok,
        schema_version=schema_version,
        expected_schema_version=SCHEMA_VERSION,
        documents=documents,
        chunks=chunks,
        vectors_in_db=vectors_in_db,
        vectors_in_store=vectors_in_store,
        orphan_chunks=orphans,
        documents_without_chunks=without_chunks,
        chunks_without_vectors=chunks_without_vectors,
        problems=problems,
        warnings=warnings,
    )


def compatibility_state(
    repository: Repository,
    *,
    index_compat_hash: str,
    vector_compat_hash: str,
) -> dict[str, bool]:
    """Sprawdza, czy istniejacy indeks jest zgodny z biezaca konfiguracja."""
    stored_index = repository.get_meta(META_INDEX_COMPAT)
    stored_vector = repository.get_meta(META_VECTOR_COMPAT)
    return {
        "fts_zgodny": stored_index is None or stored_index == index_compat_hash,
        "wektory_zgodne": stored_vector is None or stored_vector == vector_compat_hash,
        "pierwszy_start": stored_index is None,
    }


def record_compatibility(
    repository: Repository,
    *,
    index_compat_hash: str,
    vector_compat_hash: str,
    model_key: str | None,
    model_version: str | None,
    dimension: int | None,
) -> None:
    """Zapisuje w indeksie informacje o konfiguracji, ktora go utworzyla."""
    repository.set_meta_many(
        {
            META_INDEX_COMPAT: index_compat_hash,
            META_VECTOR_COMPAT: vector_compat_hash,
            META_MODEL_KEY: model_key,
            META_MODEL_VERSION: model_version,
            META_EMBEDDING_DIM: str(dimension) if dimension else None,
            META_SCHEMA_VERSION: str(SCHEMA_VERSION),
        }
    )


# --- kopia zapasowa i przywracanie ----------------------------------------


def backup_index(paths: AppPaths, *, label: str | None = None) -> Path:
    """Tworzy kopie indeksu w katalogu kopii zapasowych. Zwraca sciezke kopii."""
    stamp = label or _dt.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    target = paths.backup_dir / f"index-{stamp}"
    if target.exists():
        raise StorageSpaceError(f"Katalog kopii {target} juz istnieje.")

    source_size = paths.index_size_bytes()
    free = paths.free_space_bytes()
    if free < source_size * SPACE_SAFETY_FACTOR:
        raise StorageSpaceError(
            "Za malo miejsca na dysku, zeby wykonac kopie indeksu. "
            f"Potrzeba okolo {_mb(source_size * SPACE_SAFETY_FACTOR)} MB, "
            f"dostepne {_mb(free)} MB."
        )

    target.mkdir(parents=True, exist_ok=True)
    for item in paths.index_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, target / item.name)
    log.info("index.backup_created", target=str(target), bytes=source_size)
    return target


def list_backups(paths: AppPaths) -> list[dict[str, Any]]:
    """Lista dostepnych kopii indeksu."""
    if not paths.backup_dir.exists():
        return []
    result: list[dict[str, Any]] = []
    for entry in sorted(paths.backup_dir.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        size = sum(p.stat().st_size for p in entry.rglob("*") if p.is_file())
        result.append(
            {
                "nazwa": entry.name,
                "sciezka": str(entry),
                "rozmiar_bajty": size,
                "utworzono": _dt.datetime.fromtimestamp(entry.stat().st_mtime)
                .astimezone()
                .isoformat(),
            }
        )
    return result


def restore_backup(paths: AppPaths, backup_name: str) -> Path:
    """Przywraca indeks z kopii. Biezacy indeks jest najpierw odkladany na bok."""
    source = paths.backup_dir / backup_name
    if not source.is_dir():
        raise StorageSpaceError(f"Nie znaleziono kopii o nazwie {backup_name}.")

    stamp = _dt.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    aside = paths.backup_dir / f"przed-przywroceniem-{stamp}"
    if paths.index_dir.exists() and any(paths.index_dir.iterdir()):
        aside.mkdir(parents=True, exist_ok=True)
        for item in paths.index_dir.iterdir():
            if item.is_file():
                shutil.move(str(item), str(aside / item.name))

    paths.index_dir.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_file():
            shutil.copy2(item, paths.index_dir / item.name)
    log.info("index.restored", source=str(source), aside=str(aside))
    return paths.index_dir


# --- przebudowa i kompaktacja ---------------------------------------------


def compact_vectors(
    repository: Repository,
    vector_store: VectorStore,
    *,
    batch: int = 512,
    cancel: CancellationToken | None = None,
) -> int:
    """Buduje indeks wektorowy od nowa, usuwajac nagrobki. Zwraca liczbe wektorow."""
    active_ids: list[int] = []
    vectors: list[np.ndarray] = []
    last = 0
    while True:
        if cancel is not None:
            cancel.raise_if_cancelled()
        rows = repository.db.query_all(
            "SELECT chunk_id FROM chunks WHERE has_vector = 1 AND chunk_id > ? "
            "ORDER BY chunk_id LIMIT ?",
            (last, batch),
        )
        if not rows:
            break
        last = int(rows[-1]["chunk_id"])
        for row in rows:
            chunk_id = int(row["chunk_id"])
            vector = vector_store.reconstruct(chunk_id)
            if vector is None:
                repository.db.execute(
                    "UPDATE chunks SET has_vector = 0 WHERE chunk_id = ?", (chunk_id,)
                )
                continue
            active_ids.append(chunk_id)
            vectors.append(vector)

    matrix = (
        np.vstack(vectors) if vectors else np.zeros((0, vector_store.dimension), dtype="float32")
    )
    vector_store.compact(active_ids, matrix)
    return len(active_ids)


def mark_all_for_reindex(repository: Repository, *, only_vectors: bool = False) -> int:
    """Oznacza dokumenty do ponownego przetworzenia. Zwraca liczbe dokumentow."""
    db = repository.db
    with db.transaction():
        if only_vectors:
            db.execute("UPDATE chunks SET has_vector = 0")
            db.execute(
                "UPDATE documents SET vector_indexed = 0, model_key = NULL WHERE status IN (?, ?)",
                (DocumentStatus.INDEXED.value, DocumentStatus.PARTIAL.value),
            )
            count = int(
                db.query_scalar(
                    "SELECT COUNT(*) FROM documents WHERE status IN (?, ?)",
                    (DocumentStatus.INDEXED.value, DocumentStatus.PARTIAL.value),
                    0,
                )
            )
        else:
            db.execute(
                "UPDATE documents SET status = ?, change_key = NULL, "
                "fts_indexed = 0, vector_indexed = 0 WHERE attachment_of IS NULL",
                (DocumentStatus.PENDING.value,),
            )
            db.execute("DELETE FROM chunks")
            count = int(db.query_scalar("SELECT COUNT(*) FROM documents", (), 0))
    return count


def estimate_rebuild_space(paths: AppPaths) -> dict[str, int]:
    """Szacuje miejsce potrzebne na przebudowe indeksu."""
    current = paths.index_size_bytes()
    return {
        "biezacy_indeks_bajty": current,
        "wymagane_wolne_bajty": int(current * SPACE_SAFETY_FACTOR),
        "dostepne_bajty": paths.free_space_bytes(),
    }


def ensure_free_space(paths: AppPaths, required_bytes: int) -> None:
    """Rzuca wyjatek, gdy na dysku brakuje miejsca."""
    free = paths.free_space_bytes()
    if free < required_bytes:
        raise StorageSpaceError(
            f"Za malo miejsca na dysku. Potrzeba {_mb(required_bytes)} MB, "
            f"dostepne {_mb(free)} MB.",
            details={"required": required_bytes, "available": free},
        )


def _mb(value: float) -> int:
    return int(value / (1024 * 1024))


__all__ = [
    "SPACE_SAFETY_FACTOR",
    "ConsistencyReport",
    "backup_index",
    "check_consistency",
    "compact_vectors",
    "compatibility_state",
    "ensure_free_space",
    "estimate_rebuild_space",
    "list_backups",
    "mark_all_for_reindex",
    "record_compatibility",
    "restore_backup",
]
