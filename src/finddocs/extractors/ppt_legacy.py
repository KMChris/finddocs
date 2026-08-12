"""Adaptery starego formatu Microsoft PowerPoint 97-2003 (.ppt, .pps, .pot).

Format binarny PowerPointa nie ma prostej reprezentacji tekstu, dlatego modul
udostepnia lancuch dwoch adapterow o roznych priorytetach, wzorem plikow .doc:

* :class:`LegacyPptComExtractor` steruje zainstalowanym Microsoft PowerPoint
  przez COM. Zachowuje podzial na slajdy, tytuly i notatki prelegenta, ale
  wymaga PowerPointa i dziala tylko w Windows.
* :class:`LegacyPptOleExtractor` czyta plik w czystym Pythonie: rozbiera
  kontener OLE i zbiera rekordy tekstowe (TextCharsAtom, TextBytesAtom)
  ze strumienia PowerPoint Document. Dziala zawsze, ale gubi przypisanie
  tekstu do slajdow.

Struktury binarne (RecordHeader, CurrentUserAtom, atomy tekstowe) sa opisane
w specyfikacji [MS-PPT].
"""

from __future__ import annotations

import contextlib
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
    ExtractionTimeoutError,
    FindDocsError,
    PasswordProtectedError,
    UnsupportedFormatError,
)
from finddocs.extractors.base import ExtractionContext, Extractor
from finddocs.extractors.office_com import (
    BOGUS_OFFICE_KEY,
    CHECKPOINT_EVERY,
    DEFAULT_COM_TIMEOUT,
    FALLBACK_WARNING,
    MSO_AUTOMATION_SECURITY_FORCE_DISABLE,
    metadata_from_builtin_properties,
    metadata_from_ole,
    probe_text,
    read_builtin_properties,
    sections_from_text,
    translate_com_error,
)
from finddocs.logging_setup import get_logger
from finddocs.normalization.text import clean_text, looks_like_garbage
from finddocs.types import (
    ExtractedSection,
    ExtractionResult,
    SupportLevel,
    TextOrigin,
)

log = get_logger(__name__)

#: Etykieta aplikacji w komunikatach bledow automatyzacji.
_APP_LABEL = "Microsoft PowerPoint"

#: Maksymalna dlugosc naglowka przypisywanego sekcjom slajdu.
_MAX_HEADING_CHARS = 200

#: Znaki konca akapitu i zlamania wiersza w tekscie PowerPointa.
_PPT_TRANSLATION: dict[int, str] = {
    0x0D: "\n",
    0x0B: "\n",
    0xA0: " ",
}

# --- adapter oparty o automatyzacje Microsoft PowerPoint -------------------------

#: Shape.Type ksztaltu grupujacego (msoGroup).
_MSO_GROUP = 6

#: PlaceholderFormat.Type tresci notatek prelegenta (ppPlaceholderBody).
_PP_PLACEHOLDER_BODY = 2


@dataclass(slots=True)
class _SlideText:
    """Tekst jednego slajdu zebrany w watku automatyzacji."""

    number: int
    title: str = ""
    texts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _ComCallState:
    """Stan dzielony miedzy watkiem automatyzacji a watkiem wywolujacym."""

    app: Any = None
    slides: list[_SlideText] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    error: BaseException | None = None


