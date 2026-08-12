"""Wspolne narzedzia adapterow starych formatow Microsoft Office.

Modul zbiera to, co identyczne dla Worda i PowerPointa: tlumaczenie bledow
automatyzacji COM na wyjatki aplikacji, odczyt wlasciwosci wbudowanych,
metadane z bloku SummaryInformation kontenera OLE oraz skladanie sekcji
z surowego tekstu. Adaptery formatow trzymaja u siebie wylacznie logike
wlasnego formatu binarnego i wlasnego modelu obiektowego COM.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
from pathlib import Path
from typing import Any

from finddocs.errors import (
    CorruptedFileError,
    ExtractionError,
    PasswordProtectedError,
)
from finddocs.extractors.base import ExtractionContext
from finddocs.normalization.text import clean_text, fold_diacritics
from finddocs.types import DocumentMetadata, ExtractedSection

#: Co ile iteracji petli sprawdzac anulowanie i limit czasu.
CHECKPOINT_EVERY = 16

#: Ile znakow tekstu wystarczy, zeby ocenic jakosc dekodowania.
GARBAGE_PROBE_CHARS = 4000

#: Ostrzezenie dopisywane przez adaptery zapasowe czytajace format samodzielnie.
FALLBACK_WARNING = "Tekst odczytano zapasowym parserem, formatowanie i tabele moga być uproszczone"

#: msoAutomationSecurityForceDisable: aplikacja Office otwiera plik bez makr.
MSO_AUTOMATION_SECURITY_FORCE_DISABLE = 3

#: Limit czasu uzywany, gdy konfiguracja podaje wartosc niedodatnia.
DEFAULT_COM_TIMEOUT = 90.0

#: Celowo bledne haslo. Aplikacja Office zglosi blad zamiast czekac na okno.
BOGUS_OFFICE_KEY = "__brak__"

#: Wlasciwosci wbudowane pobierane z dokumentu przez COM.
COM_PROPERTY_NAMES: tuple[str, ...] = (
    "Title",
    "Author",
    "Subject",
    "Keywords",
    "Creation Date",
    "Last Save Time",
)

#: Fragmenty komunikatow Office swiadczace o zabezpieczeniu haslem (bez diakrytykow).
PASSWORD_MARKERS: tuple[str, ...] = (
    "haslo",
    "hasla",
    "haslem",
    "password",
    "zaszyfrow",
    "encrypt",
    "chronion",
    "protected",
    "-2146822880",
)

#: Fragmenty komunikatow Office swiadczace o uszkodzeniu pliku.
CORRUPTION_MARKERS: tuple[str, ...] = (
    "uszkodz",
    "corrupt",
    "nie jest prawidłow",
    "not a valid",
    "nieprawidłowy format",
    "unreadable",
)


# --- tlumaczenie bledow COM ------------------------------------------------------


def com_error_text(exc: BaseException) -> str:
    """Skleja wszystkie czesci komunikatu bledu COM w jeden napis."""
    parts: list[str] = [str(exc)]
    for arg in getattr(exc, "args", ()):
        if isinstance(arg, tuple):
            parts.extend(str(item) for item in arg)
        else:
            parts.append(str(arg))
    return " ".join(parts)


def translate_com_error(exc: BaseException, path: Path, app_label: str) -> ExtractionError:
    """Tlumaczy blad automatyzacji aplikacji Office na wyjatek aplikacji."""
    probe = fold_diacritics(com_error_text(exc)).casefold()
    details: dict[str, Any] = {"plik": path.name, "blad": type(exc).__name__}
    if any(marker in probe for marker in PASSWORD_MARKERS):
        return PasswordProtectedError(
            "Dokument jest zabezpieczony hasłem, nie można odczytać jego treści.",
            details=details,
            cause=exc,
        )
    if any(marker in probe for marker in CORRUPTION_MARKERS):
        return CorruptedFileError(
            f"{app_label} uznał dokument za uszkodzony lub niekompletny.",
            details=details,
            cause=exc,
        )
    return ExtractionError(
        f"{app_label} nie zdołał otworzyć dokumentu.",
        details=details,
        cause=exc,
    )


# --- metadane --------------------------------------------------------------------


def decode_meta_bytes(raw: bytes) -> str:
    """Dekoduje bajty metadanych: najpierw cp1250, potem latin-1."""
    try:
        return raw.decode("cp1250")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def clean_meta_text(value: object) -> str | None:
    """Sprowadza wartosc metadanej do czytelnego napisu albo None."""
    if isinstance(value, bytes):
        text = decode_meta_bytes(value)
    elif isinstance(value, str):
        text = value
    else:
        return None
    cleaned = clean_text(text.replace("\x00", " "))
    return cleaned or None


def plain_datetime(value: _dt.datetime) -> _dt.datetime:
    """Zwraca zwykly, naiwny ``datetime``. COM oddaje wlasna podklase z strefa czasowa."""
    return _dt.datetime(
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond,
    )


def coerce_datetime(value: object) -> _dt.datetime | None:
    """Sprowadza date z COM albo z olefile do naiwnego ``datetime``."""
    if isinstance(value, _dt.datetime):
        return plain_datetime(value)
    if isinstance(value, _dt.date):
        return _dt.datetime(value.year, value.month, value.day)
    if isinstance(value, str) and value.strip():
        with contextlib.suppress(ValueError):
            return plain_datetime(_dt.datetime.fromisoformat(value.strip()))
    return None


def read_builtin_properties(document: Any) -> dict[str, Any]:
    """Odczytuje wybrane wlasciwosci wbudowane COM, pomijajac te niedostepne."""
    properties: dict[str, Any] = {}
    builtin: Any = None
    with contextlib.suppress(Exception):
        builtin = document.BuiltInDocumentProperties
    if builtin is None:
        return properties
    for name in COM_PROPERTY_NAMES:
        with contextlib.suppress(Exception):
            properties[name] = builtin(name).Value
    return properties


def metadata_from_builtin_properties(properties: dict[str, Any]) -> DocumentMetadata:
    """Buduje metadane dokumentu z wlasciwosci wbudowanych Office."""
    return DocumentMetadata(
        title=clean_meta_text(properties.get("Title")),
        author=clean_meta_text(properties.get("Author")),
        subject=clean_meta_text(properties.get("Subject")),
        keywords=clean_meta_text(properties.get("Keywords")),
        created_at=coerce_datetime(properties.get("Creation Date")),
        modified_at=coerce_datetime(properties.get("Last Save Time")),
    )


def metadata_from_ole(ole: Any) -> DocumentMetadata:
    """Buduje metadane z bloku SummaryInformation kontenera OLE."""
    meta: Any = None
    with contextlib.suppress(Exception):
        meta = ole.get_metadata()
    if meta is None:
        return DocumentMetadata()
    pages = getattr(meta, "num_pages", None)
    return DocumentMetadata(
        title=clean_meta_text(getattr(meta, "title", None)),
        author=clean_meta_text(getattr(meta, "author", None)),
        subject=clean_meta_text(getattr(meta, "subject", None)),
        keywords=clean_meta_text(getattr(meta, "keywords", None)),
        created_at=coerce_datetime(getattr(meta, "create_time", None)),
        modified_at=coerce_datetime(getattr(meta, "last_saved_time", None)),
        page_count=pages if isinstance(pages, int) and pages > 0 else None,
    )


# --- skladanie sekcji ------------------------------------------------------------


def sections_from_text(
    text: str, context: ExtractionContext
) -> tuple[list[ExtractedSection], bool]:
    """Dzieli tekst na akapity i buduje sekcje. Zwraca (sekcje, czy_przyciete)."""
    sections: list[ExtractedSection] = []
    total = 0
    truncated = False
    for index, paragraph in enumerate(text.split("\n")):
        if index % CHECKPOINT_EVERY == 0:
            context.checkpoint()
        cleaned = clean_text(paragraph)
        if not cleaned:
            continue
        sections.append(ExtractedSection(text=cleaned, kind="text", order=len(sections)))
        total += len(cleaned)
        if total >= context.max_chars:
            truncated = True
            break
    return sections, truncated


def probe_text(sections: list[ExtractedSection]) -> str:
    """Krotka probka tekstu uzywana do oceny jakosci dekodowania."""
    probe: list[str] = []
    length = 0
    for section in sections:
        probe.append(section.text)
        length += len(section.text)
        if length >= GARBAGE_PROBE_CHARS:
            break
    return " ".join(probe)[:GARBAGE_PROBE_CHARS]


__all__ = [
    "BOGUS_OFFICE_KEY",
    "CHECKPOINT_EVERY",
    "COM_PROPERTY_NAMES",
    "CORRUPTION_MARKERS",
    "DEFAULT_COM_TIMEOUT",
    "FALLBACK_WARNING",
    "GARBAGE_PROBE_CHARS",
    "MSO_AUTOMATION_SECURITY_FORCE_DISABLE",
    "PASSWORD_MARKERS",
    "clean_meta_text",
    "coerce_datetime",
    "com_error_text",
    "decode_meta_bytes",
    "metadata_from_builtin_properties",
    "metadata_from_ole",
    "plain_datetime",
    "probe_text",
    "read_builtin_properties",
    "sections_from_text",
    "translate_com_error",
]
