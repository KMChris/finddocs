"""Wspolne liczenie embeddingow dla wielu dokumentow, rownolegle z ekstrakcja.

Male dokumenty daja po kilka fragmentow, wiec osadzanie ich pojedynczo marnuje
batch dostawcy: sesja ONNX na GPU i zdalne API pracuja najwydajniej na duzych
paczkach. Batcher zbiera fragmenty kolejnych dokumentow i liczy embeddingi
jednym wywolaniem dostawcy.

Dostawca liczy w osobnym watku. Dzieki temu ekstrakcja, OCR i fragmentacja
kolejnych dokumentow ida rownolegle z liczeniem wektorow poprzednich: na
sciezce GPU (lokalny model na CUDA/DML albo zdalne API) karta nie czeka na
procesor i odwrotnie. Watek roboczy wykonuje WYLACZNIE wywolanie dostawcy.
Wszystkie zapisy do SQLite i magazynu wektorow pozostaja w watku zadania:
``submit``, ``take_completed`` i ``flush`` odbieraja gotowe paczki i wtedy
zapisuja dokumenty, kazdy osobna transakcja, tak jak sciezka bez batchowania.
Kolejka paczek jest ograniczona, wiec pamiec nie rosnie z liczba dokumentow.

Zasady spojnosci:

* zapis dokumentu nastepuje dopiero po policzeniu jego wektorow, wiec przerwanie
  w dowolnym momencie zostawia dokument w poprzednim stanie i zostanie on
  ponownie zakwalifikowany przy nastepnym skanowaniu;
* przed zapisem checkpointu zadanie woła ``flush``, ktore oproznia bufor,
  czeka na wszystkie paczki w locie i zapisuje je; licznik przetworzonych
  dokumentow w checkpointach nigdy nie wyprzedza zapisow;
* paczki wracaja z watku roboczego w kolejnosci wyslania, wiec zapisy zachowuja
  kolejnosc dokumentow;
* blad dostawcy nie zatrzymuje zadania: dokumenty z paczki sa zapisywane bez
  wektorow (status partial) i uzupelnione przy kolejnym przebiegu;
* anulowanie odklada nieprzetworzone dokumenty z powrotem do bufora, a zadanie
  jawnie je porzuca (``discard``);
* ``embed_batch_documents: 1`` w konfiguracji wylacza batcher w calosci
  i przywraca w pelni synchroniczna sciezke.
"""

from __future__ import annotations

import contextlib
import queue
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

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

#: Ile pelnych paczek moze czekac w kolejce do watku liczacego. Ogranicza
#: pamiec: w locie jest najwyzej ta liczba paczek plus jedna liczona.
QUEUE_BATCHES = 2

#: Najdluzsze pojedyncze czekanie na wynik z watku roboczego. Krotki interwal
#: pozwala regularnie sprawdzac, czy watek zyje.
_WAIT_INTERVAL_SECONDS = 0.2


@dataclass(slots=True)
class _PendingDocument:
    """Dokument czekajacy w buforze na wspolne policzenie embeddingow."""

    payload: DocumentPayload
    texts: list[str]
    outcome: DocumentOutcome
    tracked: bool


@dataclass(slots=True)
class _Batch:
    """Paczka dokumentow wyslana do watku liczacego."""

    documents: list[_PendingDocument]
    texts: list[str]
    control: CancellationToken | None


@dataclass(slots=True)
class _BatchResult:
    """Wynik policzenia jednej paczki."""

    batch: _Batch
    matrix: np.ndarray | None
    cancelled: bool