class LegacyPptComExtractor(Extractor):
    """Odczyt .ppt przez automatyzacje zainstalowanego Microsoft PowerPoint.

    PowerPoint jest uruchamiany w osobnym procesie, z wylaczonymi makrami,
    a prezentacja jest otwierana bez okna. Calosc pracy odbywa sie w osobnym
    watku, bo wywolania COM potrafia zawisnac na oknie dialogowym, ktorego
    nie da sie zamknac programowo.
    """

    name = "ppt_com"
    extensions = (".ppt", ".pps", ".pot")
    mime_types = ("application/vnd.ms-powerpoint",)
    support_level = SupportLevel.LIMITED
    priority = 115

    #: Wynik jednorazowego sprawdzenia srodowiska, wspolny dla wszystkich instancji.
    _availability: ClassVar[bool | None] = None
    _availability_reason: ClassVar[str] = ""

    # --- dostepnosc ---

    @staticmethod
    def _probe_environment() -> tuple[bool, str]:
        """Sprawdza system, pakiet pywin32 oraz wpis ProgID PowerPointa w rejestrze."""
        if sys.platform != "win32":
            return False, "Automatyzacja Microsoft PowerPoint działa tylko w systemie Windows."
        try:
            import winreg

            import pythoncom  # noqa: F401
            import win32com.client  # noqa: F401
        except ImportError:
            return False, "Brak pakietu pywin32 wymaganego do automatyzacji Microsoft PowerPoint."
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "PowerPoint.Application"):
                pass
        except OSError:
            return False, "Microsoft PowerPoint nie jest zainstalowany."
        return True, ""

    def is_available(self) -> bool:
        if LegacyPptComExtractor._availability is None:
            available, reason = self._probe_environment()
            LegacyPptComExtractor._availability = available
            LegacyPptComExtractor._availability_reason = reason
            log.debug("ppt_com.availability", available=available, reason=reason)
        return LegacyPptComExtractor._availability

    def unavailable_reason(self) -> str:
        self.is_available()
        return LegacyPptComExtractor._availability_reason

    # --- ekstrakcja ---

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        """Otwiera prezentacje w PowerPoincie i pobiera tekst slajdow oraz metadane."""
        if not context.office_com_enabled:
            raise DependencyUnavailableError(
                "Automatyzacja Microsoft PowerPoint jest wyłączona w konfiguracji aplikacji.",
                details={"parser": self.name},
            )
        if not self.is_available():
            raise DependencyUnavailableError(
                self.unavailable_reason() or "Microsoft PowerPoint nie jest dostępny.",
                details={"parser": self.name},
            )
        context.checkpoint()

        state = _ComCallState()
        thread = threading.Thread(
            target=self._run_powerpoint,
            args=(path, state),
            name="finddocs-ppt-com",
            daemon=True,
        )
        thread.start()
        timeout = float(context.office_com_timeout_seconds)
        if timeout <= 0:
            timeout = DEFAULT_COM_TIMEOUT
        thread.join(timeout)
        if thread.is_alive():
            self._force_quit(state)
            raise ExtractionTimeoutError(
                f"Microsoft PowerPoint nie odczytał prezentacji w ciągu {timeout:.0f} s.",
                details={"parser": self.name, "plik": path.name},
            )
        if state.error is not None:
            if isinstance(state.error, FindDocsError):
                raise state.error
            raise translate_com_error(state.error, path, _APP_LABEL)

        result = self._build_result(state, context)
        if not result.sections:
            raise EmptyDocumentError(
                "Prezentacja nie zawiera tekstu możliwego do zaindeksowania.",
                details={"parser": self.name, "plik": path.name},
            )
        return result

    def _build_result(self, state: _ComCallState, context: ExtractionContext) -> ExtractionResult:
        """Sklada sekcje ze slajdow zebranych w watku automatyzacji."""
        result = ExtractionResult(
            metadata=metadata_from_builtin_properties(state.properties),
            origin=TextOrigin.NATIVE,
            parser_name=self.name,
            support_level=self.support_level,
        )
        chars = 0
        truncated = False
        for slide in state.slides:
            context.checkpoint()
            if truncated:
                break
            heading = clean_text(slide.title)[:_MAX_HEADING_CHARS] or None
            entries: list[tuple[str, str | None]] = [(text, None) for text in slide.texts]
            entries.extend((note, "notatki prelegenta") for note in slide.notes)
            for text, source in entries:
                cleaned = clean_text(text.translate(_PPT_TRANSLATION))
                if not cleaned:
                    continue
                remaining = context.max_chars - chars
                if remaining <= 0:
                    truncated = True
                    break
                if len(cleaned) > remaining:
                    cleaned = cleaned[:remaining].rstrip()
                    truncated = True
                    if not cleaned:
                        break
                chars += len(cleaned)
                result.sections.append(
                    ExtractedSection(
                        text=cleaned,
                        kind="text",
                        order=len(result.sections),
                        page=slide.number,
                        origin=TextOrigin.NATIVE,
                        heading=heading,
                        extra={"zrodlo": source} if source else {},
                    )
                )
        if truncated:
            result.warnings.append(
                "Prezentacja przekroczyła limit długości tekstu, zaindeksowano tylko początek."
            )
        if state.slides:
            result.total_pages = state.slides[-1].number
            result.metadata.page_count = state.slides[-1].number
        return result

    # --- praca w watku ---

    @staticmethod
    def _run_powerpoint(path: Path, state: _ComCallState) -> None:
        """Cialo watku automatyzacji. Bledy trafiaja do stanu, nie sa wyrzucane."""
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        presentation: Any = None
        try:
            dispatch: Any = win32com.client.DispatchEx
            app: Any = dispatch("PowerPoint.Application")
            state.app = app
            with contextlib.suppress(Exception):
                app.DisplayAlerts = 1  # ppAlertsNone
            with contextlib.suppress(Exception):
                app.AutomationSecurity = MSO_AUTOMATION_SECURITY_FORCE_DISABLE
            # PowerPoint nie przyjmuje parametru hasla w Open. Haslo dokleja sie
            # do nazwy pliku po podwojnym dwukropku; celowo bledne haslo daje
            # blad zamiast okna dialogowego przy pliku chronionym.
            target = f"{Path(path).resolve()}::{BOGUS_OFFICE_KEY}::{BOGUS_OFFICE_KEY}"
            presentation = app.Presentations.Open(
                target,
                ReadOnly=True,
                Untitled=False,
                WithWindow=False,
            )
            for number, slide in enumerate(presentation.Slides, start=1):
                collected = _SlideText(number=number)
                with contextlib.suppress(Exception):
                    if slide.Shapes.HasTitle:
                        collected.title = str(slide.Shapes.Title.TextFrame.TextRange.Text or "")
                _collect_shape_texts(slide.Shapes, collected.texts)
                _collect_notes(slide, collected.notes)
                state.slides.append(collected)
            state.properties = read_builtin_properties(presentation)
        except Exception as exc:
            state.error = exc
        finally:
            if presentation is not None:
                with contextlib.suppress(Exception):
                    presentation.Close()
            app_ref = state.app
            state.app = None
            if app_ref is not None:
                with contextlib.suppress(Exception):
                    app_ref.Quit()
            pythoncom.CoUninitialize()

    @staticmethod
    def _force_quit(state: _ComCallState) -> None:
        """Proba zamkniecia PowerPointa po przekroczeniu limitu czasu."""
        app = state.app
        if app is None:
            return
        with contextlib.suppress(Exception):
            app.Quit()


