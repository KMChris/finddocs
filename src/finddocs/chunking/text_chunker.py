"""Podzial tekstu ciaglego na fragmenty z zachowaniem kontekstu.

Algorytm laczy kolejne akapity, dopoki miesci sie w docelowym rozmiarze. Gdy pojedynczy
akapit jest za dlugi, tnie go na granicy zdania, a w ostatecznosci na granicy slowa.
Kolejne fragmenty zachodza na siebie o ustalona liczbe znakow, zeby zdanie na styku
dwoch fragmentow nie stracilo kontekstu.

Zmiana strony albo naglowka konczy biezacy fragment, o ile ma juz sensowna dlugosc.
Dzieki temu fragment nie miesza tresci z dwoch rozdzialow.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from finddocs.chunking.base import ChunkingStrategy, build_chunk
from finddocs.types import Chunk, ExtractedSection, TextOrigin

#: Granica zdania: znak konca zdania, spacja, wielka litera albo cyfra.
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ0-9])")
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


def split_sentences(text: str) -> list[str]:
    """Dzieli tekst na zdania. Pomija elementy puste."""
    return [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]


def split_paragraphs(text: str) -> list[str]:
    """Dzieli tekst na akapity po pustych liniach."""
    return [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]


def tail_of(text: str, chars: int) -> str:
    """Koncowka tekstu przycieta do granicy slowa. Uzywana jako naklodka."""
    if chars <= 0 or not text:
        return ""
    if len(text) <= chars:
        return text
    tail = text[-chars:]
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else tail


class _Buffer:
    """Bufor skladajacy kolejne kawalki tekstu w jeden fragment."""

    __slots__ = ("confidences", "heading", "origin", "page", "parts", "size", "start")

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.size = 0
        self.start = 0
        self.page: int | None = None
        self.heading: str | None = None
        self.origin: TextOrigin = TextOrigin.NATIVE
        self.confidences: list[float] = []

    def is_empty(self) -> bool:
        return not self.parts

    def text(self) -> str:
        return "\n".join(self.parts).strip()

    def add(self, piece: str) -> None:
        self.parts.append(piece)
        self.size += len(piece) + 1

    def note_origin(self, origin: TextOrigin) -> None:
        if origin is self.origin:
            return
        if self.origin is TextOrigin.NATIVE and not self.parts:
            self.origin = origin
        elif origin is not TextOrigin.NATIVE or self.origin is not TextOrigin.NATIVE:
            self.origin = TextOrigin.MIXED if self.parts else origin

    def confidence(self) -> float | None:
        if not self.confidences:
            return None
        return sum(self.confidences) / len(self.confidences)

    def reset(self, start: int) -> None:
        self.parts = []
        self.size = 0
        self.start = start
        self.confidences = []
        self.origin = TextOrigin.NATIVE


class TextChunkingStrategy(ChunkingStrategy):
    """Fragmentacja tekstu ciaglego z nakladaniem."""

    name = "text"

    def chunk(self, sections: Iterable[ExtractedSection]) -> Iterator[Chunk]:
        config = self.config
        buffer = _Buffer()
        ordinal = 0
        offset = 0
        produced = 0
        pending_overlap = ""

        def emit() -> Chunk | None:
            nonlocal ordinal
            body = buffer.text()
            if not body:
                return None
            chunk = build_chunk(
                ordinal,
                body,
                origin=buffer.origin,
                ocr_confidence=buffer.confidence(),
                page=buffer.page,
                heading=buffer.heading,
                section_kind="text",
                char_start=buffer.start,
                char_end=buffer.start + len(body),
            )
            ordinal += 1
            return chunk

        for section in sections:
            body = section.text.strip()
            if not body:
                continue

            boundary = (
                section.page is not None and section.page != buffer.page
            ) or section.heading != buffer.heading
            if boundary and buffer.size >= config.min_chars:
                chunk = emit()
                if chunk is not None:
                    yield chunk
                    produced += 1
                    if produced >= config.max_chunks:
                        return
                pending_overlap = tail_of(chunk.text if chunk else "", config.overlap_chars)
                buffer.reset(offset)

            if section.page is not None:
                buffer.page = section.page
            buffer.heading = section.heading
            buffer.note_origin(section.origin)
            if section.ocr_confidence is not None:
                buffer.confidences.append(section.ocr_confidence)

            for paragraph in split_paragraphs(body) or [body]:
                for piece in self._split_oversized(paragraph):
                    if buffer.is_empty():
                        buffer.start = max(0, offset - len(pending_overlap))
                        if pending_overlap:
                            buffer.add(pending_overlap)
                            pending_overlap = ""
                    elif buffer.size + len(piece) + 1 > config.target_chars:
                        chunk = emit()
                        if chunk is not None:
                            yield chunk
                            produced += 1
                            if produced >= config.max_chunks:
                                return
                            pending_overlap = tail_of(chunk.text, config.overlap_chars)
                        page, heading = buffer.page, buffer.heading
                        origin, confidences = buffer.origin, list(buffer.confidences)
                        buffer.reset(max(0, offset - len(pending_overlap)))
                        buffer.page, buffer.heading = page, heading
                        buffer.origin, buffer.confidences = origin, confidences
                        if pending_overlap:
                            buffer.add(pending_overlap)
                            pending_overlap = ""

                    buffer.add(piece)
                    offset += len(piece) + 1

        chunk = emit()
        if chunk is not None and len(chunk.text) >= min(config.min_chars, len(chunk.text)):
            yield chunk

    def _split_oversized(self, paragraph: str) -> list[str]:
        """Tnie zbyt dlugi akapit na kawalki mieszczace sie w limicie."""
        config = self.config
        if len(paragraph) <= config.max_chars:
            return [paragraph]

        pieces: list[str] = []
        for sentence in split_sentences(paragraph) or [paragraph]:
            if len(sentence) <= config.max_chars:
                pieces.append(sentence)
                continue
            current: list[str] = []
            length = 0
            for word in sentence.split(" "):
                if length + len(word) + 1 > config.target_chars and current:
                    pieces.append(" ".join(current))
                    current = []
                    length = 0
                current.append(word)
                length += len(word) + 1
            if current:
                pieces.append(" ".join(current))
        return [p for p in pieces if p]


__all__ = ["TextChunkingStrategy", "split_paragraphs", "split_sentences", "tail_of"]
