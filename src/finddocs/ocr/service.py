"""Uslugi OCR: wybor silnika, rasteryzacja stron, limity i pamiec podreczna.

Przetwarzanie idzie strona po stronie, zeby zuzycie pamieci nie zalezalo od liczby
stron dokumentu. Kazda strona moze zostac przerwana przez uzytkownika. Wynik jest
zapisywany w pamieci podrecznej pod kluczem (skrot tresci, silnik, wersja, dpi),
wiec ponowne skanowanie niezmienionego pliku nie uruchamia OCR jeszcze raz.
"""

from __future__ import annotations

import math
import threading
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
from finddocs.ocr.engines.remote_api import ENGINE_NAME as REMOTE_ENGINE_NAME
from finddocs.ocr.engines.remote_api import RemoteOcrEngine
from finddocs.ocr.engines.tesseract import TesseractEngine
from finddocs.security.network import NetworkPolicy
from finddocs.types import CancellationToken, ExtractedSection, TextOrigin

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable

    from PIL.Image import Image

    from finddocs.indexing.repository import Repository

log = get_logger(__name__)

#: Kolejnosc prob przy ustawieniu engine="auto". Zdalnego serwera na tej liscie
#: nie ma celowo: wysylka obrazu poza komputer wymaga jawnego wyboru silnika.
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


def ocr_api_key_provider(config_dir: Path | None) -> Callable[[], str | None] | None:
    """Buduje funkcje odczytu klucza API zdalnego serwera OCR.

    Klucz jest odczytywany dopiero w chwili wysylki zadania, wiec jego zmiana
    w magazynie poswiadczen dziala bez ponownego tworzenia silnika.
    """
    if config_dir is None:
        return None

    from finddocs.security.credentials import OCR_API_KEY_NAME, create_credential_store

    def read_key() -> str | None:
        try:
            store = create_credential_store(config_dir)
            return store.get_secret(OCR_API_KEY_NAME)
        except Exception as exc:
            log.warning("ocr.api_key_unavailable", error_type=type(exc).__name__)
            return None

    return read_key


def build_remote_engine(
    settings: OcrSettings,
    credentials_dir: Path | None = None,
    *,
    policy: NetworkPolicy | None = None,
) -> RemoteOcrEngine:
    """Tworzy adapter zdalnego serwera OCR z ustawien aplikacji.

    ``policy`` sluzy testowi polaczenia w interfejsie: pozwala sprawdzic adres
    z formularza, zanim trafi on do konfiguracji i do polityki procesu.
    """
    return RemoteOcrEngine(
        settings.remote_api_url,
        enabled=settings.remote_api_enabled,
        model=settings.remote_api_model,
        timeout=settings.remote_api_timeout_seconds,
        max_retries=settings.remote_api_max_retries,
        api_key_provider=ocr_api_key_provider(credentials_dir),
        api_key_header=settings.remote_api_key_header,
        auto_rotate=settings.auto_rotate,
        policy=policy,
    )


def build_engines(
    settings: OcrSettings,
    model_dir: Path | None = None,
    *,
    credentials_dir: Path | None = None,
) -> list[OcrEngine]:
    """Tworzy liste silnikow w kolejnosci preferencji."""
    tesseract = TesseractEngine(executable=settings.tesseract_path)
    easy = EasyOcrEngine(model_dir=model_dir, allow_download=False)
    rapid = RapidOcrEngine()
    by_name: dict[str, OcrEngine] = {
        tesseract.name: tesseract,
        easy.name: easy,
        rapid.name: rapid,
    }
    if settings.engine == REMOTE_ENGINE_NAME:
        # Zdalny serwer pierwszy, silniki lokalne jako rezerwa. Gdy serwer nie
        # odpowiada, indeksowanie idzie dalej na procesorze zamiast stanac.
        return [build_remote_engine(settings, credentials_dir), *by_name.values()]
    if settings.engine in by_name:
        preferred = by_name.pop(settings.engine)
        return [preferred, *by_name.values()]
    return [by_name[name] for name in AUTO_ENGINE_ORDER if name in by_name]


