"""Testy integracyjne zachowania aplikacji w warunkach bledu.

Zakres: brak miejsca na dysku w trakcie indeksowania, uszkodzony plik tymczasowy,
awaria pojedynczego parsera oraz sterowanie zadaniem (pauza, wznowienie, anulowanie)
wraz z polityka ponawiania prob.
"""

from __future__ import annotations

import hashlib
import itertools
import random
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from finddocs.app_paths import AppPaths
from finddocs.config import AppConfig
from finddocs.connectors.local_dir import LocalDirectoryConnector
from finddocs.errors import ExtractionError, JobCancelledError
from finddocs.extractors.base import ExtractionContext
from finddocs.extractors.registry import ExtractorRegistry
from finddocs.indexing.service import IndexService
from finddocs.jobs.control import JobControl, RetryPolicy
from finddocs.types import (
    CancellationToken,
    DocumentStatus,
    ExtractionResult,
    FetchedFile,
    JobState,
    ProgressSnapshot,
    SourceItem,
)

#: Dokumenty uzywane w testach bledow.
CORPUS: dict[str, str] = {
    "alfa.txt": (
        "Notatka pierwsza z przegladu procedur.\nSlowo rozpoznawcze tego dokumentu to kolczatka.\n"
    ),
    "beta.txt": (
        "Notatka druga z przegladu procedur.\nSlowo rozpoznawcze tego dokumentu to wiewiorka.\n"
    ),
    "gamma.txt": (
        "Notatka trzecia z przegladu procedur.\nSlowo rozpoznawcze tego dokumentu to jezozwierz.\n"
    ),
}


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "zrodlo"
    root.mkdir(parents=True, exist_ok=True)
    for name, content in CORPUS.items():
        (root / name).write_text(content, encoding="utf-8")
    return root


# --- brak miejsca na dysku -------------------------------------------------------


