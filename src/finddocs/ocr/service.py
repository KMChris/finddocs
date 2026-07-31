"""Uslugi OCR: wybor silnika, rasteryzacja stron, limity i pamiec podreczna.

Przetwarzanie idzie strona po stronie, zeby zuzycie pamieci nie zalezalo od liczby
stron dokumentu. Kazda strona moze zostac przerwana przez uzytkownika. Wynik jest
zapisywany w pamieci podrecznej pod kluczem (skrot tresci, silnik, wersja, dpi),
wiec ponowne skanowanie niezmienionego pliku nie uruchamia OCR jeszcze raz.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from finddocs.config import OcrSettings
from finddocs.errors import OcrCancelledError, OcrEngineUnavailableError, OcrError
from finddocs.extractors.detect import FileTypeInfo
from finddocs.logging_setup import get_logger
from finddocs.ocr.base import OcrDocumentResult, OcrEngine, OcrPageResult
from finddocs.ocr.engines.easyocr_engine import EasyOcrEngine
from finddocs.ocr.engines.rapidocr_engine import RapidOcrEngine
from finddocs.ocr.engines.tesseract import TesseractEngine
from finddocs.types import CancellationToken, ExtractedSection, TextOrigin

if TYPE_CHECKING:  # pragma: no cover
    from PIL.Image import Image

    from finddocs.indexing.repository import Repository

log = get_logger(__name__)

#: Kolejnosc prob przy ustawieniu engine="auto".
AUTO_ENGINE_ORDER: tuple[str, ...] = ("tesseract", "easyocr", "rapidocr")

MIN_RENDER_DPI = 120
MAX_RENDER_DPI = 400


@dataclass(slots=True)
class OcrEngineInfo:
    """Informacja o dostepnosci silnika, pokazywana w diagnostyce."""

    name: str
    available: bool
    reason: str
    version: str
    languages: list[str]
    polish_supported: bool


def build_engines(settings: OcrSettings, model_dir: Path | None = None) -> list[OcrEngine]:
    """Tworzy liste silnikow w kolejnosci preferencji."""
    tesseract = TesseractEngine(executable=settings.tesseract_path)
    easy = EasyOcrEngine(model_dir=model_dir, allow_download=False)
    rapid = RapidOcrEngine()
    by_name: dict[str, OcrEngine] = {
        tesseract.name: tesseract,
        easy.name: easy,
        rapid.name: rapid,
    }
    if settings.engine in by_name:
        preferred = by_name.pop(settings.engine)
        return [preferred, *by_name.values()]
    return [by_name[name] for name in AUTO_ENGINE_ORDER if name in by_name]


def describe_engines(settings: OcrSettings, model_dir: Path | None = None) -> list[OcrEngineInfo]:
    """Opis wszystkich silnikow dla ekranu diagnostyki."""
    result: list[OcrEngineInfo] = []
    for engine in build_engines(settings, model_dir):
        available = engine.is_available()
        polish = bool(getattr(engine, "has_polish", lambda: False)()) if available else False
        result.append(
            OcrEngineInfo(
                name=engine.name,
                available=available,
                reason="" if available else engine.unavailable_reason(),
                version=engine.version() if available else "",
                languages=engine.supported_languages() if available else [],
                polish_supported=polish,
            )
        )
    return result


class OcrService:
    """Uruchamia OCR dla dokumentow, ktore tego wymagaja."""

    def __init__(
        self,
        settings: OcrSettings,
        *,
        repository: Repository | None = None,
        model_dir: Path | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self._engines = build_engines(settings, model_dir)
        self._selected: OcrEngine | None = None
        self.warnings: list[str] = []

    # --- wybor silnika ----------------------------------------------------

    @property
    def engine(self) -> OcrEngine:
        if self._selected is not None:
            return self._selected
        problems: list[str] = []
        for candidate in self._engines:
            if candidate.is_available():
                self._selected = candidate
                polish = bool(getattr(candidate, "has_polish", lambda: False)())
                if not polish:
                    message = (
                        f"Silnik OCR {candidate.name} nie ma modelu dla jezyka polskiego. "
                        "Rozpoznane teksty moga gubic znaki diakrytyczne. "
                        "Wyszukiwanie dziala mimo to, bo indeks sklada znaki."
                    )
                    self.warnings.append(message)
                    log.warning("ocr.engine_without_polish", engine=candidate.name)
                log.info("ocr.engine_selected", engine=candidate.name, version=candidate.version())
                return candidate
            problems.append(f"{candidate.name}: {candidate.unavailable_reason()}")
        raise OcrEngineUnavailableError(
            "Zaden silnik OCR nie jest dostepny. Zainstaluj Tesseract OCR albo "
            "dodatek 'ocr-rapid'.",
            details={"probowano": problems},
        )

    @property
    def engine_available(self) -> bool:
        return any(candidate.is_available() for candidate in self._engines)

    def engine_name(self) -> str:
        return self.engine.name if self.engine_available else ""

    # --- rasteryzacja -----------------------------------------------------

    def _render_pages(
        self,
        path: Path,
        info: FileTypeInfo,
        pages: list[int] | None,
        cancel: CancellationToken | None,
    ) -> Iterator[tuple[int, Image]]:
        dpi = max(MIN_RENDER_DPI, min(MAX_RENDER_DPI, self.settings.render_dpi))
        if info.mime_type == "application/pdf":
            from finddocs.extractors.pdf import pdf_page_count, render_pdf_page

            total = pdf_page_count(path)
            wanted = pages or list(range(1, total + 1))
            for page in wanted[: self.settings.max_pages_per_document]:
                if cancel is not None and cancel.is_cancelled():
                    raise OcrCancelledError()
                if page < 1 or page > total:
                    continue
                yield page, render_pdf_page(
                    path, page - 1, dpi=dpi, max_pixels=self.settings.max_image_pixels
                )
            return

        from finddocs.extractors.image import load_image_frames

        index = 0
        for frame in load_image_frames(
            path,
            max_frames=self.settings.max_pages_per_document,
            max_pixels=self.settings.max_image_pixels,
        ):
            if cancel is not None and cancel.is_cancelled():
                raise OcrCancelledError()
            index += 1
            yield index, frame

    # --- glowne wejscie ---------------------------------------------------

    def run(
        self,
        path: Path,
        info: FileTypeInfo,
        *,
        content_sha256: str | None = None,
        pages: list[int] | None = None,
        cancel: CancellationToken | None = None,
    ) -> OcrDocumentResult:
        """Wykonuje OCR dokumentu. Zwraca wynik zlozony ze stron."""
        engine = self.engine
        dpi = max(MIN_RENDER_DPI, min(MAX_RENDER_DPI, self.settings.render_dpi))
        version = engine.version()

        cached = self._load_cache(content_sha256, engine.name, version, dpi)
        if cached is not None:
            return cached

        result = OcrDocumentResult(
            engine=engine.name,
            engine_version=version,
            languages=list(self.settings.languages),
            dpi=dpi,
        )
        processed = 0
        started = time.monotonic()
        for page_number, image in self._render_pages(path, info, pages, cancel):
            if cancel is not None and cancel.is_cancelled():
                raise OcrCancelledError()
            deadline = self.settings.page_timeout_seconds
            page_started = time.monotonic()
            try:
                page_result = engine.recognize(
                    image,
                    languages=list(self.settings.languages),
                    page=page_number,
                    cancel=cancel,
                )
            except OcrCancelledError:
                raise
            except OcrError as exc:
                result.warnings.append(f"Strona {page_number}: {exc.user_message}")
                log.warning("ocr.page_failed", page=page_number, code=exc.code)
                continue
            finally:
                image.close()
            if time.monotonic() - page_started > deadline:
                result.warnings.append(
                    f"Strona {page_number} przekroczyla zalecany czas rozpoznawania."
                )
            if (
                page_result.confidence is not None
                and page_result.confidence < self.settings.min_confidence_to_keep
            ):
                result.warnings.append(
                    f"Strona {page_number}: niska pewnosc rozpoznania "
                    f"({page_result.confidence:.2f})."
                )
            result.pages.append(page_result)
            processed += 1
            if processed >= self.settings.max_pages_per_document:
                result.truncated = True
                result.warnings.append(
                    f"Przetworzono {processed} stron, limit dokumentu zostal osiagniety."
                )
                break

        log.info(
            "ocr.document_done",
            engine=engine.name,
            pages=len(result.pages),
            chars=result.char_count,
            duration=round(time.monotonic() - started, 2),
        )
        self._store_cache(content_sha256, result)
        return result

    def to_sections(
        self, result: OcrDocumentResult, *, start_order: int = 0
    ) -> list[ExtractedSection]:
        """Zamienia wynik OCR na sekcje gotowe do fragmentacji."""
        sections: list[ExtractedSection] = []
        for index, page in enumerate(result.pages):
            if not page.text.strip():
                continue
            sections.append(
                ExtractedSection(
                    text=page.text,
                    kind="page",
                    order=start_order + index,
                    page=page.page,
                    origin=TextOrigin.OCR,
                    ocr_confidence=page.confidence,
                )
            )
        return sections

    # --- pamiec podreczna -------------------------------------------------

    def _load_cache(
        self, content_sha256: str | None, engine: str, version: str, dpi: int
    ) -> OcrDocumentResult | None:
        if not content_sha256 or self.repository is None:
            return None
        row = self.repository.get_ocr_cache(content_sha256, engine, version, dpi)
        if row is None:
            return None
        pages = [
            OcrPageResult(page=index + 1, text=text, confidence=row["confidence"], engine=engine)
            for index, text in enumerate(str(row["text"]).split("\f"))
            if text.strip()
        ]
        log.info("ocr.cache_hit", engine=engine, pages=len(pages))
        return OcrDocumentResult(
            pages=pages,
            engine=engine,
            engine_version=version,
            languages=list(self.settings.languages),
            dpi=dpi,
            from_cache=True,
        )

    def _store_cache(self, content_sha256: str | None, result: OcrDocumentResult) -> None:
        if not content_sha256 or self.repository is None or not result.pages:
            return
        payload = "\f".join(page.text for page in result.pages)
        self.repository.put_ocr_cache(
            content_sha256,
            result.engine,
            result.engine_version,
            result.dpi,
            len(result.pages),
            result.confidence,
            payload,
        )

    def close(self) -> None:
        if self._selected is not None:
            self._selected.close()


__all__ = [
    "AUTO_ENGINE_ORDER",
    "MAX_RENDER_DPI",
    "MIN_RENDER_DPI",
    "OcrEngineInfo",
    "OcrService",
    "build_engines",
    "describe_engines",
]
