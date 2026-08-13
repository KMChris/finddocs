"""Rozpoznawanie tekstu: kwalifikacja dokumentow i wymienne silniki OCR."""

from __future__ import annotations

from finddocs.ocr.base import OcrDocumentResult, OcrEngine, OcrPageResult
from finddocs.ocr.detector import OcrDecision, OcrReason, can_rasterize, decide
from finddocs.ocr.service import (
    REMOTE_ENGINE_NAME,
    OcrService,
    build_remote_engine,
    describe_engines,
)

__all__ = [
    "REMOTE_ENGINE_NAME",
    "OcrDecision",
    "OcrDocumentResult",
    "OcrEngine",
    "OcrPageResult",
    "OcrReason",
    "OcrService",
    "build_remote_engine",
    "can_rasterize",
    "decide",
    "describe_engines",
]