def test_brak_miejsca_konczy_zadanie_stanem_failed(
    indexing_config: Callable[..., AppConfig],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
    corpus: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = indexing_config(corpus)
    monkeypatch.setattr(AppPaths, "free_space_bytes", lambda self: 16 * 1024 * 1024)

    snapshot = run_job(config, index_service)

    assert snapshot.state is JobState.FAILED
    assert snapshot.message is not None
    assert "zabraklo miejsca" in snapshot.message
    assert "Wolne miejsce" in snapshot.message

    zadanie = index_service.repository.get_job(snapshot.job_id)
    assert zadanie is not None
    assert str(zadanie["state"]) == JobState.FAILED.value
    assert str(zadanie["error_message"]) == snapshot.message

    # Indeks zostaje spojny: przerwane zadanie nie zostawia po sobie smieci.
    raport = index_service.consistency()
    assert raport.orphan_chunks == 0
    assert raport.is_healthy is True
    assert index_service.db.integrity_check() == []


# --- uszkodzony plik tymczasowy --------------------------------------------------


def test_uszkodzony_plik_tymczasowy_nie_przerywa_zadania(
    indexing_config: Callable[..., AppConfig],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
    document_statuses: Callable[[IndexService], dict[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "zrodlo"
    root.mkdir(parents=True, exist_ok=True)
    (root / "notatka.txt").write_text("Tresc notatki sluzbowej.\n", encoding="utf-8")
    (root / "raport.pdf").write_bytes(b"%PDF-1.4 tresc zastepcza\n")
    config = indexing_config(root)

    losowy = random.Random(20240501)

    def zepsute_pobranie(
        self: LocalDirectoryConnector,
        item: SourceItem,
        destination: Path,
        *,
        cancel: CancellationToken | None = None,
    ) -> FetchedFile:
        """Zwraca plik wypelniony losowymi bajtami zamiast prawdziwej tresci."""
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / item.name
        dane = bytes(losowy.randrange(256) for _ in range(2048))
        target.write_bytes(dane)
        return FetchedFile(
            item=item,
            path=target,
            size=len(dane),
            sha256=hashlib.sha256(dane).hexdigest(),
        )

    monkeypatch.setattr(LocalDirectoryConnector, "fetch", zepsute_pobranie)

    snapshot = run_job(config, index_service)

    assert snapshot.state is JobState.COMPLETED
    assert snapshot.discovered == 2
    statusy = document_statuses(index_service)
    # Plik podszywajacy sie pod PDF nie da sie otworzyc, wiec konczy jako uszkodzony.
    assert statusy["raport.pdf"] == DocumentStatus.CORRUPTED.value
    # Zaden dokument nie zostaje w stanie oczekiwania: kazdy ma zapisany wynik.
    assert DocumentStatus.PENDING.value not in statusy.values()
    assert index_service.consistency().is_healthy is True


# --- blad pojedynczego parsera ---------------------------------------------------


def test_blad_jednego_parsera_nie_zatrzymuje_pozostalych(
    indexing_config: Callable[..., AppConfig],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
    document_statuses: Callable[[IndexService], dict[str, str]],
    corpus: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = indexing_config(corpus)
    oryginalny = ExtractorRegistry.extract

    def wybuchowy(
        self: ExtractorRegistry,
        path: Path,
        context: ExtractionContext,
        *,
        declared_mime: str | None = None,
        file_name: str | None = None,
    ) -> tuple[ExtractionResult, object]:
        if (file_name or path.name) == "beta.txt":
            raise ExtractionError("Celowy blad parsera w tescie.")
        return oryginalny(  # type: ignore[return-value]
            self, path, context, declared_mime=declared_mime, file_name=file_name
        )

    monkeypatch.setattr(ExtractorRegistry, "extract", wybuchowy)

    snapshot = run_job(config, index_service)

    assert snapshot.state is JobState.COMPLETED
    assert snapshot.processed == len(CORPUS) - 1
    assert snapshot.failed == 1

    statusy = document_statuses(index_service)
    assert statusy["beta.txt"] == DocumentStatus.ERROR.value
    assert statusy["alfa.txt"] == DocumentStatus.INDEXED.value
    assert statusy["gamma.txt"] == DocumentStatus.INDEXED.value

    zepsuty = index_service.repository.find_document("lokalne", "beta.txt")
    assert zepsuty is not None
    assert zepsuty.error_message == "Celowy blad parsera w tescie."
    assert zepsuty.chunk_count == 0
    kody = index_service.repository.error_counts()
    assert kody.get("FD-3000", 0) >= 1


# --- sterowanie zadaniem ---------------------------------------------------------


def test_job_control_pauza_i_wznowienie() -> None:
    control = JobControl()
    zwolniony = threading.Event()

    def robotnik() -> None:
        control.wait_if_paused()
        zwolniony.set()

    control.pause()
    assert control.is_paused is True

    watek = threading.Thread(target=robotnik, name="pauza-test")
    watek.start()
    try:
        assert zwolniony.wait(0.5) is False
        control.resume()
        assert zwolniony.wait(5.0) is True
    finally:
        watek.join(5.0)

    assert control.is_paused is False
    assert control.paused_seconds >= 0.4
    assert watek.is_alive() is False


def test_job_control_paused_seconds_sumuje_przerwy() -> None:
    control = JobControl()
    assert control.paused_seconds == 0.0

    control.pause()
    time.sleep(0.2)
    control.resume()
    pierwsza = control.paused_seconds

    control.pause()
    time.sleep(0.2)
    control.resume()

    assert pierwsza >= 0.15
    assert control.paused_seconds >= pierwsza + 0.15


def test_job_control_anulowanie_przerywa_oczekiwanie() -> None:
    control = JobControl()
    control.pause()
    blad: list[BaseException] = []

    def robotnik() -> None:
        try:
            control.wait_if_paused()
        except BaseException as exc:
            blad.append(exc)

    watek = threading.Thread(target=robotnik, name="anulowanie-test")
    watek.start()
    time.sleep(0.1)
    control.cancel()
    watek.join(5.0)

    assert watek.is_alive() is False
    assert len(blad) == 1
    assert isinstance(blad[0], JobCancelledError)
    assert control.is_cancelled() is True
    with pytest.raises(JobCancelledError):
        control.checkpoint()


def test_job_control_reset_czysci_stan() -> None:
    control = JobControl()
    control.pause()
    control.cancel()
    assert control.is_cancelled() is True

    control.reset()

    assert control.is_cancelled() is False
    assert control.is_paused is False
    assert control.paused_seconds == 0.0
    control.checkpoint()


# --- polityka ponawiania ---------------------------------------------------------


def test_retry_policy_opoznienia_rosna_wykladniczo_i_sa_ograniczone() -> None:
    policy = RetryPolicy(max_attempts=6, base_delay=2.0, max_delay=10.0, multiplier=2.0)

    opoznienia = [policy.delay_for(numer) for numer in range(1, 7)]

    assert opoznienia == [0.0, 2.0, 4.0, 8.0, 10.0, 10.0]
    assert all(b >= a for a, b in itertools.pairwise(opoznienia))
    assert max(opoznienia) <= policy.max_delay


def test_retry_policy_pierwsza_proba_nie_czeka() -> None:
    policy = RetryPolicy(base_delay=30.0)
    start = time.monotonic()

    policy.sleep(1)

    assert time.monotonic() - start < 0.5


def test_retry_policy_reaguje_na_anulowanie() -> None:
    policy = RetryPolicy(base_delay=30.0, max_delay=60.0)
    control = JobControl()
    control.cancel()
    start = time.monotonic()

    with pytest.raises(JobCancelledError):
        policy.sleep(3, control)

    assert time.monotonic() - start < 0.5
