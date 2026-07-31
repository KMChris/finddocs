"""Fasada indeksu: otwarcie bazy, migracje, kontrola zgodnosci, dostep do warstw.

``IndexService`` jest jedynym obiektem, ktory warstwy wyzsze musza znac, zeby
korzystac z indeksu. Trzyma polaczenie z baza, repozytorium metadanych, indeks
pelnotekstowy, indeks wektorowy i dostawce embeddingow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from finddocs.app_paths import AppPaths
from finddocs.config import AppConfig
from finddocs.errors import IndexIncompatibleError, ProviderError
from finddocs.indexing.db import Database, check_fts5
from finddocs.indexing.fts import FtsIndex
from finddocs.indexing.maintenance import (
    ConsistencyReport,
    check_consistency,
    compatibility_state,
    record_compatibility,
)
from finddocs.indexing.migrations import migrate
from finddocs.indexing.repository import Repository
from finddocs.indexing.schema import (
    META_LAST_FULL_INDEX_AT,
    META_LAST_SCAN_AT,
)
from finddocs.indexing.vector import VectorStore
from finddocs.indexing.writer import IndexWriter
from finddocs.logging_setup import get_logger
from finddocs.providers.base import EmbeddingProvider
from finddocs.version import SCHEMA_VERSION

log = get_logger(__name__)


@dataclass(slots=True)
class IndexStatus:
    """Stan indeksu pokazywany w interfejsie."""

    exists: bool
    schema_version: int
    documents: int
    indexed_documents: int
    chunks: int
    vectors: int
    model_key: str | None
    model_dimension: int | None
    fts_compatible: bool
    vector_compatible: bool
    semantic_available: bool
    last_scan_at: str | None
    last_full_index_at: str | None
    size_bytes: int
    free_space_bytes: int
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "istnieje": self.exists,
            "wersja_schematu": self.schema_version,
            "dokumenty": self.documents,
            "dokumenty_zaindeksowane": self.indexed_documents,
            "fragmenty": self.chunks,
            "wektory": self.vectors,
            "model": self.model_key,
            "wymiar": self.model_dimension,
            "fts_zgodny": self.fts_compatible,
            "wektory_zgodne": self.vector_compatible,
            "semantyka_dostepna": self.semantic_available,
            "ostatnie_skanowanie": self.last_scan_at,
            "ostatnie_pelne_indeksowanie": self.last_full_index_at,
            "rozmiar_bajty": self.size_bytes,
            "wolne_miejsce_bajty": self.free_space_bytes,
            "uwagi": self.notes,
        }


class IndexService:
    """Zarzadza cyklem zycia indeksu."""

    def __init__(self, config: AppConfig, paths: AppPaths | None = None) -> None:
        self.config = config
        self.paths = (paths or config.paths()).ensure()
        self.db = Database(self.paths.database_file)
        self.repository = Repository(self.db)
        self.fts = FtsIndex(self.db)
        self.vector_store: VectorStore | None = None
        self.provider: EmbeddingProvider | None = None
        self._writer: IndexWriter | None = None
        self._notes: list[str] = []
        self._rebuild_required = False
        self._opened = False

    # --- otwieranie -------------------------------------------------------

    def open(self, *, load_provider: bool = True, allow_rebuild_prompt: bool = True) -> None:
        """Otwiera baze, wykonuje migracje i inicjalizuje warstwy."""
        if self._opened:
            return
        conn = self.db.connection
        if not check_fts5(conn):
            raise IndexIncompatibleError(
                "Biblioteka SQLite w tym srodowisku nie ma modulu FTS5. "
                "Wyszukiwanie pelnotekstowe nie zadziala."
            )
        migrate(conn)

        state = compatibility_state(
            self.repository,
            index_compat_hash=self.config.index_compat_hash(),
            vector_compat_hash=self.config.vector_compat_hash(),
        )
        if not state["fts_zgodny"]:
            message = (
                "Konfiguracja normalizacji albo fragmentacji zmienila sie od czasu "
                "zbudowania indeksu. Wymagana jest przebudowa indeksu."
            )
            if not allow_rebuild_prompt:
                raise IndexIncompatibleError(message)
            self._notes.append(message)
            self._rebuild_required = True

        if load_provider:
            self._load_provider(vector_compatible=bool(state["wektory_zgodne"]))

        if state["pierwszy_start"] or state["fts_zgodny"]:
            record_compatibility(
                self.repository,
                index_compat_hash=self.config.index_compat_hash(),
                vector_compat_hash=self.config.vector_compat_hash(),
                model_key=self.provider.info.model_key if self.provider else None,
                model_version=self.provider.info.model_version if self.provider else None,
                dimension=self.provider.dimension if self.provider else None,
            )
        self._opened = True

    def _load_provider(self, *, vector_compatible: bool) -> None:
        from finddocs.providers import create_provider

        try:
            self.provider = create_provider(self.config.embedding)
        except ProviderError as exc:
            self.provider = None
            self._notes.append(
                f"Wyszukiwanie semantyczne jest niedostepne: {exc.user_message} "
                "Tryb dokladny dziala normalnie."
            )
            log.warning("index.provider_unavailable", error_code=exc.code)
            return

        store = VectorStore(self.paths.vector_file, self.paths.vector_meta_file)
        try:
            store.open(
                dimension=self.provider.dimension,
                model_key=self.provider.info.model_key,
                model_version=self.provider.info.model_version,
                vector_compat_hash=self.config.vector_compat_hash(),
            )
        except IndexIncompatibleError as exc:
            self._notes.append(
                f"{exc.user_message} Do czasu przebudowy dziala wyszukiwanie dokladne."
            )
            self._rebuild_required = True
            log.warning("index.vector_incompatible", error_code=exc.code)
            self.vector_store = None
            return
        if not vector_compatible:
            self._notes.append(
                "Indeks wektorowy zostal zbudowany inna konfiguracja modelu. "
                "Zalecana jest przebudowa czesci semantycznej."
            )
            self._rebuild_required = True
        self.vector_store = store

    # --- dostep -----------------------------------------------------------

    @property
    def writer(self) -> IndexWriter:
        if self._writer is None:
            self._writer = IndexWriter(self.repository, self.vector_store)
        return self._writer

    @property
    def semantic_available(self) -> bool:
        return self.provider is not None and self.vector_store is not None

    @property
    def notes(self) -> list[str]:
        return list(self._notes)

    @property
    def rebuild_required(self) -> bool:
        """Czy uwagi startowe wymagaja przebudowy indeksu.

        Brak modelu embeddingow uwagą jest, ale przebudowy nie wymaga: indeks
        pelnotekstowy pozostaje poprawny, wylacza sie tylko tryb semantyczny.
        """
        return self._rebuild_required

    def status(self) -> IndexStatus:
        """Zbiera stan indeksu na potrzeby interfejsu."""
        documents = int(self.db.query_scalar("SELECT COUNT(*) FROM documents", (), 0))
        indexed = int(
            self.db.query_scalar(
                "SELECT COUNT(*) FROM documents WHERE status IN ('indexed','partial')", (), 0
            )
        )
        state = compatibility_state(
            self.repository,
            index_compat_hash=self.config.index_compat_hash(),
            vector_compat_hash=self.config.vector_compat_hash(),
        )
        return IndexStatus(
            exists=self.paths.database_file.exists(),
            schema_version=SCHEMA_VERSION,
            documents=documents,
            indexed_documents=indexed,
            chunks=self.repository.count_chunks(),
            vectors=self.vector_store.count() if self.vector_store else 0,
            model_key=self.provider.info.model_key if self.provider else None,
            model_dimension=self.provider.dimension if self.provider else None,
            fts_compatible=bool(state["fts_zgodny"]),
            vector_compatible=bool(state["wektory_zgodne"]),
            semantic_available=self.semantic_available,
            last_scan_at=self.repository.get_meta(META_LAST_SCAN_AT),
            last_full_index_at=self.repository.get_meta(META_LAST_FULL_INDEX_AT),
            size_bytes=self.paths.index_size_bytes(),
            free_space_bytes=self.paths.free_space_bytes(),
            notes=self.notes,
        )

    def consistency(self) -> ConsistencyReport:
        return check_consistency(self.db, self.repository, self.vector_store)

    def flush(self) -> None:
        """Utrwala indeks wektorowy i dziennik WAL."""
        if self.vector_store is not None:
            self.vector_store.save()
        self.db.checkpoint()

    def close(self) -> None:
        try:
            self.flush()
        finally:
            if self.provider is not None:
                self.provider.close()
            if self.vector_store is not None:
                self.vector_store.close()
            self.db.close()
            self._opened = False

    def __enter__(self) -> IndexService:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


__all__ = ["IndexService", "IndexStatus"]
