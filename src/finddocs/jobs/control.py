"""Sterowanie zadaniem w tle: anulowanie, pauza i wznowienie.

``JobControl`` implementuje protokol ``CancellationToken``, wiec ten sam obiekt
mozna przekazac do parsera, OCR i dostawcy embeddingow. Pauza jest realizowana
przez zdarzenie: watek roboczy czeka na nim w bezpiecznych punktach, miedzy
dokumentami i miedzy stronami OCR, nigdy w srodku transakcji bazy.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from finddocs.errors import JobCancelledError


class JobControl:
    """Wspolny obiekt sterujacy dla jednego zadania."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._resume = threading.Event()
        self._resume.set()
        self._paused_since: float | None = None
        self._paused_total = 0.0
        self._lock = threading.Lock()

    # --- anulowanie -------------------------------------------------------

    def cancel(self) -> None:
        self._cancelled.set()
        self._resume.set()

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def raise_if_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise JobCancelledError()

    # --- pauza ------------------------------------------------------------

    def pause(self) -> None:
        with self._lock:
            if self._resume.is_set():
                self._paused_since = time.monotonic()
            self._resume.clear()

    def resume(self) -> None:
        with self._lock:
            if self._paused_since is not None:
                self._paused_total += time.monotonic() - self._paused_since
                self._paused_since = None
            self._resume.set()

    @property
    def is_paused(self) -> bool:
        return not self._resume.is_set()

    @property
    def paused_seconds(self) -> float:
        with self._lock:
            extra = time.monotonic() - self._paused_since if self._paused_since else 0.0
            return self._paused_total + extra

    def wait_if_paused(self, poll: float = 0.2) -> None:
        """Blokuje watek roboczy, dopoki zadanie jest wstrzymane."""
        while not self._resume.wait(timeout=poll):
            if self._cancelled.is_set():
                raise JobCancelledError()
        if self._cancelled.is_set():
            raise JobCancelledError()

    def checkpoint(self) -> None:
        """Bezpieczny punkt: sprawdza anulowanie i obsluguje pauze."""
        self.raise_if_cancelled()
        if self.is_paused:
            self.wait_if_paused()

    def reset(self) -> None:
        self._cancelled.clear()
        self._resume.set()
        self._paused_since = None
        self._paused_total = 0.0


@dataclass(slots=True)
class RetryPolicy:
    """Polityka ponawiania operacji przejsciowych."""

    max_attempts: int = 3
    base_delay: float = 2.0
    max_delay: float = 60.0
    multiplier: float = 2.0

    def delay_for(self, attempt: int) -> float:
        """Opoznienie przed proba numer ``attempt`` (liczac od 1)."""
        if attempt <= 1:
            return 0.0
        raw = self.base_delay * (self.multiplier ** (attempt - 2))
        return min(self.max_delay, raw)

    def sleep(self, attempt: int, control: JobControl | None = None) -> None:
        """Czeka wymagany czas, reagujac na anulowanie."""
        delay = self.delay_for(attempt)
        if delay <= 0:
            return
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline:
            if control is not None:
                control.raise_if_cancelled()
            time.sleep(min(0.25, deadline - time.monotonic()))


__all__ = ["JobControl", "RetryPolicy"]