def _collect_shape_texts(shapes: Any, target: list[str]) -> None:
    """Zbiera tekst ksztaltow slajdu, wchodzac do grup i tabel."""
    for shape in shapes:
        with contextlib.suppress(Exception):
            if int(shape.Type) == _MSO_GROUP:
                _collect_shape_texts(shape.GroupItems, target)
                continue
            if bool(shape.HasTable):
                _collect_table_texts(shape.Table, target)
                continue
            if bool(shape.HasTextFrame):
                text = str(shape.TextFrame.TextRange.Text or "")
                if text.strip():
                    target.append(text)


def _collect_table_texts(table: Any, target: list[str]) -> None:
    """Zbiera komorki tabeli slajdu wiersz po wierszu."""
    with contextlib.suppress(Exception):
        for row in range(1, int(table.Rows.Count) + 1):
            cells: list[str] = []
            for column in range(1, int(table.Columns.Count) + 1):
                with contextlib.suppress(Exception):
                    value = str(table.Cell(row, column).Shape.TextFrame.TextRange.Text or "")
                    if value.strip():
                        cells.append(" ".join(value.split()))
            if cells:
                target.append(" | ".join(cells))


def _collect_notes(slide: Any, target: list[str]) -> None:
    """Zbiera notatki prelegenta z symbolu zastepczego tresci strony notatek."""
    with contextlib.suppress(Exception):
        for shape in slide.NotesPage.Shapes:
            with contextlib.suppress(Exception):
                if not bool(shape.HasTextFrame):
                    continue
                if int(shape.PlaceholderFormat.Type) != _PP_PLACEHOLDER_BODY:
                    continue
                text = str(shape.TextFrame.TextRange.Text or "")
                if text.strip():
                    target.append(text)


