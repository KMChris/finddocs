"""Parser plikow czysto tekstowych: txt, log, md, json, xml oraz plikow konfiguracyjnych.

Plik jest wczytywany do pamieci, dekodowany wykrytym kodowaniem i dzielony na sekcje.
Naturalna granica sekcji to pusta linia, czyli akapit. Gdy plik nie ma pustych linii,
tekst jest ciety na bloki o zblizonej wielkosci, zawsze na granicy nowej linii.

Parser nie rzuca wyjatkow bibliotek. Bledy odczytu sa tlumaczone na wyjatki
z ``finddocs.errors``.
"""

from __future__ import annotations

import codecs
import re
from pathlib import Path
from typing import Final

from finddocs.errors import CorruptedFileError, EmptyDocumentError, ExtractionError
from finddocs.extractors.base import ExtractionContext, Extractor
from finddocs.normalization.text import clean_text, looks_like_garbage
from finddocs.types import (
    DocumentMetadata,
    ExtractedSection,
    ExtractionResult,
    SupportLevel,
    TextOrigin,
)

#: Kodowania sprawdzane po kolei, gdy detekcja statystyczna nie da odpowiedzi.
FALLBACK_ENCODINGS: Final[tuple[str, ...]] = (
    "utf-8-sig",
    "cp1250",
    "iso-8859-2",
    "utf-16",
    "latin-1",
)

#: Ile poczatkowych bajtow wystarcza do rozpoznania kodowania.
DETECTION_SAMPLE_BYTES: Final[int] = 256 * 1024

#: Docelowa wielkosc bloku, gdy plik nie ma pustych linii.
BLOCK_TARGET_CHARS: Final[int] = 4000

#: Powyzej tej dlugosci nawet pojedynczy akapit jest dzielony na mniejsze bloki.
PARAGRAPH_SPLIT_THRESHOLD: Final[int] = BLOCK_TARGET_CHARS * 2

#: Co ile blokow sprawdzac anulowanie i limit czasu.
CHECKPOINT_EVERY: Final[int] = 16

#: Znaczniki kolejnosci bajtow. UTF-32 sprawdzany przed UTF-16, bo ma wspolny prefiks.
BOM_ENCODINGS: Final[tuple[tuple[bytes, str], ...]] = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)

_PARAGRAPH_SPLIT_RE = re.compile(r"\n[ \t\f\v]*\n")


def _canonical_encoding(name: str) -> str:
    """Ujednolica zapis nazwy kodowania do postaci malymi literami z lacznikiem."""
    return name.strip().lower().replace("_", "-")


def _bom_encoding(data: bytes) -> str | None:
    """Kodowanie wynikajace ze znacznika BOM albo None, gdy znacznika brak."""
    for marker, encoding in BOM_ENCODINGS:
        if data.startswith(marker):
            return encoding
    return None


def _detect_encoding(data: bytes) -> str | None:
    """Proponuje kodowanie na podstawie analizy statystycznej probki poczatku pliku."""
    try:
        from charset_normalizer import from_bytes
    except ImportError:
        return None
    try:
        best = from_bytes(data[:DETECTION_SAMPLE_BYTES]).best()
    except Exception:
        return None
    if best is None or not best.encoding:
        return None
    return _canonical_encoding(str(best.encoding))


def _candidate_encodings(data: bytes) -> list[str]:
    """Lista kodowan do sprawdzenia: BOM, detekcja statystyczna, potem stale fallbacki."""
    seen: set[str] = set()
    candidates: list[str] = []
    for name in (_bom_encoding(data), _detect_encoding(data), *FALLBACK_ENCODINGS):
        if not name:
            continue
        canonical = _canonical_encoding(name)
        if canonical in seen:
            continue
        seen.add(canonical)
        candidates.append(canonical)
    return candidates


def _decode_text(data: bytes) -> tuple[str, str, list[str]]:
    """Dekoduje bajty. Zwraca tekst, uzyte kodowanie i liste ostrzezen."""
    candidates = _candidate_encodings(data)
    for encoding in candidates:
        try:
            return data.decode(encoding), encoding, []
        except (UnicodeDecodeError, LookupError):
            continue
    warning = "Nie udalo sie jednoznacznie rozpoznac kodowania, czesc znakow zastapiono."
    fallback = candidates[0] if candidates else "utf-8"
    try:
        return data.decode(fallback, errors="replace"), fallback, [warning]
    except LookupError:
        return data.decode("utf-8", errors="replace"), "utf-8", [warning]


def _split_long_line(line: str, target: int) -> list[str]:
    """Tnie pojedyncza, bardzo dluga linie na kawalki o zadanej dlugosci."""
    if len(line) <= target:
        return [line]
    return [line[start : start + target] for start in range(0, len(line), target)]


