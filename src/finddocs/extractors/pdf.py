"""Parser dokumentow PDF oparty o biblioteke pypdfium2.

Adapter czyta warstwe tekstowa strona po stronie i nie wykonuje OCR. Gdy warstwa
tekstowa jest pusta albo wyglada na smieci, ustawia flage ``needs_ocr``, a decyzje
o rasteryzacji podejmuje osobna warstwa OCR. Modul udostepnia tej warstwie funkcje
``render_pdf_page`` oraz ``pdf_page_count``, zeby caly kontakt z pypdfium2 byl
zamkniety w jednym miejscu.
"""

from __future__ import annotations

import datetime as _dt
import math
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from finddocs.errors import CorruptedFileError, ExtractionError, PasswordProtectedError
from finddocs.extractors.base import ExtractionContext, Extractor
from finddocs.logging_setup import get_logger
from finddocs.normalization.text import clean_text, looks_like_garbage
from finddocs.types import (
    DocumentMetadata,
    ExtractedSection,
    ExtractionResult,
    SupportLevel,
    TextOrigin,
)

if TYPE_CHECKING:  # pragma: no cover - tylko dla kontroli typow
    from PIL import Image

log = get_logger(__name__)

#: Twardy limit liczby przetwarzanych stron. Wieksze pliki sa obcinane z ostrzezeniem.
MAX_PAGES: int = 5000

#: Ponizej tylu znakow na strone uznajemy warstwe tekstowa za bezuzyteczna.
MIN_CHARS_PER_PAGE: int = 90

#: Co ile stron sprawdzac anulowanie i limit czasu.
CHECKPOINT_EVERY: int = 16

#: Dolne ograniczenie skali renderowania, zabezpiecza przed skala zerowa.
MIN_RENDER_SCALE: float = 0.01

#: Liczba punktow PDF przypadajaca na cal.
POINTS_PER_INCH: float = 72.0

#: Fragmenty komunikatow pdfium wskazujace na haslo albo nieobslugiwane szyfrowanie.
_PASSWORD_MARKERS: tuple[str, ...] = ("password", "security")

_PDF_DATE_RE = re.compile(
    r"^D?:?\s*(?P<year>\d{4})(?P<month>\d{2})?(?P<day>\d{2})?"
    r"(?P<hour>\d{2})?(?P<minute>\d{2})?(?P<second>\d{2})?"
    r"(?P<tz>[Zz]|[+-]\d{2}'?(?:\d{2})?'?)?"
)


def _parse_pdf_offset(raw: str | None) -> _dt.timezone | None:
    """Zamienia przesuniecie strefy z daty PDF na obiekt strefy. Bledy zwracaja None."""
    if not raw:
        return None
    if raw in {"Z", "z"}:
        return _dt.UTC
    digits = raw[1:].replace("'", "")
    if len(digits) < 2:
        return None
    try:
        hours = int(digits[:2])
        minutes = int(digits[2:4]) if len(digits) >= 4 else 0
    except ValueError:
        return None
    if hours > 23 or minutes > 59:
        return None
    delta = _dt.timedelta(hours=hours, minutes=minutes)
    if raw[0] == "-":
        delta = -delta
    return _dt.timezone(delta)


def parse_pdf_date(value: str | None) -> _dt.datetime | None:
    """Parsuje date w formacie PDF ``D:YYYYMMDDHHmmSS`` z opcjonalna strefa czasowa.

    Zwraca None dla wartosci pustej albo niezgodnej z formatem. Bledne daty sa
    ignorowane, metadane nigdy nie przerywaja ekstrakcji.
    """
    if not value:
        return None
    match = _PDF_DATE_RE.match(value.strip())
    if match is None:
        return None
    try:
        parsed = _dt.datetime(
            int(match["year"]),
            int(match["month"] or 1),
            int(match["day"] or 1),
            int(match["hour"] or 0),
            int(match["minute"] or 0),
            int(match["second"] or 0),
        )
    except ValueError:
        return None
    offset = _parse_pdf_offset(match["tz"])
    if offset is not None:
        parsed = parsed.replace(tzinfo=offset)
    return parsed


def _open_document(path: Path) -> pdfium.PdfDocument:
    """Otwiera dokument PDF, tlumaczac bledy pdfium na wyjatki FindDocs."""
    try:
        return pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as exc:
        message = str(exc).lower()
        if any(marker in message for marker in _PASSWORD_MARKERS):
            raise PasswordProtectedError(
                "Plik PDF jest zabezpieczony haslem lub uzywa nieobslugiwanego szyfrowania.",
                details={"plik": path.name},
                cause=exc,
            ) from exc
        raise CorruptedFileError(
            "Nie udalo sie otworzyc pliku PDF, dane sa uszkodzone lub niekompletne.",
            details={"plik": path.name},
            cause=exc,
        ) from exc
    except FileNotFoundError as exc:
        raise ExtractionError(
            "Nie znaleziono pliku PDF do odczytu.",
            details={"plik": path.name},
            cause=exc,
        ) from exc
    except OSError as exc:
        raise CorruptedFileError(
            "Blad odczytu pliku PDF z dysku.",
            details={"plik": path.name},
            cause=exc,
        ) from exc