# --- adapter czysto pythonowy ---------------------------------------------------

_PPT_STREAM = "PowerPoint Document"
_CURRENT_USER_STREAM = "Current User"

#: Typy rekordow strumienia PowerPoint Document ([MS-PPT]).
_RT_TEXT_CHARS_ATOM = 0x0FA0
_RT_TEXT_BYTES_ATOM = 0x0FA8
_RT_DOCUMENT_ENCRYPTION_ATOM = 0x2F14

#: Kontenery pomijane w calosci: wzorce slajdow zawieraja teksty zastepcze
#: (np. "Click to edit Master title style"), ktore zasmiecalyby indeks.
_RT_MAIN_MASTER = 0x03F8

#: Wartosc recVer oznaczajaca rekord kontenerowy.
_REC_VER_CONTAINER = 0x0F

#: Znacznik zaszyfrowanego pliku w CurrentUserAtom.headerToken.
_HEADER_TOKEN_ENCRYPTED = 0xF3D1C4DF

#: Pozycja pola headerToken w strumieniu Current User (naglowek rekordu + size).
_HEADER_TOKEN_OFFSET = 12

_BINARY_ERRORS = (OSError, ValueError, struct.error)


class LegacyPptOleExtractor(Extractor):
    """Zapasowy odczyt .ppt bez Microsoft PowerPoint, wprost z kontenera OLE.

    Adapter zbiera atomy tekstowe ze strumienia PowerPoint Document. Nie zna
    przypisania tekstu do slajdow ani ukladu, ale pozwala zaindeksowac tresc
    na komputerze bez pakietu Office.
    """

    name = "ppt_ole"
    extensions = (".ppt", ".pps", ".pot")
    mime_types = ("application/vnd.ms-powerpoint",)
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
        return "Brak biblioteki olefile wymaganej do odczytu plików PowerPoint 97-2003."

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        """Odczytuje tekst i metadane pliku .ppt bez udzialu Microsoft PowerPoint."""
        context.checkpoint()
        stream, metadata = self._load_stream(path)
        warnings: list[str] = [FALLBACK_WARNING]
        text = _text_from_records(stream, context, path)
        sections, truncated = sections_from_text(text, context)
        if not sections:
            raise EmptyDocumentError(
                "Prezentacja nie zawiera tekstu możliwego do zaindeksowania.",
                details={"parser": self.name, "plik": path.name},
            )
        if truncated:
            warnings.append("Prezentacja była bardzo długa, tekst przycięto do limitu znaków.")
        if looks_like_garbage(probe_text(sections)):
            warnings.append(
                "Odczytany tekst wygląda na uszkodzony lub zapisany w nieznanym kodowaniu."
            )
        return ExtractionResult(
            sections=sections,
            metadata=metadata,
            parser_name=self.name,
            support_level=self.support_level,
            warnings=warnings,
        )

    def _load_stream(self, path: Path) -> tuple[bytes, Any]:
        """Otwiera kontener OLE i pobiera strumien dokumentu wraz z metadanymi."""
        try:
            import olefile
        except ImportError as exc:
            raise DependencyUnavailableError(
                "Brak biblioteki olefile wymaganej do odczytu plików PowerPoint 97-2003.",
                details={"parser": self.name},
                cause=exc,
            ) from exc

        try:
            is_ole = olefile.isOleFile(str(path))
        except _BINARY_ERRORS as exc:
            raise CorruptedFileError(
                "Nie udało się odczytać pliku PowerPoint 97-2003.",
                details={"plik": path.name},
                cause=exc,
            ) from exc
        if not is_ole:
            raise UnsupportedFormatError(
                "Plik nie jest prezentacją PowerPoint 97-2003, brak kontenera OLE.",
                details={"plik": path.name, "parser": self.name},
            )

        try:
            with olefile.OleFileIO(str(path)) as ole:
                if ole.exists(_CURRENT_USER_STREAM):
                    head = bytes(ole.openstream(_CURRENT_USER_STREAM).read(16))
                    if _is_encrypted_current_user(head):
                        raise PasswordProtectedError(
                            "Prezentacja jest zaszyfrowana albo zabezpieczona hasłem.",
                            details={"plik": path.name},
                        )
                if not ole.exists(_PPT_STREAM):
                    raise UnsupportedFormatError(
                        "Kontener OLE nie zawiera strumienia PowerPoint Document.",
                        details={"plik": path.name, "parser": self.name},
                    )
                stream = bytes(ole.openstream(_PPT_STREAM).read())
                metadata = metadata_from_ole(ole)
        except FindDocsError:
            raise
        except _BINARY_ERRORS as exc:
            raise CorruptedFileError(
                "Struktura pliku PowerPoint 97-2003 jest uszkodzona.",
                details={"plik": path.name},
                cause=exc,
            ) from exc
        return stream, metadata


