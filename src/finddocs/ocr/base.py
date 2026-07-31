"""Interfejs silnika OCR i struktury wyniku.

Silniki sa wymienne. Aplikacja wybiera pierwszy dostępny wedlug listy priorytetow,
a informacja o tym, ktory silnik zadzialal, trafia do diagnostyki i raportu pokrycia.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from finddocs.types import CancellationToken

if TYPE_CHECKING:  # pragma: no cover - tylko dla kontroli typow
    from PIL.Image import Image


@dataclass(slots=True)
class OcrLine:
    """Pojedyncza rozpoznana linia tekstu."""

    text: str
    confidence: float | None = None
    box: tuple[int, int, int, int] | None = None


@dataclass(slots=True)
class OcrPageResult:
    """Wynik OCR dla jednej strony albo klatki obrazu."""

    page: int
    text: str
    confidence: float | None = None
    lines: list[OcrLine] = field(default_factory=list)
    engine: str = ""
    duration_seconds: float = 0.0
    rotated_degrees: int = 0

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass(slots=True)
class OcrDocumentResult:
    """Wynik OCR dla calego dokumentu."""

    pages: list[OcrPageResult] = field(default_factory=list)
    engine: str = ""
    engine_version: str = ""
    languages: list[str] = field(default_factory=list)
    dpi: int = 0
    truncated: bool = False
    from_cache: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(page.text for page in self.pages if page.text)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def confidence(self) -> float | None:
        values = [p.confidence for p in self.pages if p.confidence is not None]
        return sum(values) / len(values) if values else None

    @property
    def char_count(self) -> int:
        return sum(p.char_count for p in self.pages)


class OcrEngine(ABC):
    """Silnik rozpoznawania tekstu."""

    #: Krotka nazwa uzywana w konfiguracji i raportach.
    name: str = "abstract"

    #: Wyzszy priorytet wygrywa przy automatycznym wyborze.
    priority: int = 0

    #: Czy silnik potrafi wykryc i skorygowac obrot strony.
    supports_rotation: bool = False

    #: Czy silnik zwraca miare pewnosci rozpoznania.
    provides_confidence: bool = False

    @abstractmethod
    def is_available(self) -> bool:
        """Czy silnik da sie uruchomic w tym systemie."""

    def unavailable_reason(self) -> str:
        return ""

    @abstractmethod
    def version(self) -> str:
        """Wersja silnika, uzywana jako czesc klucza pamieci podrecznej."""

    @abstractmethod
    def supported_languages(self) -> list[str]:
        """Kody jezykow dostepne w tym silniku."""

    @abstractmethod
    def recognize(
        self,
        image: Image,
        *,
        languages: list[str],
        page: int = 1,
        cancel: CancellationToken | None = None,
    ) -> OcrPageResult:
        """Rozpoznaje tekst na jednym obrazie."""

    def warmup(self) -> None:
        """Wstepna inicjalizacja, zeby pierwsza strona nie byla wyraznie wolniejsza."""

    def close(self) -> None:
        """Zwalnia zasoby."""

    def describe(self) -> dict[str, Any]:
        available = self.is_available()
        return {
            "nazwa": self.name,
            "dostępny": available,
            "powod_niedostepnosci": "" if available else self.unavailable_reason(),
            "wersja": self.version() if available else "",
            "jezyki": self.supported_languages() if available else [],
            "korekta_obrotu": self.supports_rotation,
            "miara_pewnosci": self.provides_confidence,
        }


__all__ = ["OcrDocumentResult", "OcrEngine", "OcrLine", "OcrPageResult"]
