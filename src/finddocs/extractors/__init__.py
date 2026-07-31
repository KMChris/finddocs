"""Warstwa ekstrakcji: wykrywanie typu pliku, rejestr parserow, adaptery formatow."""

from __future__ import annotations

from finddocs.extractors.base import ExtractionContext, Extractor
from finddocs.extractors.detect import FileTypeInfo, detect_file_type
from finddocs.extractors.registry import ExtractorRegistry, build_default_registry

__all__ = [
    "ExtractionContext",
    "Extractor",
    "ExtractorRegistry",
    "FileTypeInfo",
    "build_default_registry",
    "detect_file_type",
]
