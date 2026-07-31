"""Parser starych arkuszy Excel w formacie BIFF (.xls, .xlt) oparty o xlrd 2.0.

Biblioteka xlrd w wersji 2.x celowo obsluguje wylacznie stary format binarny BIFF
i to jest dokladnie zakres tego adaptera. Nowsze skoroszyty XLSX czyta osobny parser.

Kazdy wiersz arkusza staje sie osobna sekcja ``table_row`` w postaci
"Kolumna: wartosc | Kolumna: wartosc". Dzieki temu warstwa fragmentacji potrafi
odnalezc pojedynczy rekord tabeli, a nie tylko caly plik.
"""

from __future__ import annotations

import datetime as _dt
import io
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finddocs.errors import (
    CorruptedFileError,
    DependencyUnavailableError,
    EmptyDocumentError,
    ExtractionError,
    FindDocsError,
    PasswordProtectedError,
    UnsupportedFormatError,
)
from finddocs.extractors.base import ExtractionContext, Extractor
from finddocs.logging_setup import get_logger
from finddocs.normalization.text import clean_text
from finddocs.types import (
    DocumentMetadata,
    ExtractedSection,
    ExtractionResult,
    SupportLevel,
    TextOrigin,
)

try:
    import xlrd
    from xlrd.biffh import XLRDError
    from xlrd.compdoc import CompDocError
    from xlrd.xldate import XLDateError

    _IMPORT_ERROR: str | None = None
except ImportError as exc:  # pragma: no cover - xlrd jest zaleznoscia obowiazkowa
    _IMPORT_ERROR = str(exc)

log = get_logger(__name__)

#: Co ile wierszy sprawdzac anulowanie i limit czasu.
_CHECKPOINT_EVERY: int = 16

#: Fragmenty komunikatow xlrd wskazujace na plik zaszyfrowany lub chroniony haslem.
_PASSWORD_MARKERS: tuple[str, ...] = ("encrypted", "encryption", "password")

#: Fragmenty komunikatow xlrd wskazujace na nowszy format spakowany podany jako .xls.
_MODERN_FORMAT_MARKERS: tuple[str, ...] = ("xlsx", "xlsb", "ods", "zip")

#: Ile ostrzezen biblioteki przepisac do wyniku.
_MAX_LIBRARY_WARNINGS: int = 5

#: Maksymalna liczba cyfr znaczacych po przecinku przy zapisie liczb.
_NUMBER_PRECISION: int = 10


@dataclass(slots=True)
class _Budget:
    """Biezacy stan numeracji sekcji i limitu znakow dokumentu."""

    max_chars: int
    order: int = 0
    chars: int = 0
    exhausted: bool = False

    def take(self, section: ExtractedSection) -> bool:
        """Nadaje sekcji numer porzadkowy. Zwraca False, gdy limit znakow zostal wyczerpany."""
        if self.chars + len(section.text) > self.max_chars:
            self.exhausted = True
            return False
        section.order = self.order
        self.order += 1
        self.chars += len(section.text)
        return True


def _flatten(text: str) -> str:
    """Czysci tekst komorki i splaszcza go do jednej linii."""
    return " ".join(clean_text(text).split())


def _format_number(value: float) -> str:
    """Zapisuje liczbe bez zbednych zer. Liczby calkowite bez czesci dziesietnej."""
    if not math.isfinite(value):
        return ""
    rounded = round(value, _NUMBER_PRECISION)
    if rounded == 0.0 and value != 0.0:
        # Liczba mniejsza od przyjetej precyzji, lepiej zapisac ja w postaci wykladniczej.
        return repr(value)
    if rounded == int(rounded) and abs(rounded) < 1e15:
        return str(int(rounded))
    text = f"{rounded:.{_NUMBER_PRECISION}f}".rstrip("0").rstrip(".")
    return text or "0"