def _is_encrypted(pdf: pdfium.PdfDocument) -> bool:
    """Czy dokument ma zalozony slownik szyfrowania (otwarty pustym haslem uzytkownika)."""
    try:
        revision = int(pdfium_c.FPDF_GetSecurityHandlerRevision(pdf))
    except (AttributeError, OSError, ValueError, TypeError):
        return False
    return revision >= 0


def _page_text(pdf: pdfium.PdfDocument, index: int) -> str:
    """Zwraca surowy tekst jednej strony. Blad strony daje pusty wynik."""
    page = pdf[index]
    try:
        textpage = page.get_textpage()
        try:
            raw_text = textpage.get_text_bounded()
        finally:
            textpage.close()
    finally:
        page.close()
    return str(raw_text or "")


class PdfExtractor(Extractor):
    """Adapter formatu PDF czytajacy natywna warstwe tekstowa."""

    name = "pdf"
    extensions = (".pdf",)
    mime_types = ("application/pdf",)
    support_level = SupportLevel.FULL
    priority = 120

    def is_available(self) -> bool:
        """pypdfium2 jest zaleznoscia obowiazkowa, adapter jest zawsze dostepny."""
        return True

    def unavailable_reason(self) -> str:
        return ""

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        """Wyciaga tekst i metadane z pliku PDF."""
        context.checkpoint()
        result = ExtractionResult(
            parser_name=self.name,
            support_level=self.support_level,
            origin=TextOrigin.NATIVE,
        )
        total_chars = 0
        pages_read = 0
        pdf = _open_document(path)
        try:
            page_count = len(pdf)
            result.total_pages = page_count
            result.metadata = self._read_metadata(pdf, page_count)
            if _is_encrypted(pdf):
                result.metadata.extra["zaszyfrowany"] = True
                result.warnings.append(
                    "Dokument jest zaszyfrowany, ale udalo sie go otworzyc bez hasla uzytkownika."
                )
            limit = min(page_count, MAX_PAGES)
            if page_count > MAX_PAGES:
                result.warnings.append(
                    f"Dokument ma {page_count} stron. Przetworzono pierwsze {MAX_PAGES}."
                )
            total_chars, pages_read = self._read_pages(pdf, limit, context, result)
        finally:
            pdf.close()

        self._decide_ocr(result, total_chars, pages_read)
        return result

    def _read_pages(
        self,
        pdf: pdfium.PdfDocument,
        limit: int,
        context: ExtractionContext,
        result: ExtractionResult,
    ) -> tuple[int, int]:
        """Czyta strony po kolei i dopisuje sekcje.

        Zwraca laczna dlugosc czystego tekstu oraz liczbe faktycznie odczytanych stron.
        """
        total_chars = 0
        failed_pages = 0
        pages_read = 0
        for index in range(limit):
            pages_read = index + 1
            if index % CHECKPOINT_EVERY == 0:
                context.checkpoint()
            try:
                raw_text = _page_text(pdf, index)
            except (pdfium.PdfiumError, OSError, ValueError) as exc:
                failed_pages += 1
                log.warning(
                    "pdf.page_failed",
                    page=index + 1,
                    error_type=type(exc).__name__,
                )
                continue
            text = clean_text(raw_text)
            if not text:
                continue
            total_chars += len(text)
            result.sections.append(
                ExtractedSection(
                    text=text,
                    kind="page",
                    order=index,
                    page=index + 1,
                    origin=TextOrigin.NATIVE,
                )
            )
            if total_chars >= context.max_chars:
                result.warnings.append(
                    f"Przekroczono limit {context.max_chars} znakow. "
                    f"Odczyt zatrzymano na stronie {index + 1}."
                )
                break
        if failed_pages:
            result.warnings.append(f"Nie udalo sie odczytac {failed_pages} stron dokumentu.")
        return total_chars, pages_read

    def _read_metadata(self, pdf: pdfium.PdfDocument, page_count: int) -> DocumentMetadata:
        """Odczytuje slownik metadanych dokumentu. Bledy daja metadane czesciowe."""
        raw: dict[str, Any] = {}
        try:
            raw = dict(pdf.get_metadata_dict(skip_empty=True))
        except (pdfium.PdfiumError, OSError, ValueError, UnicodeDecodeError) as exc:
            log.warning("pdf.metadata_failed", error_type=type(exc).__name__)

        def value(key: str) -> str | None:
            item = raw.get(key)
            if not isinstance(item, str):
                return None
            cleaned = clean_text(item)
            return cleaned or None

        metadata = DocumentMetadata(
            title=value("Title"),
            author=value("Author"),
            subject=value("Subject"),
            keywords=value("Keywords"),
            created_at=parse_pdf_date(value("CreationDate")),
            modified_at=parse_pdf_date(value("ModDate")),
            page_count=page_count,
            producer=value("Producer"),
        )
        creator = value("Creator")
        if creator:
            metadata.extra["creator"] = creator
        return metadata

    def _decide_ocr(self, result: ExtractionResult, total_chars: int, pages_read: int) -> None:
        """Ocenia, czy warstwa tekstowa jest uzyteczna, czy trzeba sprobowac OCR."""
        if pages_read <= 0:
            result.needs_ocr = True
            result.warnings.append("Dokument PDF nie zawiera zadnej strony do odczytu.")
            return
        combined = result.all_text()
        if not combined:
            result.needs_ocr = True
            result.warnings.append(
                "Brak warstwy tekstowej w pliku PDF. Dokument kwalifikuje sie do OCR."
            )
            return
        average = total_chars / pages_read
        if average < MIN_CHARS_PER_PAGE:
            result.needs_ocr = True
            result.warnings.append(
                f"Uboga warstwa tekstowa: srednio {average:.0f} znakow na strone. "
                "Dokument kwalifikuje sie do OCR."
            )
            return
        if looks_like_garbage(combined):
            result.needs_ocr = True
            result.warnings.append(
                "Warstwa tekstowa wyglada na uszkodzona. Dokument kwalifikuje sie do OCR."
            )


