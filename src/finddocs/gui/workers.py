"""Praca w tle dla interfejsu graficznego.

Watek glowny Qt nie wykonuje zadnej pracy poza rysowaniem. Wyszukiwanie idzie do
puli watkow, indeksowanie do wlasnego watku ``JobRunner``. Zdarzenia z watkow
roboczych trafiaja do interfejsu przez sygnaly Qt, ktore sa dostarczane w kolejce
do watku glownego.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from finddocs.errors import FindDocsError, SearchCancelledError
from finddocs.logging_setup import get_logger
from finddocs.types import ProgressSnapshot, SearchRequest, SearchResponse

log = get_logger(__name__)


class CancellationFlag:
    """Prosty token anulowania dla operacji w puli watkow."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise SearchCancelledError()


class _TaskSignals(QObject):
    finished = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal()


class SearchTask(QRunnable):
    """Jedno wyszukiwanie wykonywane poza watkiem interfejsu."""

    def __init__(
        self,
        search_callable: Callable[[SearchRequest, CancellationFlag], SearchResponse],
        request: SearchRequest,
    ) -> None:
        super().__init__()
        self.signals = _TaskSignals()
        self._callable = search_callable
        self._request = request
        self.token = CancellationFlag()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            response = self._callable(self._request, self.token)
        except SearchCancelledError:
            self.signals.cancelled.emit()
            return
        except FindDocsError as exc:
            log.warning("gui.search_failed", code=exc.code)
            self.signals.failed.emit(exc.code, exc.user_message)
            return
        except Exception as exc:  # noqa: BLE001 - interfejs musi pokazac komunikat
            log.exception("gui.search_crashed")
            self.signals.failed.emit("FD-7000", f"Nieoczekiwany blad: {type(exc).__name__}.")
            return
        if self.token.is_cancelled():
            self.signals.cancelled.emit()
            return
        self.signals.finished.emit(response)


class CallableTask(QRunnable):
    """Dowolna operacja w tle zwracajaca wynik do interfejsu."""

    def __init__(self, work: Callable[[], Any], label: str = "operacja") -> None:
        super().__init__()
        self.signals = _TaskSignals()
        self._work = work
        self._label = label
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            result = self._work()
        except FindDocsError as exc:
            log.warning("gui.task_failed", label=self._label, code=exc.code)
            self.signals.failed.emit(exc.code, exc.user_message)
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("gui.task_crashed", label=self._label)
            self.signals.failed.emit("FD-0000", f"Nieoczekiwany blad: {type(exc).__name__}.")
            return
        self.signals.finished.emit(result)


class ProgressBridge(QObject):
    """Most miedzy watkiem zadania a interfejsem.

    ``JobRunner`` wola ``publish`` z watku roboczego. Sygnal Qt przenosi migawke
    do watku glownego, gdzie widok moze bezpiecznie odswiezyc kontrolki.
    """

    progress = Signal(object)
    completed = Signal(object)

    def publish(self, snapshot: ProgressSnapshot) -> None:
        self.progress.emit(snapshot)

    def publish_completion(self, snapshot: ProgressSnapshot) -> None:
        self.completed.emit(snapshot)


def thread_pool() -> QThreadPool:
    """Pula watkow uzywana przez interfejs."""
    pool = QThreadPool.globalInstance()
    if pool.maxThreadCount() < 4:
        pool.setMaxThreadCount(4)
    return pool


__all__ = [
    "CallableTask",
    "CancellationFlag",
    "ProgressBridge",
    "SearchTask",
    "thread_pool",
]
