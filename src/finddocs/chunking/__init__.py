"""Podzial dokumentow na fragmenty indeksowane."""

from __future__ import annotations

from finddocs.chunking.base import ChunkingConfig, ChunkingStrategy, build_chunk
from finddocs.chunking.strategy import (
    MixedChunkingStrategy,
    chunk_document,
    select_strategy,
)
from finddocs.chunking.table_chunker import TableChunkingStrategy
from finddocs.chunking.text_chunker import TextChunkingStrategy

__all__ = [
    "ChunkingConfig",
    "ChunkingStrategy",
    "MixedChunkingStrategy",
    "TableChunkingStrategy",
    "TextChunkingStrategy",
    "build_chunk",
    "chunk_document",
    "select_strategy",
]
