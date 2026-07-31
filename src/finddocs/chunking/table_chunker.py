"""Fragmentacja dokumentow tabelarycznych: CSV, XLS, XLSX i tabel w dokumentach.

Caly plik CSV jako jeden fragment bylby bezuzyteczny: pojedynczy rekord zginalby
w tysiacach innych. Dlatego wiersze sa grupowane w male paczki, a kazda paczka
dostaje naglowek kolumn. Zapytanie o konkretna transakcje trafia wtedy w fragment,
ktory zawiera ten wiersz i nazwy kolumn potrzebne do zrozumienia wartosci.

Bardzo dlugi wiersz (np. rekord z dziesiatkami kolumn) jest indeksowany osobno,
zeby nie rozmyc go w paczce.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from finddocs.chunking.base import ChunkingStrategy, build_chunk
from finddocs.types import Chunk, ExtractedSection, TextOrigin

TABLE_KINDS = frozenset({"table_row", "table_header", "sheet"})

#: Wiersz dluzszy niz ta wartosc trafia do wlasnego fragmentu.
STANDALONE_ROW_CHARS = 700


class TableChunkingStrategy(ChunkingStrategy):
    """Grupowanie wierszy tabeli w fragmenty z naglowkiem kolumn."""

    name = "table"

    def chunk(self, sections: Iterable[ExtractedSection]) -> Iterator[Chunk]:
        config = self.config
        ordinal = 0
        produced = 0
        sheet: str | None = None
        header: str | None = None
        sheet_label: str | None = None
        pending: list[ExtractedSection] = []

        def flush() -> Iterator[Chunk]:
            nonlocal pending, ordinal, produced
            if not pending:
                return
            rows = [s.text.strip() for s in pending if s.text.strip()]
            if not rows:
                pending = []
                return
            prefix_parts = [p for p in (sheet_label, header if config.table_include_header else None) if p]
            body = "\n".join(rows)
            text = "\n".join([*prefix_parts, body]) if prefix_parts else body
            row_numbers = [s.row for s in pending if s.row is not None]
            yield build_chunk(
                ordinal,
                text,
                origin=pending[0].origin,
                ocr_confidence=pending[0].ocr_confidence,
                page=pending[0].page,
                sheet=sheet,
                row_start=min(row_numbers) if row_numbers else None,
                row_end=max(row_numbers) if row_numbers else None,
                heading=header,
                section_kind="table_row",
                char_start=0,
                char_end=len(text),
            )
            ordinal += 1
            produced += 1
            pending = []

        for section in sections:
            kind = section.kind
            if kind == "sheet":
                yield from flush()
                sheet = section.sheet or section.text.strip() or sheet
                sheet_label = section.text.strip() or (f"Arkusz: {sheet}" if sheet else None)
                header = None
                continue

            if kind == "table_header":
                yield from flush()
                header = section.text.strip() or None
                if section.sheet:
                    sheet = section.sheet
                continue

            if kind != "table_row":
                yield from flush()
                for chunk in self._chunk_free_text(section, ordinal, sheet, header):
                    yield chunk
                    ordinal += 1
                    produced += 1
                    if produced >= config.max_chunks:
                        return
                continue

            if section.sheet and section.sheet != sheet:
                yield from flush()
                sheet = section.sheet
                sheet_label = f"Arkusz: {sheet}"

            row_header = section.heading or header
            if row_header and row_header != header:
                yield from flush()
                header = row_header

            if len(section.text) >= STANDALONE_ROW_CHARS:
                yield from flush()
                pending = [section]
                yield from flush()
                if produced >= config.max_chunks:
                    return
                continue

            pending.append(section)
            current_chars = sum(len(s.text) for s in pending)
            if (
                len(pending) >= config.table_rows_per_chunk
                or current_chars >= config.target_chars
            ):
                yield from flush()
                if produced >= config.max_chunks:
                    return

        yield from flush()

    def _chunk_free_text(
        self,
        section: ExtractedSection,
        ordinal: int,
        sheet: str | None,
        header: str | None,
    ) -> Iterator[Chunk]:
        """Sekcja tekstowa w pliku tabelarycznym, np. komentarz nad tabela."""
        body = section.text.strip()
        if not body:
            return
        yield build_chunk(
            ordinal,
            body,
            origin=section.origin,
            ocr_confidence=section.ocr_confidence,
            page=section.page,
            sheet=sheet,
            heading=header,
            section_kind=section.kind or "text",
            char_start=0,
            char_end=len(body),
        )


def has_table_sections(sections: Iterable[ExtractedSection]) -> bool:
    """Czy w zbiorze sekcji sa dane tabelaryczne."""
    return any(s.kind in TABLE_KINDS for s in sections)


def table_row_ratio(sections: list[ExtractedSection]) -> float:
    """Udzial sekcji tabelarycznych. Uzywany przy wyborze strategii."""
    if not sections:
        return 0.0
    table = sum(1 for s in sections if s.kind in TABLE_KINDS)
    return table / len(sections)


__all__ = [
    "STANDALONE_ROW_CHARS",
    "TABLE_KINDS",
    "TableChunkingStrategy",
    "TextOrigin",
    "has_table_sections",
    "table_row_ratio",
]
