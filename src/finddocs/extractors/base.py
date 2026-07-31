"""Interfejs parsera formatu i wspolne narzedzia dla adapterow.

Kazdy parser dostaje sciezke do pliku w bezpiecznej przestrzeni tymczasowej oraz
kontekst (limity, token anulowania). Zwraca ``ExtractionResult`` z sekcjami tekstu,
metadanymi i ewentualnymi zalacznikami.

Parser nigdy nie rzuca surowego wyjatku biblioteki. Kazdy blad jest tlumaczony na
wyjatek z ``finddocs.errors``, dzieki czemu raport pokrycia moze go skategoryzowac.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from finddocs.types import (
    CancellationToken,
    ExtractionResult,
    SupportLevel,
)


@dataclass(slots=True)
class ExtractionContext:
    """Parametry i limity przekazywane parserowi."""

    max_bytes: int = 512 * 1024 * 1024
    max_chars: int = 60_000_000
    timeout_seconds: float = 300.0
    cancel: CancellationToken | None = None
    extract_attachments: bool = True
    office_com_enabled: bool = True
    office_com_timeout_seconds: float = 90.0
    csv_max_rows: int = 500_000
    sheet_max_rows: int = 500_000
    started_at: float = field(default_factory=time.monotonic)

    def check_cancelled(self) -> None:
        if self.cancel is not None:
            self.cancel.raise_if_cancelled()

    def check_timeout(self) -> None:
        from finddocs.errors import ExtractionTimeoutError

        if time.monotonic() - self.started_at > self.timeout_seconds:
            raise ExtractionTimeoutError(
                f"Odczyt dokumentu przekroczył limit {self.timeout_seconds:.0f} s."
            )

    def checkpoint(self) -> None:
        """Wywolywane w petlach parsera: sprawdza anulowanie i limit czasu."""
        self.check_cancelled()
        self.check_timeout()


class Extractor(ABC):
    """Adapter jednego formatu albo rodziny formatow."""

    #: Krotka, stabilna nazwa uzywana w metadanych i raportach.
    name: str = "abstract"

    #: Rozszerzenia obslugiwane przez adapter, malymi literami, z kropka.
    extensions: tuple[str, ...] = ()

    #: Typy MIME obslugiwane przez adapter.
    mime_types: tuple[str, ...] = ()

    #: Deklarowany poziom wsparcia.
    support_level: SupportLevel = SupportLevel.FULL

    #: Wyzszy priorytet wygrywa, gdy kilka adapterow obsluguje ten sam format.
    priority: int = 100

    def is_available(self) -> bool:
        """Czy adapter da sie uzyc w tym systemie (np. czy jest zainstalowany Office)."""
        return True

    def unavailable_reason(self) -> str:
        """Opis powodu niedostepnosci, pokazywany w diagnostyce."""
        return ""

    def supports(self, path: Path, mime_type: str | None) -> bool:
        suffix = path.suffix.lower()
        if suffix and suffix in self.extensions:
            return True
        return bool(mime_type and mime_type in self.mime_types)

    @abstractmethod
    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        """Wyciaga tekst i metadane z pliku."""

    def describe(self) -> dict[str, object]:
        return {
            "nazwa": self.name,
            "rozszerzenia": list(self.extensions),
            "poziom_wsparcia": self.support_level.value,
            "dostępny": self.is_available(),
            "powod_niedostepnosci": self.unavailable_reason(),
        }


__all__ = ["ExtractionContext", "Extractor"]