def _is_encrypted_current_user(head: bytes) -> bool:
    """Sprawdza znacznik szyfrowania w naglowku strumienia Current User."""
    if len(head) < _HEADER_TOKEN_OFFSET + 4:
        return False
    token = int(struct.unpack_from("<I", head, _HEADER_TOKEN_OFFSET)[0])
    return token == _HEADER_TOKEN_ENCRYPTED


def _text_from_records(stream: bytes, context: ExtractionContext, path: Path) -> str:
    """Zbiera atomy tekstowe ze strumienia dokumentu w kolejnosci zapisu.

    Rekord kontenerowy (recVer 0xF) zawiera w tresci kolejne rekordy, wiec
    przejscie liniowe z wejsciem do kontenerow odwiedza wszystkie atomy.
    """
    parts: list[str] = []
    position = 0
    size = len(stream)
    steps = 0
    while position + 8 <= size:
        steps += 1
        if steps % CHECKPOINT_EVERY == 0:
            context.checkpoint()
        ver_instance, record_type, record_length = struct.unpack_from("<HHI", stream, position)
        position += 8
        record_length = min(record_length, size - position)
        if record_type == _RT_DOCUMENT_ENCRYPTION_ATOM:
            raise PasswordProtectedError(
                "Prezentacja jest zaszyfrowana albo zabezpieczona hasłem.",
                details={"plik": path.name},
            )
        if (ver_instance & 0x000F) == _REC_VER_CONTAINER:
            if record_type == _RT_MAIN_MASTER:
                position += record_length
            continue
        if record_type == _RT_TEXT_CHARS_ATOM:
            raw = stream[position : position + record_length]
            parts.append(raw.decode("utf-16-le", errors="replace"))
        elif record_type == _RT_TEXT_BYTES_ATOM:
            # Kazdy bajt to mlodszy bajt znaku UTF-16, wiec dekodowanie
            # latin-1 odtwarza znaki wprost.
            raw = stream[position : position + record_length]
            parts.append(raw.decode("latin-1"))
        position += record_length
    return "\n".join(part.translate(_PPT_TRANSLATION) for part in parts)


__all__ = ["LegacyPptComExtractor", "LegacyPptOleExtractor"]
