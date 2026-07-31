"""Rejestr parserow.

Rejestr pozwala dodac obsluge nowego formatu bez zmian w reszcie aplikacji:
wystarczy zarejestrowac adapter implementujacy ``Extractor``.
"""

from __future__ import annotations

from pathlib import Path

from finddocs.errors import UnsupportedFormatError
from finddocs.extractors.base import ExtractionContext, Extractor
from finddocs.extractors.detect import FileTypeInfo, detect_file_type
from finddocs.logging_setup import get_logger
from finddocs.types import ExtractionResult, SupportLevel

log = get_logger(__name__)


class ExtractorRegistry:
    """Kolekcja adapterow formatow z wyborem najlepszego dla danego pliku."""

    def __init__(self) -> None:
        self._extractors: list[Extractor] = []

    def register(self, extractor: Extractor) -> None:
        self._extractors.append(extractor)
        self._extractors.sort(key=lambda e: e.priority, reverse=True)

    def unregister(self, name: str) -> None:
        self._extractors = [e for e in self._extractors if e.name != name]

    @property
    def extractors(self) -> list[Extractor]:
        return list(self._extractors)

    def supported_extensions(self) -> set[str]:
        result: set[str] = set()
        for extractor in self._extractors:
            result.update(extractor.extensions)
        return result

    def candidates(self, path: Path, info: FileTypeInfo) -> list[Extractor]:
        """Adaptery zdolne obsluzyc plik, w kolejnosci priorytetu."""
        matched = [e for e in self._extractors if e.supports(path, info.mime_type)]
        if not matched and info.extension:
            matched = [e for e in self._extractors if info.extension in e.extensions]
        return matched

    def find(self, path: Path, info: FileTypeInfo) -> Extractor | None:
        """Pierwszy dostepny adapter dla pliku."""
        for extractor in self.candidates(path, info):
            if extractor.is_available():
                return extractor
        return None

    def extract(
        self,
        path: Path,
        context: ExtractionContext,
        *,
        declared_mime: str | None = None,
        file_name: str | None = None,
    ) -> tuple[ExtractionResult, FileTypeInfo]:
        """Rozpoznaje typ i uruchamia lancuch adapterow.

        Gdy adapter o wyzszym priorytecie zawiedzie, probowany jest kolejny.
        Zwracany jest wynik pierwszego, ktory zadziala. Gdy zaden nie zadziala,
        rzucany jest ostatni napotkany blad.
        """
        info = detect_file_type(path, declared_mime=declared_mime, file_name=file_name)
        if info.is_encrypted:
            from finddocs.errors import PasswordProtectedError

            raise PasswordProtectedError(
                "Plik jest zaszyfrowany albo zabezpieczony hasłem.",
                details={"mime": info.mime_type},
            )

        candidates = self.candidates(path, info)
        if not candidates:
            raise UnsupportedFormatError(
                f"Brak parsera dla typu {info.mime_type} "
                f"(rozszerzenie {info.extension or 'brak'}).",
                details={"mime": info.mime_type, "extension": info.extension},
            )

        last_error: Exception | None = None
        unavailable: list[str] = []
        for extractor in candidates:
            if not extractor.is_available():
                unavailable.append(f"{extractor.name}: {extractor.unavailable_reason()}")
                continue
            context.checkpoint()
            try:
                result = extractor.extract(path, context)
            except Exception as exc:
                last_error = exc
                log.warning(
                    "extractor.failed",
                    extractor=extractor.name,
                    mime=info.mime_type,
                    error_type=type(exc).__name__,
                )
                continue
            result.parser_name = result.parser_name or extractor.name
            if result.support_level is SupportLevel.FULL:
                result.support_level = extractor.support_level
            for note in unavailable:
                result.warnings.append(f"Adapter niedostępny, użyto zapasowego. {note}")
            return result, info

        if last_error is not None:
            raise last_error
        raise UnsupportedFormatError(
            f"Żaden adapter dla {info.mime_type} nie jest dostępny w tym systemie.",
            details={"mime": info.mime_type, "unavailable": unavailable},
        )

    def describe(self) -> list[dict[str, object]]:
        return [e.describe() for e in self._extractors]


def build_default_registry(*, office_com_enabled: bool = True) -> ExtractorRegistry:
    """Tworzy rejestr ze wszystkimi wbudowanymi adapterami."""
    from finddocs.extractors.csv_table import CsvExtractor
    from finddocs.extractors.doc_legacy import (
        LegacyDocComExtractor,
        LegacyDocOleExtractor,
    )
    from finddocs.extractors.docx import DocxExtractor
    from finddocs.extractors.eml import EmlExtractor
    from finddocs.extractors.html_text import HtmlExtractor
    from finddocs.extractors.image import ImageExtractor
    from finddocs.extractors.msg import MsgExtractor
    from finddocs.extractors.pdf import PdfExtractor
    from finddocs.extractors.rtf import RtfExtractor
    from finddocs.extractors.text import PlainTextExtractor
    from finddocs.extractors.xls_legacy import LegacyXlsExtractor
    from finddocs.extractors.xlsx import XlsxExtractor

    registry = ExtractorRegistry()
    registry.register(PdfExtractor())
    registry.register(DocxExtractor())
    registry.register(XlsxExtractor())
    registry.register(LegacyXlsExtractor())
    registry.register(CsvExtractor())
    registry.register(PlainTextExtractor())
    registry.register(HtmlExtractor())
    registry.register(RtfExtractor())
    registry.register(EmlExtractor())
    registry.register(MsgExtractor())
    registry.register(ImageExtractor())
    if office_com_enabled:
        registry.register(LegacyDocComExtractor())
    registry.register(LegacyDocOleExtractor())
    return registry


__all__ = ["ExtractorRegistry", "build_default_registry"]
