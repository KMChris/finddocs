"""Parser plikow rozdzielanych separatorem: CSV oraz TSV.

Adapter rozpoznaje kodowanie znakow i separator kolumn, a nastepnie zamienia kazdy
wiersz danych na osobna sekcje tekstu w formacie "Kolumna: wartosc". Dzieki temu
fragmenty trafiajace do indeksu zachowuja nazwy kolumn i pozostaja czytelne
w wynikach wyszukiwania, nawet gdy uzytkownik zobaczy tylko jeden wiersz tabeli.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator, Sequence
from itertools import chain
from pathlib import Path

from finddocs.errors import CorruptedFileError, EmptyDocumentError, ExtractionError
from finddocs.extractors.base import ExtractionContext, Extractor
from finddocs.extractors.encoding import decode_text
from finddocs.normalization.text import clean_text
from finddocs.types import (
    DocumentMetadata,
    ExtractedSection,
    ExtractionResult,
    SupportLevel,
    TextOrigin,
)

#: Separatory rozwazane przy analizie probki, w kolejnosci preferencji.
_DELIMITERS: tuple[str, ...] = (";", ",", "\t", "|")

#: Rozmiar probki (w znakach) uzywanej do wykrycia separatora: 64 KB.
_SAMPLE_CHARS: int = 64 * 1024

#: Ile pierwszych linii analizowac, gdy sniffer nie rozpozna separatora.
_COUNT_LINES: int = 5

#: Co ile wierszy sprawdzac anulowanie i limit czasu.
_CHECKPOINT_EVERY: int = 500

#: Docelowy limit rozmiaru pojedynczego pola w module csv.
_FIELD_SIZE_LIMIT: int = 10_000_000


def _set_field_size_limit(limit: int = _FIELD_SIZE_LIMIT) -> None:
    """Podnosi limit rozmiaru pola modulu csv.

    Na czesci platform typ C long jest 32 bitowy i zbyt duza wartosc konczy sie
    OverflowError. W takim przypadku limit jest polowiony az do wartosci akceptowanej.
    """
    current = limit
    while current > 1024:
        try:
            csv.field_size_limit(current)
        except (OverflowError, ValueError):
            current //= 2
        else:
            return


def _looks_numeric(value: str) -> bool:
    """Czy wartosc wyglada na liczbe (dopuszcza przecinek dziesietny i spacje)."""
    cleaned = value.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    if not cleaned or not any(ch.isdigit() for ch in cleaned):
        return False
    try:
        float(cleaned)
    except ValueError:
        return False
    return True


def _is_header_row(first: Sequence[str], second: Sequence[str]) -> bool:
    """Pierwszy wiersz jest naglowkiem, gdy ma tyle samo pol co drugi i nie jest liczbowy."""
    if len(first) != len(second):
        return False
    values = [cell.strip() for cell in first if cell.strip()]
    if not values:
        return False
    return not all(_looks_numeric(value) for value in values)


def _detect_delimiter(sample: str, *, is_tsv: bool) -> str:
    """Wykrywa separator kolumn: najpierw sniffer, potem zliczanie wystapien."""
    default = "\t" if is_tsv else ","
    if not sample:
        return default
    try:
        sniffed = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except (csv.Error, IndexError):
        sniffed = ""
    if sniffed in _DELIMITERS:
        return sniffed

    lines = sample.splitlines()[:_COUNT_LINES]
    best = default
    best_count = 0
    for candidate in _DELIMITERS:
        count = sum(line.count(candidate) for line in lines)
        if count > best_count:
            best = candidate
            best_count = count
    return best


def _format_row(row: Sequence[str], header: Sequence[str] | None) -> str:
    """Sklada wiersz w tekst "Kolumna: wartosc | Kolumna2: wartosc2".

    Puste komorki sa pomijane. Pola bez odpowiadajacej kolumny (wiersz dluzszy niz
    naglowek) trafiaja do wyniku bez nazwy kolumny.
    """
    parts: list[str] = []
    for index, cell in enumerate(row):
        value = cell.strip()
        if not value:
            continue
        name = header[index] if header is not None and index < len(header) else ""
        parts.append(f"{name}: {value}" if name else value)
    return " | ".join(parts)


def _next_meaningful(records: Iterator[tuple[int, list[str]]]) -> tuple[int, list[str]] | None:
    """Zwraca kolejny wiersz zawierajacy jakakolwiek tresc albo None na koncu pliku."""
    for number, row in records:
        if any(cell.strip() for cell in row):
            return number, row
    return None


class CsvExtractor(Extractor):
    """Adapter plikow CSV i TSV oparty o modul csv biblioteki standardowej."""

    name = "csv"
    extensions = (".csv", ".tsv")
    mime_types = ("text/csv", "text/tab-separated-values")
    support_level = SupportLevel.FULL
    priority = 120

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        """Odczytuje plik i zwraca sekcje: opcjonalny naglowek oraz wiersze danych."""
        context.checkpoint()
        _set_field_size_limit()

        result = ExtractionResult(
            parser_name=self.name,
            support_level=self.support_level,
            origin=TextOrigin.NATIVE,
        )
        text, encoding = self._load_text(path, result)
        if not text.strip():
            raise EmptyDocumentError(
                f"Plik {path.name} nie zawiera żadnej treści.",
                details={"plik": path.name, "kodowanie": encoding},
            )

        delimiter = _detect_delimiter(self._sample(text), is_tsv=path.suffix.lower() == ".tsv")
        sections, header, rows_read = self._build_sections(
            text, delimiter=delimiter, context=context, result=result, file_name=path.name
        )
        if not any(section.kind == "table_row" for section in sections):
            raise EmptyDocumentError(
                f"Plik {path.name} nie zawiera wierszy danych możliwych do zaindeksowania.",
                details={"plik": path.name, "separator": delimiter},
            )

        result.sections = sections
        result.metadata = DocumentMetadata(
            extra={
                "encoding": encoding,
                "delimiter": delimiter,
                "has_header": bool(header),
                "columns": len(header),
                "data_rows": rows_read,
            }
        )
        return result

    # --- odczyt pliku ----------------------------------------------------------

    def _load_text(self, path: Path, result: ExtractionResult) -> tuple[str, str]:
        """Odczytuje plik jako tekst. Zwraca (tresc, nazwa uzytego kodowania)."""
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise ExtractionError(
                f"Nie udało się odczytać pliku {path.name}.",
                details={"plik": path.name},
                cause=exc,
            ) from exc
        if size == 0:
            raise EmptyDocumentError(f"Plik {path.name} jest pusty.", details={"plik": path.name})

        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ExtractionError(
                f"Nie udało się odczytać pliku {path.name}.",
                details={"plik": path.name},
                cause=exc,
            ) from exc

        decoded = decode_text(raw)
        result.warnings.extend(decoded.warnings)
        if decoded.encoding == "latin-1":
            result.warnings.append(
                "Kodowanie rozpoznano zapasowo jako latin-1, znaki moga być zniekształcone."
            )
        if not decoded.text and raw:
            raise CorruptedFileError(
                f"Nie udało się zdekodować pliku {path.name} żadnym ze znanych kodowań.",
                details={"plik": path.name},
            )
        return decoded.text, decoded.encoding

    def _sample(self, text: str) -> str:
        """Probka tekstu do wykrywania separatora, przycieta do pelnej linii."""
        sample = text[:_SAMPLE_CHARS]
        if len(text) > _SAMPLE_CHARS:
            cut = sample.rfind("\n")
            if cut > 0:
                sample = sample[:cut]
        return sample

    # --- budowa sekcji ---------------------------------------------------------

    def _build_sections(
        self,
        text: str,
        *,
        delimiter: str,
        context: ExtractionContext,
        result: ExtractionResult,
        file_name: str,
    ) -> tuple[list[ExtractedSection], list[str], int]:
        """Zamienia wiersze na sekcje.

        Zwraca (sekcje, naglowek, liczba odczytanych wierszy danych). Wiersze o innej
        liczbie pol niz naglowek sa dopasowywane po indeksie i nie przerywaja odczytu.
        """
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        records: Iterator[tuple[int, list[str]]] = enumerate(reader, start=1)
        sections: list[ExtractedSection] = []
        header: list[str] = []
        heading: str | None = None
        order = 0
        rows_read = 0
        max_rows = context.csv_max_rows if context.csv_max_rows > 0 else None

        try:
            first = _next_meaningful(records)
            second = _next_meaningful(records)
            pending: list[tuple[int, list[str]]] = []
            if first is not None and second is not None and _is_header_row(first[1], second[1]):
                header = [clean_text(cell) for cell in first[1]]
                heading = " | ".join(name for name in header if name) or None
                if heading:
                    sections.append(
                        ExtractedSection(
                            text=heading,
                            kind="table_header",
                            order=order,
                            row=first[0],
                            heading=heading,
                        )
                    )
                    order += 1
                pending.append(second)
            else:
                pending.extend(item for item in (first, second) if item is not None)

            for row_number, row in chain(pending, records):
                if max_rows is not None and rows_read >= max_rows:
                    result.warnings.append(
                        f"Przekroczono limit {max_rows} wierszy, "
                        "dalsza część pliku nie została zaindeksowana."
                    )
                    break
                rows_read += 1
                if rows_read % _CHECKPOINT_EVERY == 0:
                    context.checkpoint()
                cleaned = clean_text(_format_row(row, header or None))
                if not cleaned:
                    continue
                sections.append(
                    ExtractedSection(
                        text=cleaned,
                        kind="table_row",
                        order=order,
                        row=row_number,
                        heading=heading,
                    )
                )
                order += 1
        except csv.Error as exc:
            if not sections:
                raise CorruptedFileError(
                    f"Nie udało się odczytać struktury pliku {file_name}.",
                    details={"plik": file_name, "separator": delimiter},
                    cause=exc,
                ) from exc
            result.warnings.append(
                f"Odczyt przerwano po {rows_read} wierszach: uszkodzona struktura pliku."
            )

        return sections, header, rows_read


__all__ = ["CsvExtractor"]