def _pixel_count(width_pt: float, height_pt: float, scale: float) -> int:
    """Liczba pikseli obrazu przy danej skali. Pdfium zaokragla wymiary w gore."""
    return math.ceil(width_pt * scale) * math.ceil(height_pt * scale)


def _fit_scale(width_pt: float, height_pt: float, *, dpi: int, max_pixels: int) -> float:
    """Dobiera skale renderowania tak, zeby obraz zmiescil sie w limicie pikseli."""
    scale = dpi / POINTS_PER_INCH
    width = max(1.0, width_pt)
    height = max(1.0, height_pt)
    if max_pixels <= 0:
        return max(scale, MIN_RENDER_SCALE)
    pixels = (width * scale) * (height * scale)
    if pixels > max_pixels:
        scale *= math.sqrt(max_pixels / pixels)
    while scale > MIN_RENDER_SCALE and _pixel_count(width, height, scale) > max_pixels:
        scale *= 0.99
    return max(scale, MIN_RENDER_SCALE)


def render_pdf_page(
    path: Path,
    page_index: int,
    dpi: int = 220,
    max_pixels: int = 40_000_000,
) -> Image.Image:
    """Rasteryzuje jedna strone PDF do obrazu PIL.

    Strony liczone sa od zera. Gdy obraz w zadanym ``dpi`` przekroczylby
    ``max_pixels``, skala jest proporcjonalnie zmniejszana. Wynik ma tryb "L"
    albo "RGB" i nie wspoldzieli pamieci z buforem pdfium.
    """
    if page_index < 0:
        raise ExtractionError(
            "Numer strony do rasteryzacji nie moze byc ujemny.",
            details={"strona": page_index},
        )
    if dpi <= 0:
        raise ExtractionError(
            "Rozdzielczosc rasteryzacji musi byc dodatnia.",
            details={"dpi": dpi},
        )

    image: Image.Image
    pdf = _open_document(path)
    try:
        page_count = len(pdf)
        if page_index >= page_count:
            raise ExtractionError(
                f"Plik PDF ma {page_count} stron, zadano strony {page_index + 1}.",
                details={"plik": path.name, "strona": page_index + 1},
            )
        try:
            width_pt, height_pt = pdf.get_page_size(page_index)
            scale = _fit_scale(float(width_pt), float(height_pt), dpi=dpi, max_pixels=max_pixels)
            page = pdf[page_index]
            try:
                bitmap = page.render(scale=scale, draw_annots=True, may_draw_forms=False)
                try:
                    raw_image = bitmap.to_pil()
                    if raw_image.mode in {"L", "RGB"}:
                        image = raw_image.copy()
                    else:
                        image = raw_image.convert("RGB")
                finally:
                    bitmap.close()
            finally:
                page.close()
        except (pdfium.PdfiumError, OSError, ValueError) as exc:
            raise CorruptedFileError(
                f"Nie udalo sie zrasteryzowac strony {page_index + 1} pliku PDF.",
                details={"plik": path.name, "strona": page_index + 1},
                cause=exc,
            ) from exc
    finally:
        pdf.close()
    return image


def pdf_page_count(path: Path) -> int:
    """Zwraca liczbe stron dokumentu PDF."""
    pdf = _open_document(path)
    try:
        return len(pdf)
    finally:
        pdf.close()


__all__ = [
    "CHECKPOINT_EVERY",
    "MAX_PAGES",
    "MIN_CHARS_PER_PAGE",
    "PdfExtractor",
    "parse_pdf_date",
    "pdf_page_count",
    "render_pdf_page",
]