def describe_engines(
    settings: OcrSettings,
    model_dir: Path | None = None,
    *,
    credentials_dir: Path | None = None,
) -> list[OcrEngineInfo]:
    """Opis wszystkich silnikow dla ekranu diagnostyki."""
    engines = build_engines(settings, model_dir, credentials_dir=credentials_dir)
    if settings.remote_api_enabled and settings.engine != REMOTE_ENGINE_NAME:
        # Skonfigurowany serwer pokazujemy takze wtedy, gdy nie jest wybrany:
        # administrator ma widziec, czy odpowiada, zanim przelaczy silnik.
        engines = [build_remote_engine(settings, credentials_dir), *engines]
    result: list[OcrEngineInfo] = []
    for engine in engines:
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
        credentials_dir: Path | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self._engines = build_engines(settings, model_dir, credentials_dir=credentials_dir)
        self._selected: OcrEngine | None = None
        self.warnings: list[str] = []
        self._select_lock = threading.Lock()
        #: Serializuje wywolania silnikow, ktore nie deklaruja bezpieczenstwa
        #: rownoczesnego (wspolna sesja modelu w pamieci).
        self._recognize_lock = threading.Lock()

    # --- wybor silnika ----------------------------------------------------

    @property
    def engine(self) -> OcrEngine:
        if self._selected is not None:
            return self._selected
        with self._select_lock:
            return self._select_engine()

    def _select_engine(self) -> OcrEngine:
        if self._selected is not None:
            return self._selected
        problems: list[str] = []
        for candidate in self._engines:
            if candidate.is_available():
                self._selected = candidate
                if problems and self._engines[0].name == REMOTE_ENGINE_NAME:
                    # Zejscie ze zdalnego serwera na silnik lokalny zmienia
                    # jakosc i czas rozpoznawania, wiec uzytkownik ma o tym
                    # wiedziec z raportu, a nie tylko z dziennika.
                    self.warnings.append(
                        "Zdalny serwer OCR jest niedostępny, użyto silnika lokalnego "
                        f"{candidate.name}. {problems[0]}"
                    )
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
            "Żaden silnik OCR nie jest dostępny. Zainstaluj Tesseract OCR albo "
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
            from finddocs.extractors.pdf import (
                pdf_page_count,
                pdf_page_image_dpi,
                render_pdf_page,
            )

            total = pdf_page_count(path)
            wanted = pages or list(range(1, total + 1))
            for page in wanted[: self.settings.max_pages_per_document]:
                if cancel is not None and cancel.is_cancelled():
                    raise OcrCancelledError()
                if page < 1 or page > total:
                    continue
                # Strona bedaca czystym skanem nie zyskuje na rasteryzacji
                # powyzej wlasnej rozdzielczosci osadzonego obrazu, a kazdy
                # nadmiarowy piksel kosztuje przy kodowaniu, przesyle
                # i rozpoznawaniu. Ograniczenie dotyczy tylko stron zlozonych
                # z samych obrazow; strony z inna trescia renderuja sie jak
                # dotychczas.
                page_dpi = dpi
                native = pdf_page_image_dpi(path, page - 1)
                if native is not None and native < page_dpi:
                    page_dpi = max(1, math.ceil(native))
                yield (
                    page,
                    render_pdf_page(
                        path, page - 1, dpi=page_dpi, max_pixels=self.settings.max_image_pixels
                    ),
                )
            return

        from finddocs.extractors.image import load_image_frames

        frames = load_image_frames(
            path,
            max_frames=self.settings.max_pages_per_document,
            max_pixels=self.settings.max_image_pixels,
        )
        for index, frame in enumerate(frames, start=1):
            if cancel is not None and cancel.is_cancelled():
                raise OcrCancelledError()
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
                page_result = self._recognize(
                    engine,
                    image,
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
                    f"Strona {page_number} przekroczyła zalecany czas rozpoznawania."
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
                    f"Przetworzono {processed} stron, limit dokumentu został osiągnięty."
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

    def _recognize(
        self,
        engine: OcrEngine,
        image: Image,
        *,
        page: int,
        cancel: CancellationToken | None,
    ) -> OcrPageResult:
        """Wywoluje silnik, serializujac te bez bezpiecznej rownoczesnosci."""
        languages = list(self.settings.languages)
        if engine.concurrent_safe:
            return engine.recognize(image, languages=languages, page=page, cancel=cancel)
        with self._recognize_lock:
            return engine.recognize(image, languages=languages, page=page, cancel=cancel)

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
        # Wynik obciety limitem stron nie trafia do pamieci podrecznej. Klucz
        # wpisu nie zawiera limitu, wiec zapisany wynik czesciowy maskowalby
        # pozniejsze podniesienie limitu w ustawieniach.
        if result.truncated:
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
    "REMOTE_ENGINE_NAME",
    "OcrEngineInfo",
    "OcrService",
    "build_engines",
    "build_remote_engine",
    "describe_engines",
    "ocr_api_key_provider",
]
