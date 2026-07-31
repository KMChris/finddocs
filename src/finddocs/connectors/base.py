"""Interfejs zrodla dokumentow.

Konektor odpowiada za trzy rzeczy: wyliczenie obiektow w zrodle, pobranie
pojedynczego pliku i wykrycie zmian. Nigdy nie pobiera calego zbioru naraz.
Enumeracja jest leniwa, wiec indeksowanie moze ruszyc po pierwszym pliku.
"""

from __future__ import annotations

import hashlib
import shutil
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from finddocs.errors import StorageSpaceError
from finddocs.types import CancellationToken, FetchedFile, SourceItem, SourceKind


@dataclass(slots=True)
class ConnectionStatus:
    """Wynik testu polaczenia ze zrodlem."""

    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScanCursor:
    """Pozycja w enumeracji zrodla, pozwalajaca wznowic przerwane skanowanie."""

    token: str | None = None
    """Nieprzezroczysty znacznik konektora, np. odsylacz nextLink z Graph."""

    visited: int = 0
    complete: bool = False

    def to_json(self) -> str:
        import json

        return json.dumps(
            {"token": self.token, "visited": self.visited, "complete": self.complete},
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str | None) -> ScanCursor:
        if not raw:
            return cls()
        import json

        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls(
            token=data.get("token"),
            visited=int(data.get("visited", 0) or 0),
            complete=bool(data.get("complete", False)),
        )


class SourceConnector(ABC):
    """Zrodlo dokumentow."""

    #: Rodzaj zrodla.
    kind: SourceKind

    #: Identyfikator konfiguracji zrodla.
    source_id: str

    #: Etykieta pokazywana uzytkownikowi.
    label: str

    @abstractmethod
    def test_connection(self) -> ConnectionStatus:
        """Sprawdza, czy zrodlo jest osiagalne i skonfigurowane poprawnie."""

    @abstractmethod
    def iter_items(
        self,
        *,
        cursor: ScanCursor | None = None,
        cancel: CancellationToken | None = None,
    ) -> Iterator[SourceItem]:
        """Wylicza pliki w zrodle. Iterator jest leniwy."""

    @abstractmethod
    def fetch(
        self,
        item: SourceItem,
        destination: Path,
        *,
        cancel: CancellationToken | None = None,
    ) -> FetchedFile:
        """Pobiera pojedynczy plik do wskazanego katalogu."""

    def cursor(self) -> ScanCursor:
        """Biezaca pozycja enumeracji."""
        return ScanCursor()

    def open_url(self, item: SourceItem) -> str | None:
        """Adres pozwalajacy otworzyc dokument w przegladarce albo aplikacji."""
        return item.web_url

    def folder_url(self, item: SourceItem) -> str | None:
        """Adres katalogu, w ktorym lezy dokument."""
        return item.parent_url

    def describe(self) -> dict[str, Any]:
        return {"rodzaj": self.kind.value, "identyfikator": self.source_id, "etykieta": self.label}

    def close(self) -> None:
        """Zwalnia zasoby, np. sesje HTTP."""


def sha256_of_file(path: Path, *, block: int = 1024 * 1024) -> str:
    """Skrot pliku uzywany do wykrywania zmian i jako klucz pamieci OCR."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(block), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_space_for(destination: Path, size: int, *, safety: float = 2.0) -> None:
    """Sprawdza, czy na dysku wystarczy miejsca na pobranie pliku."""
    if size <= 0:
        return
    target = destination
    while not target.exists() and target.parent != target:
        target = target.parent
    free = shutil.disk_usage(target).free
    required = int(size * safety)
    if free < required:
        raise StorageSpaceError(
            "Za malo miejsca w przestrzeni tymczasowej, zeby pobrac plik. "
            f"Potrzeba okolo {required // (1024 * 1024)} MB, "
            f"dostepne {free // (1024 * 1024)} MB.",
            details={"required": required, "available": free},
        )


__all__ = [
    "ConnectionStatus",
    "ScanCursor",
    "SourceConnector",
    "ensure_space_for",
    "sha256_of_file",
]