def _format_date(value: Any, datemode: int) -> str:
    """Zamienia numer daty Excela na tekst. Godzina dopisywana tylko wtedy, gdy jest niezerowa."""
    try:
        number = float(value)
        stamp: _dt.datetime = xlrd.xldate_as_datetime(number, datemode)
    except (XLDateError, ValueError, TypeError, OverflowError):
        return ""
    has_time = bool(stamp.hour or stamp.minute or stamp.second)
    if number < 1.0 and has_time:
        # Wartosc ponizej jednego dnia to sama godzina, data bylaby mylaca.
        return stamp.strftime("%H:%M:%S")
    if has_time:
        return stamp.strftime("%Y-%m-%d %H:%M:%S")
    return stamp.strftime("%Y-%m-%d")


def _cell_text(cell_type: int, value: Any, datemode: int) -> str:
    """Zamienia komorke xlrd na tekst. Pusty wynik oznacza komorke do pominiecia."""
    if cell_type == xlrd.XL_CELL_TEXT:
        return _flatten(str(value))
    if cell_type == xlrd.XL_CELL_NUMBER:
        return _format_number(float(value))
    if cell_type == xlrd.XL_CELL_DATE:
        return _format_date(value, datemode)
    if cell_type == xlrd.XL_CELL_BOOLEAN:
        return "prawda" if value else "falsz"
    # XL_CELL_EMPTY, XL_CELL_BLANK oraz XL_CELL_ERROR nie wnosza tresci.
    return ""