@dataclass(slots=True)
class EmbeddingBatcher:
    """Bufor fragmentow wielu dokumentow, liczonych w tle i zapisywanych wspolnie."""

    index: IndexService
    max_documents: int = DEFAULT_MAX_DOCUMENTS
    max_chunks: int = DEFAULT_MAX_CHUNKS
    _pending: list[_PendingDocument] = field(default_factory=list, init=False)
    _pending_chunks: int = field(default=0, init=False)
    _completed: list[DocumentOutcome] = field(default_factory=list, init=False)
    _work: queue.Queue[_Batch | None] = field(init=False)
    _results: queue.Queue[_BatchResult] = field(init=False)
    _dispatched: deque[_Batch] = field(default_factory=deque, init=False)
    _worker: threading.Thread | None = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.max_documents = max(1, self.max_documents)
        self.max_chunks = max(1, self.max_chunks)
        self._work = queue.Queue(maxsize=QUEUE_BATCHES)
        self._results = queue.Queue()

    # --- stan --------------------------------------------------------------

    @property
    def pending_documents(self) -> int:
        """Dokumenty w buforze, jeszcze nie wyslane do liczenia."""
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
        """Dodaje dokument do bufora; pelny bufor idzie do watku liczacego.

        ``tracked`` mowi, czy wynik dokumentu ma trafic do kolejki wynikow
        zadania. Zalaczniki wiadomosci sa zapisywane, ale nie licza sie do
        postepu, tak samo jak na sciezce bez batchowania. Przy okazji metoda
        zapisuje dokumenty z paczek juz policzonych, wiec zapisy ida na biezaco
        w watku zadania.
        """
        if self._pending and self._pending_chunks + len(texts) > self.max_chunks:
            self._dispatch(control)
        self._pending.append(
            _PendingDocument(payload=payload, texts=texts, outcome=outcome, tracked=tracked)
        )
        self._pending_chunks += len(texts)
        if len(self._pending) >= self.max_documents or self._pending_chunks >= self.max_chunks:
            self._dispatch(control)
        self._drain(wait=False)

    # --- oproznianie -------------------------------------------------------

    def flush(self, control: CancellationToken | None = None) -> None:
        """Wysyla bufor, czeka na wszystkie paczki w locie i zapisuje dokumenty.

        Po powrocie zaden dokument nie czeka na embeddingi ani na zapis, wiec
        checkpoint moze bezpiecznie utrwalic licznik przetworzonych. Anulowanie
        w trakcie liczenia przywraca niezapisane dokumenty do bufora i rzuca
        ``JobCancelledError``; zadanie jawnie porzuca je przez ``discard``.
        """
        self._dispatch(control)
        self._drain(wait=True)

    def _dispatch(self, control: CancellationToken | None) -> None:
        """Przekazuje biezacy bufor watkowi liczacemu. Nie czeka na wynik."""
        if not self._pending:
            return
        batch = _Batch(
            documents=self._pending,
            texts=[text for entry in self._pending for text in entry.texts],
            control=control,
        )
        self._pending = []
        self._pending_chunks = 0
        self._ensure_worker()
        while True:
            try:
                self._work.put(batch, timeout=_WAIT_INTERVAL_SECONDS)
                break
            except queue.Full:
                # Kolejka pelna: watek liczy poprzednie paczki. W miedzyczasie
                # zapisujemy gotowe wyniki, zeby nie rosla kolejka wynikow.
                self._drain(wait=False)
                self._ensure_worker()
        self._dispatched.append(batch)

    def _drain(self, *, wait: bool) -> None:
        """Odbiera policzone paczki i zapisuje ich dokumenty w watku zadania.

        ``wait=True`` blokuje do oproznienia wszystkich paczek w locie.
        Paczki anulowane wracaja do bufora; ``JobCancelledError`` leci dopiero
        w trybie blokujacym, zeby odbior przy okazji ``submit`` nie przerywal
        przetwarzania w polowie dokumentu.
        """
        saw_cancel = False
        while self._dispatched:
            try:
                if wait:
                    result = self._results.get(timeout=_WAIT_INTERVAL_SECONDS)
                else:
                    result = self._results.get_nowait()
            except queue.Empty:
                if not wait:
                    break
                if self._worker is None or not self._worker.is_alive():
                    # Watek liczacy zginal (nie powinno sie zdarzyc). Dokumenty
                    # z paczek w locie zapisujemy bez wektorow, zeby zadne nie
                    # przepadly; kolejne skanowanie uzupelni embeddingi.
                    log.error("embed_batch.worker_died", batches=len(self._dispatched))
                    while self._dispatched:
                        self._write_batch(self._dispatched.popleft(), None)
                    break
                continue
            try:
                self._dispatched.remove(result.batch)
            except ValueError:
                # Paczka porzucona przez discard: wynik jest juz nieaktualny.
                continue
            if result.cancelled:
                saw_cancel = True
                self._restore(result.batch)
                continue
            self._write_batch(result.batch, result.matrix)
        if saw_cancel and wait:
            raise JobCancelledError()

    def _restore(self, batch: _Batch) -> None:
        """Przywraca dokumenty anulowanej paczki do bufora, w kolejnosci."""
        self._pending.extend(batch.documents)
        self._pending_chunks += sum(len(entry.texts) for entry in batch.documents)

    def _write_batch(self, batch: _Batch, matrix: np.ndarray | None) -> None:
        offset = 0
        usable = matrix is not None and len(matrix) == len(batch.texts)
        for entry in batch.documents:
            count = len(entry.texts)
            if usable and matrix is not None:
                entry.payload.embeddings = matrix[offset : offset + count]
            offset += count
            self._write(entry)
        log.debug(
            "embed_batch.flushed",
            documents=len(batch.documents),
            chunks=len(batch.texts),
            with_vectors=usable,
        )

    def _write(self, entry: _PendingDocument) -> None:
        """Zapisuje jeden dokument z paczki, nie zatrzymujac pozostalych."""
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

    # --- watek liczacy -----------------------------------------------------

    def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(
            target=self._worker_loop, name="finddocs-embed", daemon=True
        )
        self._worker.start()

    def _worker_loop(self) -> None:
        """Petla watku liczacego: wylacznie wywolania dostawcy, zadnych zapisow."""
        while True:
            item = self._work.get()
            if item is None:
                return
            matrix: np.ndarray | None = None
            cancelled = False
            provider = self.index.provider
            if provider is not None:
                try:
                    matrix = provider.embed_passages(item.texts, cancel=item.control)
                except JobCancelledError:
                    cancelled = True
                except BaseException as exc:  # degradacja zamiast awarii zadania
                    log.warning(
                        "embed_batch.embedding_failed",
                        documents=len(item.documents),
                        chunks=len(item.texts),
                        error_type=type(exc).__name__,
                    )
            self._results.put(_BatchResult(batch=item, matrix=matrix, cancelled=cancelled))

    # --- wyniki ------------------------------------------------------------

    def take_completed(self) -> list[DocumentOutcome]:
        """Zapisuje paczki policzone od ostatniego odbioru i zwraca ich wyniki."""
        self._drain(wait=False)
        completed = self._completed
        self._completed = []
        return completed

    def discard(self) -> int:
        """Porzuca bufor i paczki w locie bez zapisu. Zwraca liczbe dokumentow.

        Uzywane przy anulowaniu zadania. Porzucone dokumenty nie maja
        zaktualizowanego klucza zmiany, wiec nastepne skanowanie przetworzy
        je ponownie. Wynik paczki liczonej wlasnie przez watek zostanie
        zignorowany przy odbiorze, bo paczka nie jest juz na liscie w locie.
        """
        count = len(self._pending) + sum(len(batch.documents) for batch in self._dispatched)
        self._pending = []
        self._pending_chunks = 0
        with contextlib.suppress(queue.Empty):
            while True:
                self._work.get_nowait()
        self._dispatched.clear()
        with contextlib.suppress(queue.Empty):
            while True:
                self._results.get_nowait()
        if count:
            log.info("embed_batch.discarded", documents=count)
        return count

    def close(self) -> None:
        """Konczy watek liczacy. Nie zapisuje; wczesniej nalezy wywolac flush."""
        if self._closed:
            return
        self._closed = True
        if self._worker is None:
            return
        while True:
            try:
                self._work.put(None, timeout=_WAIT_INTERVAL_SECONDS)
                break
            except queue.Full:
                if not self._worker.is_alive():
                    break
                with contextlib.suppress(queue.Empty):
                    self._work.get_nowait()
        self._worker.join(timeout=10.0)
        self._worker = None


__all__ = ["DEFAULT_MAX_CHUNKS", "DEFAULT_MAX_DOCUMENTS", "QUEUE_BATCHES", "EmbeddingBatcher"]
