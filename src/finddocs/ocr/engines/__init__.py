"""Wymienne silniki OCR."""

from __future__ import annotations

from finddocs.ocr.engines.easyocr_engine import EasyOcrEngine
from finddocs.ocr.engines.rapidocr_engine import RapidOcrEngine
from finddocs.ocr.engines.remote_api import RemoteOcrEngine
from finddocs.ocr.engines.tesseract import TesseractEngine

__all__ = ["EasyOcrEngine", "RapidOcrEngine", "RemoteOcrEngine", "TesseractEngine"]
