"""Wspolne liczenie embeddingow dla wielu dokumentow naraz.

Male dokumenty daja po kilka fragmentow, wiec osadzanie ich pojedynczo marnuje
batch dostawcy: sesja ONNX na GPU i zdalne API pracuja najwydajniej na duzych
paczkach. Batcher zbiera fragmenty kolejnych dokumentow i liczy embeddingi
jednym wywolaniem dostawcy, a potem zapisuje kazdy dokument osobna transakcja,
tak jak sciezka bez batchowania.

Zasady spojnosci:

* zapis dokumentu nastepuje dopiero po policzeniu jego wektorow, wiec przerwanie
  w dowolnym momencie zostawia dokument w poprzednim stanie i zostanie on
  ponownie zakwalifikowany przy nastepnym skanowaniu;
* przed zapisem checkpointu zadanie oproznia bufor, dzieki czemu licznik
  przetworzonych dokumentow w checkpointach nigdy nie wyprzedza zapisow;
* blad dostawcy nie zatrzymuje zadania: dokumenty z bufora sa zapisywane bez
  wektorow (status partial) i uzupelnione przy kolejnym przebiegu;
* anulowanie odklada nieprzetworzone dokumenty z powrotem do bufora, a zadanie
  jawnie je porzuca.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from finddocs.errors import JobCancelledError
from finddocs.indexing.service import IndexService
from finddocs.indexing.writer import DocumentPayload
from finddocs.logging_setup import get_logger
from finddocs.types import CancellationToken, DocumentStatus

if TYPE_CHECKING:
    from finddocs.jobs.pipeline import DocumentOutcome

log = get_logger(__name__)

#: Domyslne progi oprozniania bufora.
DEFAULT_MAX_DOCUMENTS = 8
DEFAULT_MAX_CHUNKS = 128


@dataclass(slots=True)
class _PendingDocument:
    """Dokument czekajacy w buforze na wspolne policzenie embeddingow."""

    payload: DocumentPayload
    texts: list[str]
    outcome: DocumentOutcome
    tracked: bool


@dataclass(slots=True)
class EmbeddingBatcher:
    """Bufor fragmentow wielu dokumentow i wspolny zapis po osadzeniu."""

    index: IndexService
    max_documents: int = DEFAULT_MAX_DOCUMENTS
    max_chunks: int = DEFAULT_MAX_CHUNKS
    _pending: list[_PendingDocument] = field(default_factory=list, init=False)
    _pending_chunks: int = field(default=0, init=False)
    _completed: list[DocumentOutcome] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.max_documents = max(1, self.max_documents)
        self.max_chunks = max(1, self.max_chunks)

    # --- stan --------------------------------------------------------------

    @property
    def pending_documents(self) -> int:
        return len(self._pending)

    @property
    def pending_chunks(self) -> int:
        return self._pending_chunks

    # --- przyjmowanie ------------------------------------------------------

    def submit(
        self,
        payload: DocumentPayload,
        texts: list[str],
        outcome: DocumentOutcome,
        *,
        tracked: bool,
        control: CancellationToken | None = None,
    ) -> None:
        """Dodaje dokument do bufora i oproznia go po przekroczeniu progow.

        ``tracked`` mowi, czy wynik dokumentu ma trafic do kolejki wynikow
        zadania. Zalaczniki wiadomosci sa zapisywane, ale nie licza sie do
        postepu, tak samo jak na sciezce bez batchowania.
        """
        if self._pending and self._pending_chunks + len(texts) > self.max_chunks:
            self.flush(control)
        self._pending.append(
            _PendingDocument(payload=payload, texts=texts, outcome=outcome, tracked=tracked)
        )
        self._pending_chunks += len(texts)
        if len(self._pending) >= self.max_documents or self._pending_chunks >= self.max_chunks:
            self.flush(control)

    # --- oproznianie -------------------------------------------------------

    def flush(self, control: CancellationToken | None = None) -> None:
        """Osadza wszystkie fragmenty z bufora i zapisuje dokumenty."""
        if not self._pending:
            return
        pending = self._pending
        pending_chunks = self._pending_chunks
        self._pending = []
        self._pending_chunks = 0

        texts = [text for entry in pending for text in entry.texts]
        provider = self.index.provider
        matrix = None
        if provider is not None:
            try:
                matrix = provider.embed_passages(texts, cancel=control)
            except JobCancelledError:
                # Dokumenty wracaja do bufora, zeby zadanie moglo je jawnie
                # porzucic i policzyc w logu.
                self._pending = pending
                self._pending_chunks = pending_chunks
                raise
            except Exception as exc:
                log.warning(
                    "embed_batch.embedding_failed",
                    documents=len(pending),
                    chunks=len(texts),
                    error_type=type(exc).__name__,
                )
                matrix = None

        offset = 0
        for entry in pending:
            count = len(entry.texts)
            if matrix is not None and len(matrix) == len(texts):
                entry.payload.embeddings = matrix[offset : offset + count]
            offset += count
            self._write(entry)

        log.debug(
            "embed_batch.flushed",
            documents=len(pending),
            chunks=len(texts),
            with_vectors=matrix is not None,
        )

    def _write(self, entry: _PendingDocument) -> None:
        """Zapisuje jeden dokument z bufora, nie zatrzymujac pozostalych."""
        try:
            write = self.index.writer.write_document(entry.payload)
            entry.outcome.status = write.status
            entry.outcome.chunks = write.chunk_count
        except Exception as exc:
            log.error(
                "embed_batch.write_failed",
                doc_id=entry.payload.doc_id,
                error_type=type(exc).__name__,
            )
            message = f"Nieoczekiwany błąd zapisu dokumentu: {type(exc).__name__}."
            entry.outcome.status = DocumentStatus.ERROR
            entry.outcome.error_code = "FD-3000"
            entry.outcome.error_message = message
            with contextlib.suppress(Exception):
                self.index.writer.mark_failed(
                    entry.payload.doc_id,
                    DocumentStatus.ERROR,
                    error_code="FD-3000",
                    error_message=message,
                    stage="write",
                )
        if entry.tracked:
            self._completed.append(entry.outcome)

    # --- wyniki ------------------------------------------------------------

    def take_completed(self) -> list[DocumentOutcome]:
        """Zwraca i czysci liste dokumentow zakonczonych od ostatniego odbioru."""
        completed = self._completed
        self._completed = []
        return completed

    def discard(self) -> int:
        """Porzuca bufor bez zapisu. Zwraca liczbe porzuconych dokumentow.

        Uzywane przy anulowaniu zadania. Porzucone dokumenty nie maja
        zaktualizowanego klucza zmiany, wiec nastepne skanowanie przetworzy
        je ponownie.
        """
        count = len(self._pending)
        self._pending = []
        self._pending_chunks = 0
        if count:
            log.info("embed_batch.discarded", documents=count)
        return count


__all__ = ["DEFAULT_MAX_CHUNKS", "DEFAULT_MAX_DOCUMENTS", "EmbeddingBatcher"]
