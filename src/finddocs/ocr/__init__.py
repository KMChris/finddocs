"""Rozpoznawanie tekstu: kwalifikacja dokumentow i wymienne silniki OCR."""

from __future__ import annotations

from finddocs.ocr.base import OcrDocumentResult, OcrEngine, OcrPageResult
from finddocs.ocr.detector import OcrDecision, OcrReason, can_rasterize, decide
from finddocs.ocr.service import OcrService, describe_engines

__all__ = [
    "OcrDecision",
    "OcrDocumentResult",
    "OcrEngine",
    "OcrPageResult",
    "OcrReason",
    "OcrService",
    "can_rasterize",
    "decide",
    "describe_engines",
]