def _split_by_size(text: str, target: int = BLOCK_TARGET_CHARS) -> list[str]:
    """Dzieli tekst na bloki o zblizonej wielkosci, przecinajac na granicy nowej linii."""
    blocks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.split("\n"):
        for piece in _split_long_line(line, target):
            if current and size + len(piece) + 1 > target:
                blocks.append("\n".join(current))
                current = []
                size = 0
            current.append(piece)
            size += len(piece) + 1
    if current:
        blocks.append("\n".join(current))
    return blocks


def _split_blocks(text: str) -> list[str]:
    """Dzieli tekst na akapity. Zbyt dlugie akapity tnie dodatkowo na mniejsze bloki."""
    paragraphs = _PARAGRAPH_SPLIT_RE.split(text)
    if len(paragraphs) <= 1:
        return _split_by_size(text)
    blocks: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) > PARAGRAPH_SPLIT_THRESHOLD:
            blocks.extend(_split_by_size(paragraph))
        else:
            blocks.append(paragraph)
    return blocks


class PlainTextExtractor(Extractor):
    """Adapter plikow tekstowych i prostych formatow strukturalnych."""

    name = "text"
    extensions = (".txt", ".log", ".md", ".json", ".xml", ".ini", ".cfg", ".yaml", ".yml")
    mime_types = ("text/plain", "text/markdown", "application/json", "application/xml")
    support_level = SupportLevel.FULL
    priority = 90

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        """Odczytuje plik tekstowy i zwraca sekcje odpowiadajace akapitom."""
        context.checkpoint()
        data, size_truncated = self._read_bytes(path, context)
        if not data.strip():
            raise EmptyDocumentError(
                f"Plik {path.name} nie zawiera zadnej tresci.",
                details={"plik": path.name},
            )

        text, encoding, decode_warnings = _decode_text(data)
        result = ExtractionResult(
            metadata=DocumentMetadata(title=path.stem, extra={"encoding": encoding}),
            origin=TextOrigin.NATIVE,
            parser_name=self.name,
            support_level=self.support_level,
        )
        result.warnings.extend(decode_warnings)
        if size_truncated:
            result.warnings.append(
                "Plik jest wiekszy niz dozwolony limit, odczytano tylko poczatek tresci."
            )
        if looks_like_garbage(text):
            result.warnings.append("Tekst wyglada na uszkodzony albo zle zdekodowany")

        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        self._fill_sections(normalized, context, result)
        if not result.sections:
            raise EmptyDocumentError(
                f"Plik {path.name} nie zawiera tekstu po oczyszczeniu.",
                details={"plik": path.name, "encoding": encoding},
            )
        return result

    def _read_bytes(self, path: Path, context: ExtractionContext) -> tuple[bytes, bool]:
        """Wczytuje plik, nie wiecej niz ``context.max_bytes``. Zwraca dane i flage obciecia."""
        limit = max(1, context.max_bytes)
        try:
            with path.open("rb") as handle:
                data = handle.read(limit + 1)
        except (FileNotFoundError, PermissionError) as exc:
            raise ExtractionError(
                f"Brak dostepu do pliku {path.name}.",
                details={"plik": path.name},
                cause=exc,
            ) from exc
        except OSError as exc:
            raise CorruptedFileError(
                f"Nie udalo sie odczytac pliku {path.name}.",
                details={"plik": path.name},
                cause=exc,
            ) from exc
        if len(data) > limit:
            return data[:limit], True
        return data, False

    def _fill_sections(
        self,
        text: str,
        context: ExtractionContext,
        result: ExtractionResult,
    ) -> None:
        """Zamienia bloki tekstu na sekcje wyniku, pilnujac limitu ``context.max_chars``."""
        blocks = _split_blocks(text)
        total = 0
        order = 0
        limit_reached = False
        for index, block in enumerate(blocks):
            if index % CHECKPOINT_EVERY == 0:
                context.checkpoint()
            cleaned = clean_text(block)
            if not cleaned:
                continue
            remaining = context.max_chars - total
            if remaining <= 0:
                limit_reached = True
                break
            if len(cleaned) > remaining:
                cleaned = cleaned[:remaining]
                limit_reached = True
            result.sections.append(
                ExtractedSection(
                    text=cleaned,
                    kind="text",
                    order=order,
                    origin=TextOrigin.NATIVE,
                )
            )
            total += len(cleaned)
            order += 1
            if limit_reached:
                break
        if limit_reached:
            result.warnings.append(
                f"Przekroczono limit {context.max_chars} znakow, dalsza tresc zostala pominieta."
            )


__all__ = [
    "BLOCK_TARGET_CHARS",
    "BOM_ENCODINGS",
    "CHECKPOINT_EVERY",
    "DETECTION_SAMPLE_BYTES",
    "FALLBACK_ENCODINGS",
    "PARAGRAPH_SPLIT_THRESHOLD",
    "PlainTextExtractor",
]
