"""Wybor strategii fragmentacji na podstawie zawartosci dokumentu.

Dokument moze byc czysto tekstowy, czysto tabelaryczny albo mieszany. Strategia
mieszana przepuszcza sekcje tabelaryczne przez fragmentator tabel, a reszte przez
fragmentator tekstu, i skleja wynik w jedna, ciagla numeracje.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from finddocs.chunking.base import ChunkingConfig, ChunkingStrategy
from finddocs.chunking.table_chunker import (
    TABLE_KINDS,
    TableChunkingStrategy,
    table_row_ratio,
)
from finddocs.chunking.text_chunker import TextChunkingStrategy
from finddocs.types import Chunk, ExtractedSection

#: Powyzej tego udzialu sekcji tabelarycznych dokument traktujemy jak tabele.
TABLE_DOMINANT_RATIO = 0.6

#: Rozszerzenia, dla ktorych zawsze uzywamy strategii tabelarycznej.
TABLE_EXTENSIONS = frozenset({".csv", ".tsv", ".xls", ".xlsx", ".xlsm", ".xlt", ".xltx", ".ods"})


class MixedChunkingStrategy(ChunkingStrategy):
    """Laczy fragmentacje tekstu i tabel w jednym dokumencie."""

    name = "mixed"

    def __init__(self, config: ChunkingConfig | None = None) -> None:
        super().__init__(config)
        self._text = TextChunkingStrategy(self.config)
        self._table = TableChunkingStrategy(self.config)

    def chunk(self, sections: Iterable[ExtractedSection]) -> Iterator[Chunk]:
        materialized = list(sections)
        ordinal = 0
        run: list[ExtractedSection] = []
        run_is_table = False

        def drain(items: list[ExtractedSection], is_table: bool) -> Iterator[Chunk]:
            nonlocal ordinal
            if not items:
                return
            engine: ChunkingStrategy = self._table if is_table else self._text
            for chunk in engine.chunk(items):
                chunk.ordinal = ordinal
                ordinal += 1
                yield chunk

        for section in materialized:
            is_table = section.kind in TABLE_KINDS
            if run and is_table != run_is_table:
                yield from drain(run, run_is_table)
                run = []
            run_is_table = is_table
            run.append(section)

        yield from drain(run, run_is_table)


def select_strategy(
    sections: list[ExtractedSection],
    config: ChunkingConfig,
    *,
    extension: str = "",
) -> ChunkingStrategy:
    """Dobiera strategie do dokumentu."""
    if extension.lower() in TABLE_EXTENSIONS:
        return TableChunkingStrategy(config)
    ratio = table_row_ratio(sections)
    if ratio >= TABLE_DOMINANT_RATIO:
        return TableChunkingStrategy(config)
    if ratio > 0.0:
        return MixedChunkingStrategy(config)
    return TextChunkingStrategy(config)


def chunk_document(
    sections: list[ExtractedSection],
    config: ChunkingConfig,
    *,
    extension: str = "",
) -> list[Chunk]:
    """Fragmentuje dokument wybrana automatycznie strategia."""
    strategy = select_strategy(sections, config, extension=extension)
    chunks = list(strategy.chunk(sections))
    for index, chunk in enumerate(chunks):
        chunk.ordinal = index
    return chunks


__all__ = [
    "TABLE_DOMINANT_RATIO",
    "TABLE_EXTENSIONS",
    "MixedChunkingStrategy",
    "chunk_document",
    "select_strategy",
]
