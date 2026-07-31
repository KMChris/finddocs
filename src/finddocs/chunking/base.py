"""Interfejs strategii fragmentacji i wspolne narzedzia.

Fragment to jednostka indeksowania. Kazdy fragment zna swoj dokument zrodlowy,
kolejnosc, pochodzenie tekstu i, jesli to mozliwe, strone albo wiersz.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from finddocs.normalization.pipeline import normalize
from finddocs.types import Chunk, ExtractedSection, TextOrigin


@dataclass(slots=True)
class ChunkingConfig:
    """Parametry podzialu na fragmenty."""

    target_chars: int = 1100
    overlap_chars: int = 180
    min_chars: int = 120
    max_chars: int = 2200
    table_rows_per_chunk: int = 12
    table_include_header: bool = True
    max_chunks: int = 20000

    def clamp(self) -> ChunkingConfig:
        """Poprawia wartosci niespojne, zeby algorytm nie wpadl w petle."""
        target = max(200, self.target_chars)
        maximum = max(target + 100, self.max_chars)
        overlap = min(max(0, self.overlap_chars), target // 2)
        minimum = min(max(20, self.min_chars), target)
        return ChunkingConfig(
            target_chars=target,
            overlap_chars=overlap,
            min_chars=minimum,
            max_chars=maximum,
            table_rows_per_chunk=max(1, self.table_rows_per_chunk),
            table_include_header=self.table_include_header,
            max_chunks=max(1, self.max_chunks),
        )


class ChunkingStrategy(ABC):
    """Strategia podzialu sekcji dokumentu na fragmenty."""

    name: str = "abstract"

    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self.config = (config or ChunkingConfig()).clamp()

    @abstractmethod
    def chunk(self, sections: Iterable[ExtractedSection]) -> Iterator[Chunk]: ...


def build_chunk(
    ordinal: int,
    text: str,
    *,
    origin: TextOrigin = TextOrigin.NATIVE,
    ocr_confidence: float | None = None,
    page: int | None = None,
    sheet: str | None = None,
    row_start: int | None = None,
    row_end: int | None = None,
    heading: str | None = None,
    section_kind: str = "text",
    char_start: int = 0,
    char_end: int = 0,
) -> Chunk:
    """Tworzy fragment wraz z wszystkimi reprezentacjami wyszukiwawczymi."""
    header_prefix = f"{heading}\n" if heading else ""
    normalized = normalize(header_prefix + text)
    display = normalize(text).display
    return Chunk(
        ordinal=ordinal,
        text=display,
        search_text=normalized.search,
        folded_text=normalized.folded,
        normalized_tokens=normalized.token_text,
        origin=origin,
        ocr_confidence=ocr_confidence,
        page=page,
        sheet=sheet,
        row_start=row_start,
        row_end=row_end,
        heading=heading,
        section_kind=section_kind,
        char_start=char_start,
        char_end=char_end if char_end else char_start + len(text),
    )


__all__ = ["ChunkingConfig", "ChunkingStrategy", "build_chunk"]
