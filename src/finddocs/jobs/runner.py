"""Kolejka i uruchamianie zadan w tle.

Interfejs uzytkownika nigdy nie wykonuje pracy w watku glownym. Zadania ida do
kolejki obslugiwanej przez jeden watek roboczy, ktory mozna wstrzymac, wznowic
i anulowac. Po zamknieciu aplikacji niedokonczone zadania zostaja w bazie ze
stanem, ktory pozwala je wznowic przy kolejnym starcie.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from finddocs.app_paths import AppPaths
from finddocs.config import AppConfig
from finddocs.indexing.service import IndexService
from finddocs.jobs.control import JobControl
from finddocs.jobs.indexing_job import IndexingJob, JobOptions
from finddocs.logging_setup import get_logger
from finddocs.types import JobKind, JobState, ProgressSnapshot

log = get_logger(__name__)

ProgressCallback = Callable[[ProgressSnapshot], None]
CompletionCallback = Callable[[ProgressSnapshot], None]


@dataclass(slots=True)
class QueuedJob:
    """Zadanie oczekujace w kolejce."""

    options: JobOptions
    control: JobControl = field(default_factory=JobControl)
    job_id: str | None = None


class _SinkAdapter:
    """Przekazuje migawki postepu do wywolan zwrotnych."""

    def __init__(self, callbacks: list[ProgressCallback]) -> None:
        self._callbacks = callbacks

    def update(self, snapshot: ProgressSnapshot) -> None:
        for callback in list(self._callbacks):
            try:
                callback(snapshot)
            except Exception as exc:
                log.warning("runner.progress_callback_failed", error_type=type(exc).__name__)


class JobRunner:
    """Watek roboczy obslugujacy kolejke zadan indeksowania."""

    def __init__(
        self,
        config: AppConfig,
        index: IndexService,
        *,
        paths: AppPaths | None = None,
        config_provider: Callable[[], AppConfig] | None = None,
    ) -> None:
        self.config = config
        self.index = index
        self.paths = paths or index.paths
        self._config_provider = config_provider
        self._queue: queue.Queue[QueuedJob | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._current: IndexingJob | None = None
        self._current_control: JobControl | None = None
        self._lock = threading.RLock()
        self._progress_callbacks: list[ProgressCallback] = []
        self._completion_callbacks: list[CompletionCallback] = []
        self._stopping = threading.Event()
        self._last_snapshot: ProgressSnapshot | None = None

    # --- subskrypcje ------------------------------------------------------

    def on_progress(self, callback: ProgressCallback) -> None:
        """Dopisuje odbiorce postepu. Powtorne zgloszenie tego samego nic nie zmienia.

        Widok zglasza sie przy kazdym zleceniu zadania. Bez odsiewania powtorzen
        lista rosla z kazdym uruchomieniem, a interfejs dostawal te sama migawke
        tyle razy, ile zadan zlecono w tej sesji.
        """
        if callback not in self._progress_callbacks:
            self._progress_callbacks.append(callback)

    def on_completed(self, callback: CompletionCallback) -> None:
        """Dopisuje odbiorce zakonczenia. Powtorne zgloszenie tego samego nic nie zmienia."""
        if callback not in self._completion_callbacks:
            self._completion_callbacks.append(callback)

    # --- cykl zycia -------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping.clear()
            self._thread = threading.Thread(target=self._worker, name="finddocs-jobs", daemon=True)
            self._thread.start()

    def stop(self, *, wait: bool = True, timeout: float = 30.0) -> None:
        """Zatrzymuje watek roboczy. Biezace zadanie jest anulowane."""
        self._stopping.set()
        with self._lock:
            if self._current_control is not None:
                self._current_control.cancel()
            self._queue.put(None)
            thread = self._thread
        if wait and thread is not None:
            thread.join(timeout=timeout)

    # --- zlecanie ---------------------------------------------------------

    def submit(self, options: JobOptions) -> QueuedJob:
        job = QueuedJob(options=options)
        self._queue.put(job)
        self.start()
        return job

    def submit_full_index(self, source_ids: list[str] | None = None) -> QueuedJob:
        return self.submit(
            JobOptions(
                kind=JobKind.FULL_INDEX,
                source_ids=source_ids or [],
                force_reindex=True,
            )
        )

    def submit_rescan(self, source_ids: list[str] | None = None) -> QueuedJob:
        return self.submit(JobOptions(kind=JobKind.RESCAN, source_ids=source_ids or []))

    def submit_resume(self, job_id: str, source_ids: list[str] | None = None) -> QueuedJob:
        return self.submit(
            JobOptions(
                kind=JobKind.RESCAN,
                source_ids=source_ids or [],
                resume_job_id=job_id,
            )
        )

    # --- sterowanie -------------------------------------------------------

    def pause(self) -> bool:
        with self._lock:
            if self._current_control is None:
                return False
            self._current_control.pause()
            return True

    def resume(self) -> bool:
        with self._lock:
            if self._current_control is None:
                return False
            self._current_control.resume()
            return True

    def cancel(self) -> bool:
        with self._lock:
            if self._current_control is None:
                return False
            self._current_control.cancel()
            return True

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._current is not None

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._current_control is not None and self._current_control.is_paused

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    @property
    def last_snapshot(self) -> ProgressSnapshot | None:
        return self._last_snapshot

    # --- wznawianie po restarcie -----------------------------------------

    def resumable_jobs(self) -> list[dict[str, Any]]:
        """Zadania przerwane przez zamkniecie aplikacji albo restart systemu."""
        rows = self.index.repository.resumable_jobs()
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "job_id": str(row["job_id"]),
                    "rodzaj": str(row["kind"]),
                    "stan": str(row["state"]),
                    "utworzono": row["created_at"],
                    "zaktualizowano": row["updated_at"],
                    "zrodla": str(row["source_ids"] or "").split(",") if row["source_ids"] else [],
                }
            )
        return result

    def mark_interrupted_jobs(self) -> int:
        """Oznacza zadania, ktore zostaly przerwane przez zamkniecie aplikacji.

        Wywolywane przy starcie. Zadania w stanie ``running`` nie moga byc aktywne
        zaraz po uruchomieniu procesu, wiec sa przestawiane na ``paused``, zeby
        uzytkownik mogl je swiadomie wznowic.
        """
        rows = self.index.repository.resumable_jobs()
        count = 0
        for row in rows:
            if str(row["state"]) != JobState.RUNNING.value:
                continue
            self.index.repository.update_job_state(str(row["job_id"]), JobState.PAUSED)
            count += 1
        if count:
            log.info("runner.interrupted_jobs_marked", count=count)
        return count

    # --- watek roboczy ----------------------------------------------------

    def _worker(self) -> None:
        while not self._stopping.is_set():
            item = self._queue.get()
            if item is None:
                break
            self._run_job(item)
        log.info("runner.stopped")

    def _run_job(self, queued: QueuedJob) -> None:
        # Konfiguracja jest pobierana w chwili startu zadania, nie w chwili
        # utworzenia wykonawcy. Zrodla dodane po uruchomieniu aplikacji sa
        # dzieki temu widoczne bez restartu.
        if self._config_provider is not None:
            self.config = self._config_provider()
        sink = _SinkAdapter(self._progress_callbacks)
        job = IndexingJob(
            self.config,
            self.index,
            options=queued.options,
            control=queued.control,
            progress=sink,
            paths=self.paths,
        )
        queued.job_id = job.job_id
        with self._lock:
            self._current = job
            self._current_control = queued.control
        try:
            snapshot = job.run()
        except Exception as exc:
            log.error("runner.job_crashed", error_type=type(exc).__name__)
            snapshot = job.snapshot
            snapshot.state = JobState.FAILED
            snapshot.message = f"Nieoczekiwany błąd: {type(exc).__name__}."
        finally:
            with self._lock:
                self._current = None
                self._current_control = None
        self._last_snapshot = snapshot
        for callback in list(self._completion_callbacks):
            try:
                callback(snapshot)
            except Exception as exc:
                log.warning("runner.completion_callback_failed", error_type=type(exc).__name__)


__all__ = ["CompletionCallback", "JobRunner", "ProgressCallback", "QueuedJob"]
