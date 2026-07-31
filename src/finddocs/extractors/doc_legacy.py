"""Adaptery starego formatu Microsoft Word 97-2003 (.doc, .dot).

Format binarny Worda nie ma prostej reprezentacji tekstu, dlatego modul udostepnia
lancuch dwoch adapterow o roznych priorytetach:

* :class:`LegacyDocComExtractor` steruje zainstalowanym Microsoft Word przez COM.
  Daje najlepsza wiernosc odczytu, ale wymaga Worda i dziala tylko w Windows.
* :class:`LegacyDocOleExtractor` czyta plik w czystym Pythonie: rozbiera kontener OLE,
  tablice fragmentow (piece table) i dekoduje tekst. Dziala zawsze, ale gubi
  formatowanie oraz uklad tabel.

Uzyte struktury binarne (FIB, Clx, PlcPcd, PCD) sa opisane w specyfikacji [MS-DOC].
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import struct
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from finddocs.errors import (
    CorruptedFileError,
    DependencyUnavailableError,
    EmptyDocumentError,
    ExtractionError,
    ExtractionTimeoutError,
    FindDocsError,
    PasswordProtectedError,
    UnsupportedFormatError,
)
from finddocs.extractors.base import ExtractionContext, Extractor
from finddocs.logging_setup import get_logger
from finddocs.normalization.text import clean_text, fold_diacritics, looks_like_garbage
from finddocs.types import (
    DocumentMetadata,
    ExtractedSection,
    ExtractionResult,
    SupportLevel,
)

log = get_logger(__name__)

#: Co ile iteracji petli sprawdzac anulowanie i limit czasu.
_CHECKPOINT_EVERY = 16

#: Ile znakow tekstu wystarczy, zeby ocenic jakosc dekodowania.
_GARBAGE_PROBE_CHARS = 4000

_FALLBACK_WARNING = "Tekst odczytano zapasowym parserem, formatowanie i tabele moga być uproszczone"

# --- wspolne czyszczenie tekstu Worda ------------------------------------------

#: Znaki sterujace Worda i ich odpowiedniki w zwyklym tekscie.
_WORD_TRANSLATION: dict[int, str] = {
    0x07: " | ",  # koniec komorki tabeli
    0x0B: "\n",  # zlamanie wiersza
    0x0C: "\n",  # zlamanie strony lub sekcji
    0x0D: "\n",  # koniec akapitu
    0x1E: "-",  # lacznik nierozdzielajacy
    0x1F: "",  # lacznik opcjonalny
    0xA0: " ",  # spacja nierozdzielajaca
}

_FIELD_BEGIN = "\x13"
_FIELD_SEPARATOR = "\x14"
_FIELD_END = "\x15"

#: Znacznik konca komorki tabeli i jego postac z modelu obiektowego Worda.
_CELL_END = "\x07"
_CELL_END_PAIR = "\r\x07"


def _strip_field_codes(text: str) -> str:
    """Usuwa kody pol Worda, zostawiajac ich wynik widoczny dla czytelnika.

    Instrukcja pola znajduje sie miedzy znakami 0x13 i 0x14, wynik miedzy 0x14 i 0x15.
    Zagniezdzone pola sa liczone, zeby nie zgubic tekstu po ich zamknieciu.
    """
    parts: list[str] = []
    depth = 0
    for char in text:
        if char == _FIELD_BEGIN:
            depth += 1
        elif char == _FIELD_SEPARATOR:
            depth = max(0, depth - 1)
        elif char == _FIELD_END:
            depth = 0
        elif depth == 0:
            parts.append(char)
    return "".join(parts)


def _clean_word_text(text: str) -> str:
    """Zamienia znaki sterujace Worda na zwykly tekst z podzialem na akapity.

    Model obiektowy Worda konczy komorke tabeli para znakow 0x0D 0x07. Znak konca
    akapitu jest tam czescia znacznika komorki, wiec jest usuwany przed zamiana,
    zeby separator kolumn nie wyladowal na poczatku nastepnego wiersza.
    """
    if not text:
        return ""
    if _FIELD_BEGIN in text or _FIELD_SEPARATOR in text or _FIELD_END in text:
        text = _strip_field_codes(text)
    return text.replace(_CELL_END_PAIR, _CELL_END).translate(_WORD_TRANSLATION)


def _sections_from_text(
    text: str, context: ExtractionContext
) -> tuple[list[ExtractedSection], bool]:
    """Dzieli tekst na akapity i buduje sekcje. Zwraca (sekcje, czy_przyciete)."""
    sections: list[ExtractedSection] = []
    total = 0
    truncated = False
    for index, paragraph in enumerate(text.split("\n")):
        if index % _CHECKPOINT_EVERY == 0:
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


def _probe_text(sections: list[ExtractedSection]) -> str:
    """Krotka probka tekstu uzywana do oceny jakosci dekodowania."""
    probe: list[str] = []
    length = 0
    for section in sections:
        probe.append(section.text)
        length += len(section.text)
        if length >= _GARBAGE_PROBE_CHARS:
            break
    return " ".join(probe)[:_GARBAGE_PROBE_CHARS]


# --- wspolne metadane ----------------------------------------------------------


def _decode_meta_bytes(raw: bytes) -> str:
    """Dekoduje bajty metadanych: najpierw cp1250, potem latin-1."""
    try:
        return raw.decode("cp1250")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def _clean_meta_text(value: object) -> str | None:
    """Sprowadza wartosc metadanej do czytelnego napisu albo None."""
    if isinstance(value, bytes):
        text = _decode_meta_bytes(value)
    elif isinstance(value, str):
        text = value
    else:
        return None
    cleaned = clean_text(text.replace("\x00", " "))
    return cleaned or None


def _plain_datetime(value: _dt.datetime) -> _dt.datetime:
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


def _coerce_datetime(value: object) -> _dt.datetime | None:
    """Sprowadza date z COM albo z olefile do naiwnego ``datetime``."""
    if isinstance(value, _dt.datetime):
        return _plain_datetime(value)
    if isinstance(value, _dt.date):
        return _dt.datetime(value.year, value.month, value.day)
    if isinstance(value, str) and value.strip():
        with contextlib.suppress(ValueError):
            return _plain_datetime(_dt.datetime.fromisoformat(value.strip()))
    return None


# --- adapter oparty o automatyzacje Microsoft Word ------------------------------

#: msoAutomationSecurityForceDisable: Word otwiera plik z wylaczonymi makrami.
_MSO_AUTOMATION_SECURITY_FORCE_DISABLE = 3

#: wdDoNotSaveChanges.
_WD_DO_NOT_SAVE_CHANGES = 0

#: Celowo bledne haslo. Word zglosi blad zamiast czekac na okno dialogowe.
_BOGUS_DOC_KEY = "__brak__"

#: Limit czasu uzywany, gdy konfiguracja podaje wartosc niedodatnia.
_DEFAULT_COM_TIMEOUT = 90.0

#: Wlasciwosci wbudowane pobierane z dokumentu.
_COM_PROPERTY_NAMES: tuple[str, ...] = (
    "Title",
    "Author",
    "Subject",
    "Keywords",
    "Creation Date",
    "Last Save Time",
)

#: Fragmenty komunikatow Worda swiadczace o zabezpieczeniu haslem (bez diakrytykow).
_PASSWORD_MARKERS: tuple[str, ...] = (
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

#: Fragmenty komunikatow Worda swiadczace o uszkodzeniu pliku.
_CORRUPTION_MARKERS: tuple[str, ...] = (
    "uszkodz",
    "corrupt",
    "nie jest prawidłow",
    "not a valid",
    "nieprawidłowy format",
    "unreadable",
)


@dataclass(slots=True)
class _ComCallState:
    """Stan dzielony miedzy watkiem automatyzacji a watkiem wywolujacym."""

    app: Any = None
    text: str = ""
    properties: dict[str, Any] = field(default_factory=dict)
    error: BaseException | None = None


def _error_text(exc: BaseException) -> str:
    """Skleja wszystkie czesci komunikatu bledu COM w jeden napis."""
    parts: list[str] = [str(exc)]
    for arg in getattr(exc, "args", ()):
        if isinstance(arg, tuple):
            parts.extend(str(item) for item in arg)
        else:
            parts.append(str(arg))
    return " ".join(parts)


def _translate_com_error(exc: BaseException, path: Path) -> ExtractionError:
    """Tlumaczy blad automatyzacji Worda na wyjatek aplikacji."""
    probe = fold_diacritics(_error_text(exc)).casefold()
    details: dict[str, Any] = {"plik": path.name, "blad": type(exc).__name__}
    if any(marker in probe for marker in _PASSWORD_MARKERS):
        return PasswordProtectedError(
            "Dokument Word jest zabezpieczony hasłem, nie można odczytać jego treści.",
            details=details,
            cause=exc,
        )
    if any(marker in probe for marker in _CORRUPTION_MARKERS):
        return CorruptedFileError(
            "Microsoft Word uznał dokument za uszkodzony lub niekompletny.",
            details=details,
            cause=exc,
        )
    return ExtractionError(
        "Microsoft Word nie zdołał otworzyć dokumentu.",
        details=details,
        cause=exc,
    )


def _read_com_properties(document: Any) -> dict[str, Any]:
    """Odczytuje wybrane wlasciwosci wbudowane, pomijajac te niedostepne."""
    properties: dict[str, Any] = {}
    builtin: Any = None
    with contextlib.suppress(Exception):
        builtin = document.BuiltInDocumentProperties
    if builtin is None:
        return properties
    for name in _COM_PROPERTY_NAMES:
        with contextlib.suppress(Exception):
            properties[name] = builtin(name).Value
    return properties


def _metadata_from_com(properties: dict[str, Any]) -> DocumentMetadata:
    """Buduje metadane dokumentu z wlasciwosci wbudowanych Worda."""
    return DocumentMetadata(
        title=_clean_meta_text(properties.get("Title")),
        author=_clean_meta_text(properties.get("Author")),
        subject=_clean_meta_text(properties.get("Subject")),
        keywords=_clean_meta_text(properties.get("Keywords")),
        created_at=_coerce_datetime(properties.get("Creation Date")),
        modified_at=_coerce_datetime(properties.get("Last Save Time")),
    )


class LegacyDocComExtractor(Extractor):
    """Odczyt .doc przez automatyzacje zainstalowanego Microsoft Word.

    Word jest uruchamiany w osobnym procesie, niewidocznie, z wylaczonymi makrami
    i komunikatami. Calosc pracy odbywa sie w osobnym watku, bo wywolania COM
    potrafia zawisnac na oknie dialogowym, ktorego nie da sie zamknac programowo.
    """

    name = "doc_com"
    extensions = (".doc", ".dot")
    mime_types = ("application/msword",)
    support_level = SupportLevel.LIMITED
    priority = 115

    #: Wynik jednorazowego sprawdzenia srodowiska, wspolny dla wszystkich instancji.
    _availability: ClassVar[bool | None] = None
    _availability_reason: ClassVar[str] = ""

    # --- dostepnosc ---

    @staticmethod
    def _probe_environment() -> tuple[bool, str]:
        """Sprawdza system, pakiet pywin32 oraz wpis ProgID Worda w rejestrze."""
        if sys.platform != "win32":
            return False, "Automatyzacja Microsoft Word działa tylko w systemie Windows."
        try:
            import winreg

            import pythoncom  # noqa: F401
            import win32com.client  # noqa: F401
        except ImportError:
            return False, "Brak pakietu pywin32 wymaganego do automatyzacji Microsoft Word."
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Word.Application"):
                pass
        except OSError:
            return False, "Microsoft Word nie jest zainstalowany."
        return True, ""

    def is_available(self) -> bool:
        if LegacyDocComExtractor._availability is None:
            available, reason = self._probe_environment()
            LegacyDocComExtractor._availability = available
            LegacyDocComExtractor._availability_reason = reason
            log.debug("doc_com.availability", available=available, reason=reason)
        return LegacyDocComExtractor._availability

    def unavailable_reason(self) -> str:
        self.is_available()
        return LegacyDocComExtractor._availability_reason

    # --- ekstrakcja ---

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        """Otwiera dokument w Wordzie i pobiera z niego tekst oraz metadane."""
        if not context.office_com_enabled:
            raise DependencyUnavailableError(
                "Automatyzacja Microsoft Word jest wyłączona w konfiguracji aplikacji.",
                details={"parser": self.name},
            )
        if not self.is_available():
            raise DependencyUnavailableError(
                self.unavailable_reason() or "Microsoft Word nie jest dostępny.",
                details={"parser": self.name},
            )
        context.checkpoint()

        state = _ComCallState()
        thread = threading.Thread(
            target=self._run_word,
            args=(path, state),
            name="finddocs-doc-com",
            daemon=True,
        )
        thread.start()
        timeout = float(context.office_com_timeout_seconds)
        if timeout <= 0:
            timeout = _DEFAULT_COM_TIMEOUT
        thread.join(timeout)
        if thread.is_alive():
            self._force_quit(state)
            raise ExtractionTimeoutError(
                f"Microsoft Word nie odczytał dokumentu w ciągu {timeout:.0f} s.",
                details={"parser": self.name, "plik": path.name},
            )
        if state.error is not None:
            if isinstance(state.error, FindDocsError):
                raise state.error
            raise _translate_com_error(state.error, path)

        sections, truncated = _sections_from_text(_clean_word_text(state.text), context)
        if not sections:
            raise EmptyDocumentError(
                "Dokument Word nie zawiera tekstu możliwego do zaindeksowania.",
                details={"parser": self.name, "plik": path.name},
            )
        result = ExtractionResult(
            sections=sections,
            metadata=_metadata_from_com(state.properties),
            parser_name=self.name,
            support_level=self.support_level,
        )
        if truncated:
            result.warnings.append("Dokument był bardzo długi, tekst przycięto do limitu znaków.")
        return result

    # --- praca w watku ---

    @staticmethod
    def _run_word(path: Path, state: _ComCallState) -> None:
        """Cialo watku automatyzacji. Bledy trafiaja do stanu, nie sa wyrzucane."""
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        document: Any = None
        try:
            # DispatchEx wymusza osobny proces Worda, niezalezny od sesji uzytkownika.
            dispatch: Any = win32com.client.DispatchEx
            app: Any = dispatch("Word.Application")
            state.app = app
            app.Visible = False
            app.DisplayAlerts = 0
            with contextlib.suppress(Exception):
                app.AutomationSecurity = _MSO_AUTOMATION_SECURITY_FORCE_DISABLE
            # Word rozwiazuje sciezki wzgledne wzgledem wlasnego katalogu roboczego,
            # dlatego zawsze przekazujemy sciezke bezwzgledna.
            document = app.Documents.Open(
                str(Path(path).resolve()),
                ConfirmConversions=False,
                ReadOnly=True,
                AddToRecentFiles=False,
                PasswordDocument=_BOGUS_DOC_KEY,
                WritePasswordDocument=_BOGUS_DOC_KEY,
                Visible=False,
            )
            state.text = str(document.Content.Text or "")
            state.properties = _read_com_properties(document)
        except Exception as exc:
            state.error = exc
        finally:
            if document is not None:
                with contextlib.suppress(Exception):
                    document.Close(SaveChanges=_WD_DO_NOT_SAVE_CHANGES)
            app_ref = state.app
            state.app = None
            if app_ref is not None:
                with contextlib.suppress(Exception):
                    app_ref.Quit(SaveChanges=_WD_DO_NOT_SAVE_CHANGES)
            pythoncom.CoUninitialize()

    @staticmethod
    def _force_quit(state: _ComCallState) -> None:
        """Proba zamkniecia Worda po przekroczeniu limitu czasu."""
        app = state.app
        if app is None:
            return
        with contextlib.suppress(Exception):
            app.DisplayAlerts = 0
        with contextlib.suppress(Exception):
            app.Quit(SaveChanges=_WD_DO_NOT_SAVE_CHANGES)


# --- adapter czysto pythonowy ---------------------------------------------------

_WORD_STREAM = "WordDocument"
_TABLE_STREAMS: tuple[str, str] = ("0Table", "1Table")

#: Minimalny sensowny rozmiar naglowka FIB (do fcMac wlacznie).
_FIB_MIN_SIZE = 0x0020

#: Rozmiar naglowka pozwalajacy odczytac fcClx i lcbClx.
_FIB_CLX_SIZE = 0x01AA

_OFF_FLAGS = 0x000A
_OFF_FC_MIN = 0x0018
_OFF_FC_MAC = 0x001C
_OFF_FC_CLX = 0x01A2
_OFF_LCB_CLX = 0x01A6

_FLAG_COMPLEX = 0x0004
_FLAG_ENCRYPTED = 0x0100
_FLAG_WHICH_TBL_STM = 0x0200

_CLX_PRC = 0x01
_CLX_PCDT = 0x02

#: Rozmiar jednej struktury PCD w tablicy fragmentow.
_PCD_SIZE = 8

#: Bit informujacy, ze fragment jest zapisany jednobajtowo (cp1252).
_FC_COMPRESSED = 0x40000000
_FC_MASK = 0x3FFFFFFF

_BINARY_ERRORS = (OSError, ValueError, struct.error)


@dataclass(frozen=True, slots=True)
class _Piece:
    """Jeden fragment tekstu z tablicy fragmentow dokumentu."""

    offset: int
    """Pozycja bajtowa w strumieniu WordDocument."""

    chars: int
    """Liczba znaków zapisanych we fragmencie."""

    compressed: bool
    """True: jeden bajt na znak (cp1252). False: UTF-16LE."""


@dataclass(frozen=True, slots=True)
class _DocStreams:
    """Surowe strumienie dokumentu wraz z odczytanymi flagami FIB."""

    fib: bytes
    table: bytes
    flags: int
    metadata: DocumentMetadata


def _metadata_from_ole(ole: Any) -> DocumentMetadata:
    """Buduje metadane z bloku SummaryInformation kontenera OLE."""
    meta: Any = None
    with contextlib.suppress(Exception):
        meta = ole.get_metadata()
    if meta is None:
        return DocumentMetadata()
    pages = getattr(meta, "num_pages", None)
    return DocumentMetadata(
        title=_clean_meta_text(getattr(meta, "title", None)),
        author=_clean_meta_text(getattr(meta, "author", None)),
        subject=_clean_meta_text(getattr(meta, "subject", None)),
        keywords=_clean_meta_text(getattr(meta, "keywords", None)),
        created_at=_coerce_datetime(getattr(meta, "create_time", None)),
        modified_at=_coerce_datetime(getattr(meta, "last_saved_time", None)),
        page_count=pages if isinstance(pages, int) and pages > 0 else None,
    )


def _slice_clx(table: bytes, fc_clx: int, lcb_clx: int) -> bytes:
    """Wycina strukture Clx ze strumienia tabeli, sprawdzajac zakres."""
    if fc_clx < 0 or lcb_clx <= 0 or fc_clx + lcb_clx > len(table):
        raise CorruptedFileError(
            "Tablica fragmentow tekstu wskazuje poza strumień tabeli dokumentu.",
            details={"fcClx": fc_clx, "lcbClx": lcb_clx, "rozmiar_tabeli": len(table)},
        )
    return table[fc_clx : fc_clx + lcb_clx]


def _find_plc_pcd(clx: bytes) -> bytes:
    """Znajduje blok PlcPcd w strukturze Clx, pomijajac bloki Prc."""
    position = 0
    size = len(clx)
    while position < size:
        marker = clx[position]
        if marker == _CLX_PRC:
            if position + 3 > size:
                return b""
            cb_grpprl = int(struct.unpack_from("<H", clx, position + 1)[0])
            position += 3 + cb_grpprl
            continue
        if marker == _CLX_PCDT:
            if position + 5 > size:
                return b""
            lcb = int(struct.unpack_from("<I", clx, position + 1)[0])
            start = position + 5
            return clx[start : start + lcb]
        return b""
    return b""


def _parse_piece_table(clx: bytes) -> list[_Piece]:
    """Rozbiera PlcPcd na liste fragmentow tekstu."""
    plc = _find_plc_pcd(clx)
    minimal = 4 + 4 + _PCD_SIZE
    if len(plc) < minimal:
        return []
    count = (len(plc) - 4) // (4 + _PCD_SIZE)
    if count <= 0:
        return []
    positions = [int(struct.unpack_from("<i", plc, 4 * i)[0]) for i in range(count + 1)]
    pcd_base = 4 * (count + 1)
    pieces: list[_Piece] = []
    for index in range(count):
        chars = positions[index + 1] - positions[index]
        if chars <= 0:
            continue
        raw_fc = int(struct.unpack_from("<I", plc, pcd_base + _PCD_SIZE * index + 2)[0])
        compressed = bool(raw_fc & _FC_COMPRESSED)
        offset = (raw_fc & _FC_MASK) >> 1 if compressed else raw_fc & _FC_MASK
        pieces.append(_Piece(offset=offset, chars=chars, compressed=compressed))
    return pieces


def _text_from_pieces(
    fib: bytes,
    pieces: list[_Piece],
    context: ExtractionContext,
    warnings: list[str],
) -> str:
    """Skleja tekst z fragmentow, dekodujac kazdy zgodnie z jego kodowaniem."""
    parts: list[str] = []
    total = 0
    skipped = 0
    for index, piece in enumerate(pieces):
        if index % _CHECKPOINT_EVERY == 0:
            context.checkpoint()
        length = piece.chars if piece.compressed else piece.chars * 2
        end = piece.offset + length
        if piece.offset < 0 or end > len(fib):
            skipped += 1
            continue
        raw = fib[piece.offset : end]
        encoding = "cp1252" if piece.compressed else "utf-16-le"
        parts.append(raw.decode(encoding, errors="replace"))
        total += piece.chars
        if total >= context.max_chars:
            warnings.append("Dokument był bardzo długi, tekst przycięto do limitu znaków.")
            break
    if skipped and not parts:
        raise CorruptedFileError(
            "Wszystkie fragmenty tekstu wskazuja poza zawartość pliku.",
            details={"fragmenty": len(pieces)},
        )
    if skipped:
        warnings.append(f"Pominięto {skipped} uszkodzonych fragmentow tekstu dokumentu.")
    return "".join(parts)


def _text_from_range(fib: bytes, fc_min: int, fc_mac: int) -> str:
    """Odczyt zapasowy: caly tekst lezy zwarcie miedzy fcMin a fcMac."""
    if fc_min < 0 or fc_mac <= fc_min or fc_mac > len(fib):
        raise CorruptedFileError(
            "Zakres tekstu w nagłówku dokumentu Word jest nieprawidłowy.",
            details={"fcMin": fc_min, "fcMac": fc_mac, "rozmiar": len(fib)},
        )
    return fib[fc_min:fc_mac].decode("cp1252", errors="replace")


def _document_text(streams: _DocStreams, context: ExtractionContext, warnings: list[str]) -> str:
    """Wybiera sciezke odczytu tekstu: tablica fragmentow albo zwarty zakres."""
    fib = streams.fib
    fc_min = int(struct.unpack_from("<i", fib, _OFF_FC_MIN)[0])
    fc_mac = int(struct.unpack_from("<i", fib, _OFF_FC_MAC)[0])

    pieces: list[_Piece] = []
    if len(fib) >= _FIB_CLX_SIZE and streams.table:
        fc_clx = int(struct.unpack_from("<i", fib, _OFF_FC_CLX)[0])
        lcb_clx = int(struct.unpack_from("<i", fib, _OFF_LCB_CLX)[0])
        if lcb_clx > 0:
            pieces = _parse_piece_table(_slice_clx(streams.table, fc_clx, lcb_clx))
    if pieces:
        return _text_from_pieces(fib, pieces, context, warnings)

    if streams.flags & _FLAG_COMPLEX:
        warnings.append(
            "Dokument zapisano w trybie szybkiego zapisu, a tablica fragmentow jest pusta. "
            "Kolejnosc tekstu moze byc zaburzona."
        )
    return _text_from_range(fib, fc_min, fc_mac)


class LegacyDocOleExtractor(Extractor):
    """Zapasowy odczyt .doc bez Microsoft Word, wprost z kontenera OLE.

    Adapter rozbiera naglowek FIB, znajduje tablice fragmentow tekstu w strumieniu
    tabeli i dekoduje kazdy fragment osobno. Nie odtwarza formatowania ani ukladu
    tabel, ale pozwala zaindeksowac tresc na komputerze bez pakietu Office.
    """

    name = "doc_ole"
    extensions = (".doc", ".dot")
    mime_types = ("application/msword",)
    support_level = SupportLevel.EXPERIMENTAL
    priority = 60

    def is_available(self) -> bool:
        try:
            import olefile  # noqa: F401
        except ImportError:
            return False
        return True

    def unavailable_reason(self) -> str:
        if self.is_available():
            return ""
        return "Brak biblioteki olefile wymaganej do odczytu plików Word 97-2003."

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        """Odczytuje tekst i metadane pliku .doc bez udzialu Microsoft Word."""
        context.checkpoint()
        streams = self._load_streams(path)
        warnings: list[str] = [_FALLBACK_WARNING]
        text = _clean_word_text(_document_text(streams, context, warnings))
        sections, truncated = _sections_from_text(text, context)
        if not sections:
            raise EmptyDocumentError(
                "Dokument Word nie zawiera tekstu możliwego do zaindeksowania.",
                details={"parser": self.name, "plik": path.name},
            )
        if truncated:
            warnings.append("Dokument był bardzo długi, tekst przycięto do limitu znaków.")
        if looks_like_garbage(_probe_text(sections)):
            warnings.append(
                "Odczytany tekst wygląda na uszkodzony lub zapisany w nieznanym kodowaniu."
            )
        return ExtractionResult(
            sections=sections,
            metadata=streams.metadata,
            parser_name=self.name,
            support_level=self.support_level,
            warnings=warnings,
        )

    def _load_streams(self, path: Path) -> _DocStreams:
        """Otwiera kontener OLE i pobiera strumienie potrzebne do odczytu tekstu."""
        try:
            import olefile
        except ImportError as exc:
            raise DependencyUnavailableError(
                "Brak biblioteki olefile wymaganej do odczytu plików Word 97-2003.",
                details={"parser": self.name},
                cause=exc,
            ) from exc

        try:
            is_ole = olefile.isOleFile(str(path))
        except _BINARY_ERRORS as exc:
            raise CorruptedFileError(
                "Nie udało się odczytać pliku Word 97-2003.",
                details={"plik": path.name},
                cause=exc,
            ) from exc
        if not is_ole:
            raise UnsupportedFormatError(
                "Plik nie jest dokumentem Word 97-2003, brak kontenera OLE.",
                details={"plik": path.name, "parser": self.name},
            )

        try:
            with olefile.OleFileIO(str(path)) as ole:
                if not ole.exists(_WORD_STREAM):
                    raise UnsupportedFormatError(
                        "Kontener OLE nie zawiera strumienia WordDocument.",
                        details={"plik": path.name, "parser": self.name},
                    )
                fib = bytes(ole.openstream(_WORD_STREAM).read())
                if len(fib) < _FIB_MIN_SIZE:
                    raise CorruptedFileError(
                        "Nagłówek dokumentu Word jest niekompletny.",
                        details={"plik": path.name, "rozmiar": len(fib)},
                    )
                flags = int(struct.unpack_from("<H", fib, _OFF_FLAGS)[0])
                if flags & _FLAG_ENCRYPTED:
                    raise PasswordProtectedError(
                        "Dokument Word jest zaszyfrowany albo zabezpieczony hasłem.",
                        details={"plik": path.name},
                    )
                table = self._read_table_stream(ole, flags)
                metadata = _metadata_from_ole(ole)
        except FindDocsError:
            raise
        except _BINARY_ERRORS as exc:
            raise CorruptedFileError(
                "Struktura pliku Word 97-2003 jest uszkodzona.",
                details={"plik": path.name},
                cause=exc,
            ) from exc
        return _DocStreams(fib=fib, table=table, flags=flags, metadata=metadata)

    @staticmethod
    def _read_table_stream(ole: Any, flags: int) -> bytes:
        """Wczytuje strumien tabeli wskazany przez flage fWhichTblStm.

        Gdy wskazany strumien nie istnieje, probowany jest ten drugi. Stare pliki
        Worda 6 i 95 nie maja zadnego z nich i wtedy zwracany jest pusty ciag.
        """
        preferred = _TABLE_STREAMS[1] if flags & _FLAG_WHICH_TBL_STM else _TABLE_STREAMS[0]
        for candidate in (preferred, *_TABLE_STREAMS):
            if ole.exists(candidate):
                return bytes(ole.openstream(candidate).read())
        return b""


__all__ = ["LegacyDocComExtractor", "LegacyDocOleExtractor"]