class LegacyXlsExtractor(Extractor):
    """Adapter starych skoroszytow Excel (.xls, .xlt) czytanych biblioteka xlrd."""

    name = "xls"
    extensions = (".xls", ".xlt")
    mime_types = ("application/vnd.ms-excel",)
    support_level = SupportLevel.GOOD
    priority = 110

    def is_available(self) -> bool:
        return _IMPORT_ERROR is None

    def unavailable_reason(self) -> str:
        if _IMPORT_ERROR is None:
            return ""
        return f"Biblioteka xlrd nie jest dostepna: {_IMPORT_ERROR}"

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        """Czyta wszystkie arkusze skoroszytu i zwraca sekcje wierszy."""
        if _IMPORT_ERROR is not None:
            raise DependencyUnavailableError(
                "Obsluga plikow XLS wymaga biblioteki xlrd.",
                details={"blad_importu": _IMPORT_ERROR},
            )
        context.checkpoint()
        result = ExtractionResult(parser_name=self.name, support_level=self.support_level)
        diagnostics = io.StringIO()
        book = self._open(path, diagnostics)
        try:
            self._read_workbook(book, context, result)
        except FindDocsError:
            raise
        except Exception as exc:
            raise CorruptedFileError(
                f"Nie udalo sie odczytac skoroszytu {path.name}, plik jest uszkodzony.",
                details={"plik": path.name, "blad": type(exc).__name__},
            ) from exc
        finally:
            self._release(book)
        self._append_library_warnings(result, diagnostics.getvalue())
        if not result.sections:
            raise EmptyDocumentError(
                f"Skoroszyt {path.name} nie zawiera tresci mozliwej do zaindeksowania.",
                details={"plik": path.name},
            )
        return result

    # --- otwieranie i sprzatanie ------------------------------------------------

    def _open(self, path: Path, diagnostics: io.StringIO) -> Any:
        """Otwiera skoroszyt w trybie on_demand i tlumaczy bledy xlrd."""
        try:
            return xlrd.open_workbook(
                str(path),
                logfile=diagnostics,
                on_demand=True,
                formatting_info=False,
            )
        except XLRDError as exc:
            raise self._translate_xlrd_error(exc, path) from exc
        except CompDocError as exc:
            raise CorruptedFileError(
                f"Struktura dokumentu OLE w pliku {path.name} jest uszkodzona.",
                details={"plik": path.name},
            ) from exc
        except OSError as exc:
            raise ExtractionError(
                f"Nie udalo sie otworzyc pliku {path.name}.",
                details={"plik": path.name},
            ) from exc
        except Exception as exc:
            raise CorruptedFileError(
                f"Nie udalo sie odczytac skoroszytu {path.name}, plik jest uszkodzony.",
                details={"plik": path.name, "blad": type(exc).__name__},
            ) from exc

    def _translate_xlrd_error(self, exc: Exception, path: Path) -> FindDocsError:
        """Mapuje komunikat xlrd na wyjatek aplikacji."""
        message = str(exc)
        lowered = message.casefold()
        if any(marker in lowered for marker in _PASSWORD_MARKERS):
            return PasswordProtectedError(
                f"Skoroszyt {path.name} jest zaszyfrowany albo zabezpieczony haslem.",
                details={"plik": path.name, "komunikat": message},
            )
        if "not supported" in lowered and any(m in lowered for m in _MODERN_FORMAT_MARKERS):
            return UnsupportedFormatError(
                f"Plik {path.name} ma rozszerzenie starego formatu Excela, ale w srodku jest "
                "nowszy format spakowany, na przyklad XLSX. Popraw rozszerzenie pliku.",
                details={"plik": path.name, "komunikat": message},
            )
        return CorruptedFileError(
            f"Nie udalo sie odczytac skoroszytu {path.name}, plik jest uszkodzony.",
            details={"plik": path.name, "komunikat": message},
        )

    def _release(self, book: Any) -> None:
        """Zwalnia pamiec i uchwyt pliku. Blad zamykania nie moze przeslonic wyniku."""
        try:
            book.release_resources()
        except Exception as exc:  # pragma: no cover - zalezy od stanu pliku
            log.debug("xls.release_failed", error_type=type(exc).__name__)

    def _unload(self, book: Any, sheet_name: str) -> None:
        """Usuwa arkusz z pamieci, co ma sens tylko przy on_demand=True."""
        try:
            book.unload_sheet(sheet_name)
        except Exception as exc:  # pragma: no cover - nazwa arkusza zawsze pochodzi z ksiazki
            log.debug("xls.unload_failed", error_type=type(exc).__name__)

    # --- odczyt tresci ----------------------------------------------------------

    def _read_workbook(
        self, book: Any, context: ExtractionContext, result: ExtractionResult
    ) -> None:
        """Przechodzi po arkuszach skoroszytu i dopisuje sekcje do wyniku."""
        sheet_names = [str(name) for name in book.sheet_names()]
        result.total_pages = len(sheet_names)
        result.metadata = self._build_metadata(book, sheet_names)
        budget = _Budget(max_chars=context.max_chars)
        failed: list[str] = []
        for index, sheet_name in enumerate(sheet_names):
            context.checkpoint()
            label = clean_text(sheet_name) or f"Arkusz {index + 1}"
            if not self._process_sheet(book, index, sheet_name, label, context, result, budget):
                failed.append(label)
            if budget.exhausted:
                result.warnings.append(
                    "Przekroczono limit znakow dokumentu, dalsza tresc zostala pominieta."
                )
                break
        if failed:
            result.warnings.append(f"Pominieto uszkodzone arkusze: {', '.join(failed)}.")
            if not result.sections:
                raise CorruptedFileError(
                    "Nie udalo sie odczytac zadnego arkusza skoroszytu.",
                    details={"arkusze": failed},
                )

    def _process_sheet(
        self,
        book: Any,
        index: int,
        sheet_name: str,
        label: str,
        context: ExtractionContext,
        result: ExtractionResult,
        budget: _Budget,
    ) -> bool:
        """Czyta jeden arkusz. Zwraca False, gdy arkusz okazal sie nieczytelny."""
        try:
            sheet = book.sheet_by_index(index)
            sections = self._read_sheet(sheet, label, int(book.datemode), context, result)
        except FindDocsError:
            raise
        except Exception as exc:
            log.warning("xls.sheet_failed", sheet=label, error_type=type(exc).__name__)
            return False
        finally:
            self._unload(book, sheet_name)
        for section in sections:
            if not budget.take(section):
                break
            result.sections.append(section)
        return True

    def _read_sheet(
        self,
        sheet: Any,
        label: str,
        datemode: int,
        context: ExtractionContext,
        result: ExtractionResult,
    ) -> list[ExtractedSection]:
        """Buduje sekcje jednego arkusza: naglowek arkusza, naglowek tabeli i wiersze."""
        total_rows = int(sheet.nrows)
        if total_rows <= 0:
            return []
        limit = min(total_rows, context.sheet_max_rows)
        if total_rows > limit:
            result.warnings.append(
                f"Arkusz {label}: odczytano {limit} z {total_rows} wierszy, reszte pominieto."
            )
        headers, first_data_row = self._read_headers(sheet, limit)
        heading = " | ".join(h for h in headers if h) or label
        rows: list[ExtractedSection] = []
        for row_index in range(first_data_row, limit):
            if row_index % _CHECKPOINT_EVERY == 0:
                context.checkpoint()
            text = self._format_row(sheet, row_index, headers, datemode)
            if not text:
                continue
            rows.append(
                ExtractedSection(
                    text=text,
                    kind="table_row",
                    sheet=label,
                    row=row_index + 1,
                    heading=heading,
                    origin=TextOrigin.NATIVE,
                )
            )
        if not rows:
            return []
        sections: list[ExtractedSection] = [
            ExtractedSection(text=clean_text(f"Arkusz: {label}"), kind="sheet", sheet=label)
        ]
        header_text = clean_text(" | ".join(h for h in headers if h))
        if header_text:
            sections.append(
                ExtractedSection(
                    text=header_text,
                    kind="table_header",
                    sheet=label,
                    row=1,
                    heading=heading,
                )
            )
        sections.extend(rows)
        return sections

    def _read_headers(self, sheet: Any, limit: int) -> tuple[list[str], int]:
        """Rozpoznaje wiersz naglowkowy.

        Za naglowek uznaje pierwszy wiersz, w ktorym wszystkie wypelnione komorki sa
        tekstem. Zwraca etykiety kolumn oraz numer pierwszego wiersza z danymi.
        """
        if limit <= 1:
            return [], 0
        try:
            cell_types = list(sheet.row_types(0))
            values = list(sheet.row_values(0))
        except Exception:  # pragma: no cover - obrona przed uszkodzonym pierwszym wierszem
            return [], 0
        blank = (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK)
        filled = [kind for kind in cell_types if kind not in blank]
        if not filled or any(kind != xlrd.XL_CELL_TEXT for kind in filled):
            return [], 0
        headers = [
            _flatten(str(value)) if kind == xlrd.XL_CELL_TEXT else ""
            for kind, value in zip(cell_types, values, strict=False)
        ]
        if not any(headers):
            return [], 0
        return headers, 1

    def _format_row(self, sheet: Any, row_index: int, headers: list[str], datemode: int) -> str:
        """Sklada wiersz w tekst "Kolumna: wartosc | Kolumna: wartosc"."""
        try:
            cell_types = list(sheet.row_types(row_index))
            values = list(sheet.row_values(row_index))
        except Exception:  # pragma: no cover - pojedynczy uszkodzony wiersz nie psuje arkusza
            return ""
        parts: list[str] = []
        for column, (kind, value) in enumerate(zip(cell_types, values, strict=False)):
            text = _cell_text(int(kind), value, datemode)
            if not text:
                continue
            label = headers[column] if column < len(headers) else ""
            parts.append(f"{label}: {text}" if label else text)
        if not parts:
            return ""
        return clean_text(" | ".join(parts))

    # --- metadane ---------------------------------------------------------------

    def _build_metadata(self, book: Any, sheet_names: list[str]) -> DocumentMetadata:
        """Sklada metadane dostepne w formacie BIFF. Jest ich niewiele."""
        metadata = DocumentMetadata(page_count=len(sheet_names))
        author = clean_text(str(book.user_name or ""))
        if author:
            metadata.author = author
        metadata.extra["arkusze"] = sheet_names
        metadata.extra["liczba_arkuszy"] = len(sheet_names)
        if book.biff_version:
            metadata.extra["wersja_biff"] = book.biff_version
        if book.encoding:
            metadata.extra["kodowanie_zrodla"] = str(book.encoding)
        return metadata

    def _append_library_warnings(self, result: ExtractionResult, diagnostics: str) -> None:
        """Przepisuje diagnostyke xlrd do ostrzezen wyniku, bez powtorzen."""
        seen: set[str] = set()
        for raw_line in diagnostics.splitlines():
            line = raw_line.strip().strip("*").strip()
            if not line or line in seen:
                continue
            seen.add(line)
            result.warnings.append(f"Ostrzezenie biblioteki xlrd: {line}")
            if len(seen) >= _MAX_LIBRARY_WARNINGS:
                break


__all__ = ["LegacyXlsExtractor"]
