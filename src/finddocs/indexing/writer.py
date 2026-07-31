"""Transakcyjna aktualizacja indeksu pojedynczego dokumentu.

Kolejnosc operacji jest tak dobrana, zeby przerwanie w dowolnym momencie zostawialo
indeks w stanie spojnym i mozliwym do naprawy:

1. Fragmenty i wektory sa przygotowane w pamieci. Blad na tym etapie nie dotyka indeksu.
2. Jedna transakcja SQLite usuwa stare fragmenty, wstawia nowe i aktualizuje dokument.
   Wyzwalacze utrzymuja indeks FTS w zgodzie z tabela fragmentow.
3. Dopiero po zatwierdzeniu transakcji aktualizowany jest indeks wektorowy.

Przerwanie miedzy krokiem 2 a 3 zostawia dokument w stanie ``partial``: tekst jest
wyszukiwalny, a brakujace wektory zostana dopisane przy kolejnym uruchomieniu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from finddocs.indexing.repository import Repository
from finddocs.indexing.vector import VectorStore
from finddocs.logging_setup import get_logger
from finddocs.types import (
    Chunk,
    DocumentStatus,
    SupportLevel,
    TextOrigin,
)
from finddocs.version import CHUNKING_VERSION, NORMALIZATION_VERSION

log = get_logger(__name__)


@dataclass(slots=True)
class DocumentPayload:
    """Komplet danych do zapisania dla jednego dokumentu."""

    doc_id: int
    chunks: list[Chunk]
    change_key: str
    content_sha256: str | None
    page_count: int | None = None
    used_ocr: bool = False
    ocr_pages: int = 0
    ocr_confidence: float | None = None
    text_origin: TextOrigin = TextOrigin.NATIVE
    parser_name: str | None = None
    support_level: SupportLevel = SupportLevel.FULL
    title: str | None = None
    author: str | None = None
    embeddings: np.ndarray | None = None
    model_key: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WriteResult:
    """Wynik zapisu dokumentu."""

    doc_id: int
    status: DocumentStatus
    chunk_count: int
    vectors_written: int
    vectors_removed: int


class IndexWriter:
    """Zapisuje dokumenty do indeksu w sposob transakcyjny."""

    def __init__(
        self,
        repository: Repository,
        vector_store: VectorStore | None = None,
    ) -> None:
        self.repository = repository
        self.vector_store = vector_store
        self._pending_vector_saves = 0

    # --- zapis dokumentu --------------------------------------------------

    def write_document(self, payload: DocumentPayload) -> WriteResult:
        """Zapisuje fragmenty i wektory dokumentu."""
        db = self.repository.db
        has_vectors = (
            self.vector_store is not None
            and payload.embeddings is not None
            and len(payload.embeddings) == len(payload.chunks)
            and len(payload.chunks) > 0
        )

        with db.transaction():
            removed_vector_ids = self.repository.delete_chunks(payload.doc_id)
            new_chunk_ids = self.repository.insert_chunks(payload.doc_id, payload.chunks)
            status = DocumentStatus.INDEXED if payload.chunks else DocumentStatus.EMPTY
            if payload.chunks and self.vector_store is not None and not has_vectors:
                status = DocumentStatus.PARTIAL
            self.repository.finalize_document(
                payload.doc_id,
                status=status,
                chunk_count=len(payload.chunks),
                page_count=payload.page_count,
                used_ocr=payload.used_ocr,
                ocr_pages=payload.ocr_pages,
                ocr_confidence=payload.ocr_confidence,
                text_origin=payload.text_origin,
                parser_name=payload.parser_name,
                support_level=payload.support_level,
                content_sha256=payload.content_sha256,
                change_key=payload.change_key,
                normalization_version=NORMALIZATION_VERSION,
                chunking_version=CHUNKING_VERSION,
                model_key=payload.model_key if has_vectors else None,
                title=payload.title,
                author=payload.author,
                fts_indexed=bool(payload.chunks),
                vector_indexed=False,
                error_code=None,
                error_message=None,
            )

        vectors_written = 0
        if self.vector_store is not None and removed_vector_ids:
            self.vector_store.remove(removed_vector_ids)

        if has_vectors and self.vector_store is not None and payload.embeddings is not None:
            self.vector_store.add(new_chunk_ids, payload.embeddings)
            with db.transaction():
                self.repository.mark_chunks_vectorized(new_chunk_ids)
                self.repository.set_document_status(payload.doc_id, DocumentStatus.INDEXED)
                db.execute(
                    "UPDATE documents SET vector_indexed = 1, model_key = ? WHERE doc_id = ?",
                    (payload.model_key, payload.doc_id),
                )
            vectors_written = len(new_chunk_ids)
            self._pending_vector_saves += 1

        return WriteResult(
            doc_id=payload.doc_id,
            status=DocumentStatus.INDEXED if payload.chunks else DocumentStatus.EMPTY,
            chunk_count=len(payload.chunks),
            vectors_written=vectors_written,
            vectors_removed=len(removed_vector_ids),
        )

    def mark_failed(
        self,
        doc_id: int,
        status: DocumentStatus,
        *,
        error_code: str,
        error_message: str,
        stage: str,
        file_name: str | None = None,
        source_id: str | None = None,
        retryable: bool = False,
        change_key: str | None = None,
    ) -> None:
        """Zapisuje niepowodzenie przetwarzania dokumentu i usuwa jego fragmenty.

        Zapisany ``change_key`` sprawia, ze niezmieniony plik, ktorego nie da sie
        przetworzyc, nie jest ponawiany przy kazdym skanowaniu. Zmiana pliku albo
        pelne przeindeksowanie ponownie go zakwalifikuje.
        """
        db = self.repository.db
        with db.transaction():
            removed = self.repository.delete_chunks(doc_id)
            self.repository.set_document_status(
                doc_id,
                status,
                error_code=error_code,
                error_message=error_message,
                increment_attempt=True,
            )
            db.execute(
                "UPDATE documents SET fts_indexed = 0, vector_indexed = 0, "
                "change_key = COALESCE(?, change_key), "
                "normalization_version = ?, chunking_version = ? WHERE doc_id = ?",
                (
                    change_key,
                    NORMALIZATION_VERSION if change_key else 0,
                    CHUNKING_VERSION if change_key else 0,
                    doc_id,
                ),
            )
            self.repository.log_error(
                stage=stage,
                code=error_code,
                doc_id=doc_id,
                file_name=file_name,
                source_id=source_id,
                message=error_message,
                retryable=retryable,
            )
        if self.vector_store is not None and removed:
            self.vector_store.remove(removed)

    def delete_document(self, doc_id: int) -> None:
        """Usuwa dokument z indeksu."""
        db = self.repository.db
        with db.transaction():
            removed = self.repository.delete_document(doc_id)
        if self.vector_store is not None and removed:
            self.vector_store.remove(removed)
            self._pending_vector_saves += 1

    # --- utrwalanie -------------------------------------------------------

    def flush(self, *, force: bool = False, every: int = 25) -> bool:
        """Zapisuje indeks wektorowy na dysk co ``every`` dokumentow."""
        if self.vector_store is None:
            return False
        if not force and self._pending_vector_saves < every:
            return False
        if self._pending_vector_saves == 0 and not force:
            return False
        self.vector_store.save()
        self._pending_vector_saves = 0
        return True


__all__ = ["DocumentPayload", "IndexWriter", "WriteResult"]
