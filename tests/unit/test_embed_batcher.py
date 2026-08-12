"""Testy batchera embeddingow: progi, podzial wynikow, degradacja, anulowanie."""

from __future__ import annotations

import numpy as np
import pytest

from finddocs.errors import JobCancelledError
from finddocs.indexing.writer import DocumentPayload, WriteResult
from finddocs.jobs.embed_batch import EmbeddingBatcher
from finddocs.jobs.pipeline import DocumentOutcome
from finddocs.types import Chunk, DocumentStatus

DIMENSION = 4


def _chunk(ordinal: int, text: str) -> Chunk:
    return Chunk(ordinal=ordinal, text=text, search_text=text, folded_text=text)


def _payload(doc_id: int, texts: list[str]) -> DocumentPayload:
    return DocumentPayload(
        doc_id=doc_id,
        chunks=[_chunk(i, text) for i, text in enumerate(texts)],
        change_key="klucz",
        content_sha256="abc",
    )


def _outcome(doc_id: int) -> DocumentOutcome:
    return DocumentOutcome(doc_id=doc_id, status=DocumentStatus.INDEXED, deferred=True)


class FakeProvider:
    """Dostawca zwracajacy przewidywalne wektory i liczacy wywolania."""

    def __init__(self, *, fail: Exception | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail = fail

    def embed_passages(self, texts: list[str], *, cancel: object | None = None) -> np.ndarray:
        self.calls.append(list(texts))
        if self.fail is not None:
            raise self.fail
        return np.full((len(texts), DIMENSION), 0.5, dtype="float32")


class FakeWriter:
    """Rejestruje zapisy dokumentow zamiast dotykac bazy."""

    def __init__(self) -> None:
        self.written: list[DocumentPayload] = []
        self.failed: list[int] = []

    def write_document(self, payload: DocumentPayload) -> WriteResult:
        self.written.append(payload)
        return WriteResult(
            doc_id=payload.doc_id,
            status=DocumentStatus.INDEXED,
            chunk_count=len(payload.chunks),
            vectors_written=len(payload.chunks) if payload.embeddings is not None else 0,
            vectors_removed=0,
        )

    def mark_failed(self, doc_id: int, status: DocumentStatus, **kwargs: object) -> None:
        self.failed.append(doc_id)


class FakeIndex:
    def __init__(self, provider: FakeProvider | None) -> None:
        self.provider = provider
        self.writer = FakeWriter()


class FakeControl:
    def __init__(self) -> None:
        self.cancelled = False

    def is_cancelled(self) -> bool:
        return self.cancelled

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise JobCancelledError()


def _batcher(
    provider: FakeProvider | None, *, max_documents: int = 8, max_chunks: int = 128
) -> tuple[EmbeddingBatcher, FakeIndex]:
    index = FakeIndex(provider)
    batcher = EmbeddingBatcher(index, max_documents=max_documents, max_chunks=max_chunks)  # type: ignore[arg-type]
    return batcher, index


# --- progi -----------------------------------------------------------------------


def test_prog_liczby_dokumentow_wyzwala_flush() -> None:
    provider = FakeProvider()
    batcher, index = _batcher(provider, max_documents=2)

    batcher.submit(_payload(1, ["a"]), ["a"], _outcome(1), tracked=True)
    assert index.writer.written == []

    batcher.submit(_payload(2, ["b", "c"]), ["b", "c"], _outcome(2), tracked=True)
    assert provider.calls == [["a", "b", "c"]]
    assert [p.doc_id for p in index.writer.written] == [1, 2]
    assert batcher.pending_documents == 0


def test_prog_fragmentow_oproznia_bufor_przed_duzym_dokumentem() -> None:
    provider = FakeProvider()
    batcher, index = _batcher(provider, max_documents=10, max_chunks=3)

    batcher.submit(_payload(1, ["a", "b"]), ["a", "b"], _outcome(1), tracked=True)
    batcher.submit(_payload(2, ["c", "d"]), ["c", "d"], _outcome(2), tracked=True)

    # Dolozenie drugiego dokumentu przekroczyloby limit fragmentow, wiec bufor
    # zostal oprozniony przed dodaniem, a drugi dokument czeka na kolejny flush.
    assert provider.calls == [["a", "b"]]
    assert batcher.pending_documents == 1

    batcher.flush()
    assert provider.calls == [["a", "b"], ["c", "d"]]
    assert [p.doc_id for p in index.writer.written] == [1, 2]


def test_dokument_wiekszy_niz_limit_idzie_osobno() -> None:
    provider = FakeProvider()
    batcher, index = _batcher(provider, max_documents=10, max_chunks=2)

    batcher.submit(_payload(1, ["a", "b", "c"]), ["a", "b", "c"], _outcome(1), tracked=True)
    assert provider.calls == [["a", "b", "c"]]
    assert [p.doc_id for p in index.writer.written] == [1]


# --- podzial wynikow -------------------------------------------------------------


def test_wektory_sa_rozdzielane_wedlug_dokumentow() -> None:
    provider = FakeProvider()
    batcher, index = _batcher(provider)

    batcher.submit(_payload(1, ["a"]), ["a"], _outcome(1), tracked=True)
    batcher.submit(_payload(2, ["b", "c"]), ["b", "c"], _outcome(2), tracked=True)
    batcher.flush()

    first, second = index.writer.written
    assert first.embeddings is not None and first.embeddings.shape == (1, DIMENSION)
    assert second.embeddings is not None and second.embeddings.shape == (2, DIMENSION)


def test_wyniki_trafiaja_do_kolejki_z_pominieciem_niesledzonych() -> None:
    provider = FakeProvider()
    batcher, index = _batcher(provider)

    batcher.submit(_payload(1, ["a"]), ["a"], _outcome(1), tracked=True)
    batcher.submit(_payload(2, ["b"]), ["b"], _outcome(2), tracked=False)
    batcher.flush()

    completed = batcher.take_completed()
    assert [o.doc_id for o in completed] == [1]
    assert completed[0].status is DocumentStatus.INDEXED
    assert completed[0].chunks == 1
    # Zalacznik (niesledzony) zostal zapisany, ale nie liczy sie do postepu.
    assert [p.doc_id for p in index.writer.written] == [1, 2]
    assert batcher.take_completed() == []


# --- degradacja i anulowanie -----------------------------------------------------


def test_blad_dostawcy_zapisuje_dokumenty_bez_wektorow() -> None:
    provider = FakeProvider(fail=RuntimeError("awaria"))
    batcher, index = _batcher(provider)

    batcher.submit(_payload(1, ["a"]), ["a"], _outcome(1), tracked=True)
    batcher.flush()

    assert len(index.writer.written) == 1
    assert index.writer.written[0].embeddings is None
    assert [o.doc_id for o in batcher.take_completed()] == [1]


def test_anulowanie_przywraca_bufor_i_discard_go_czysci() -> None:
    provider = FakeProvider(fail=JobCancelledError())
    batcher, index = _batcher(provider)

    batcher.submit(_payload(1, ["a"]), ["a"], _outcome(1), tracked=True)
    with pytest.raises(JobCancelledError):
        batcher.flush()

    assert batcher.pending_documents == 1
    assert index.writer.written == []
    assert batcher.discard() == 1
    assert batcher.pending_documents == 0


def test_blad_zapisu_jednego_dokumentu_nie_blokuje_pozostalych() -> None:
    provider = FakeProvider()
    batcher, index = _batcher(provider)

    original_write = index.writer.write_document

    def flaky_write(payload: DocumentPayload) -> WriteResult:
        if payload.doc_id == 1:
            raise RuntimeError("dysk")
        return original_write(payload)

    index.writer.write_document = flaky_write  # type: ignore[method-assign]

    batcher.submit(_payload(1, ["a"]), ["a"], _outcome(1), tracked=True)
    batcher.submit(_payload(2, ["b"]), ["b"], _outcome(2), tracked=True)
    batcher.flush()

    completed = {o.doc_id: o for o in batcher.take_completed()}
    assert completed[1].status is DocumentStatus.ERROR
    assert completed[2].status is DocumentStatus.INDEXED
    assert index.writer.failed == [1]


def test_pusty_flush_nie_wywoluje_dostawcy() -> None:
    provider = FakeProvider()
    batcher, _index = _batcher(provider)
    batcher.flush()
    assert provider.calls == []
