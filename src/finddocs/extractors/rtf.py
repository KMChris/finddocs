r"""Parser dokumentow RTF (Rich Text Format) bez zewnetrznych zaleznosci.

Modul zawiera kompletny dekoder RTF: tokenizer skladni grup ``{ }``, obsluge polecen
sterujacych ``\word<liczba>``, symboli sterujacych (``\\``, ``\{``, ``\*``), bajtow
``\'hh`` w biezacej stronie kodowej oraz znakow ``\uN`` w Unicode.

Grupy destrukcyjne (tablice fontow i kolorow, arkusze stylow, obrazy, obiekty OLE,
dane pomocnicze Worda) sa pomijane, a z grupy ``\info`` wyciagane sa metadane
dokumentu. Strona kodowa jest ustalana na podstawie ``\ansicpg`` oraz deklaracji
``\fcharset`` z tablicy fontow, dzieki czemu polskie dokumenty z Worda zapisane
w cp1250 dekoduja sie poprawnie.
"""

from __future__ import annotations

import codecs
import datetime as _dt
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Final, NamedTuple, NoReturn

from finddocs.errors import (
    CorruptedFileError,
    EmptyDocumentError,
    ExtractionError,
    FindDocsError,
    UnsupportedFormatError,
)
from finddocs.extractors.base import ExtractionContext, Extractor
from finddocs.normalization.text import clean_text, looks_like_garbage
from finddocs.types import (
    DocumentMetadata,
    ExtractedSection,
    ExtractionResult,
    SupportLevel,
    TextOrigin,
)

# --- stale skladni -------------------------------------------------------------

_RTF_SIGNATURE: Final = b"{\\rtf"
_BACKSLASH: Final = 0x5C
_BRACE_OPEN: Final = 0x7B
_BRACE_CLOSE: Final = 0x7D
_APOSTROPHE: Final = 0x27
_SPACE: Final = 0x20
_MINUS: Final = 0x2D
_CR: Final = 0x0D
_LF: Final = 0x0A

#: Bajty konczace ciagly fragment tekstu.
_TEXT_STOP: Final = b"\\{}\r\n\x00"
_HEX_DIGITS: Final = frozenset(b"0123456789abcdefABCDEF")

#: Maksymalna liczba cyfr parametru polecenia sterujacego.
_MAX_PARAM_DIGITS: Final = 12

#: Limit zagniezdzenia grup, chroni przed plikami zlosliwie zagniezdzonymi.
_MAX_GROUP_DEPTH: Final = 512

#: Co ile tokenow sprawdzac anulowanie i limit czasu.
_CHECKPOINT_TOKENS: Final = 2000

#: Co ile akapitow sprawdzac anulowanie przy budowaniu sekcji.
_CHECKPOINT_PARAGRAPHS: Final = 16

_DEFAULT_CODEPAGE: Final = 1252
_DEFAULT_MAX_CHARS: Final = 60_000_000
_MAX_META_CHARS: Final = 500

_PARAGRAPH_SPLIT: Final = re.compile(r"\n[ \t]*\n+")
_MULTI_NEWLINE: Final = re.compile(r"\n{3,}")

# --- mapy formatu --------------------------------------------------------------

#: Destynacje, ktorych zawartosc nie jest trescia dokumentu.
_SKIPPED_DESTINATIONS: Final[frozenset[str]] = frozenset(
    {
        "fonttbl",
        "colortbl",
        "stylesheet",
        "info",
        "pict",
        "object",
        "themedata",
        "datastore",
        "generator",
        "listtable",
        "listoverridetable",
        "rsidtbl",
        "latentstyles",
        "xmlnstbl",
        "nonshppict",
        "mmathPr",
        "mmathpr",
        "oleclsid",
        "filetbl",
        "revtbl",
        "pgptbl",
        "protusertbl",
        "colorschememapping",
        "objdata",
        "fldinst",
        "bkmkstart",
        "bkmkend",
    }
)

#: Polecenia deklarujace zestaw znakow calego dokumentu.
_CODEPAGE_WORDS: Final[dict[str, int]] = {
    "ansi": 1252,
    "mac": 10000,
    "pc": 437,
    "pca": 850,
}

#: Mapowanie ``\fcharsetN`` na numer strony kodowej.
_CHARSET_CODEPAGES: Final[dict[int, int]] = {
    0: 1252,
    2: 1252,
    77: 10000,
    78: 10001,
    79: 10003,
    80: 10008,
    81: 10002,
    83: 10005,
    84: 10004,
    85: 10006,
    86: 10081,
    87: 10021,
    88: 10029,
    89: 10007,
    128: 932,
    129: 949,
    130: 1361,
    134: 936,
    136: 950,
    161: 1253,
    162: 1254,
    163: 1258,
    177: 1255,
    178: 1256,
    186: 1257,
    204: 1251,
    222: 874,
    238: 1250,
    254: 437,
    255: 850,
}

#: Strony kodowe bez nazwy postaci ``cpNNNN`` w bibliotece standardowej.
_CODEPAGE_ALIASES: Final[dict[int, str]] = {
    42: "cp1252",
    10000: "mac_roman",
    10001: "shift_jis",
    10002: "big5",
    10003: "euc_kr",
    10004: "cp1256",
    10005: "cp1255",
    10006: "mac_greek",
    10007: "mac_cyrillic",
    10008: "gb2312",
    10021: "cp874",
    10029: "mac_latin2",
    10081: "mac_turkish",
    65001: "utf-8",
}

#: Polecenia konczace linie tekstu.
_BREAK_WORDS: Final[frozenset[str]] = frozenset(
    {"par", "line", "sect", "page", "column", "softline", "softpage", "lbr", "row", "nestrow"}
)

#: Polecenia zamieniane na konkretny znak.
_SPECIAL_WORDS: Final[dict[str, str]] = {
    "tab": "\t",
    "cell": " | ",
    "nestcell": " | ",
    "emdash": "\u2014",
    "endash": "\u2013",
    "emspace": "\u2003",
    "enspace": "\u2002",
    "qmspace": "\u2005",
    "bullet": "\u2022",
    "lquote": "\u2018",
    "rquote": "\u2019",
    "ldblquote": "\u201c",
    "rdblquote": "\u201d",
    "zwbo": "",
    "zwj": "",
    "zwnj": "",
    "ltrmark": "",
    "rtlmark": "",
    "chdate": "",
    "chtime": "",
    "chpgn": "",
    "chftn": "",
}

#: Symbole sterujace zamieniane na znak.
_SPECIAL_SYMBOLS: Final[dict[str, str]] = {
    "\\": "\\",
    "{": "{",
    "}": "}",
    "~": "\u00a0",
    "_": "\u2011",
    "-": "",
    ":": "",
    "|": "",
}

#: Pola grupy ``\info`` przepisywane do metadanych.
_INFO_CAPTURE: Final[dict[str, str]] = {
    "title": "title",
    "author": "author",
    "subject": "subject",
    "keywords": "keywords",
    "company": "company",
    "operator": "operator",
}

#: Grupy z data w grupie ``\info``.
_INFO_DATES: Final[dict[str, str]] = {"creatim": "created_at", "revtim": "modified_at"}

#: Skladowe daty w grupach ``\creatim`` i ``\revtim``.
_DATE_PARTS: Final[frozenset[str]] = frozenset({"yr", "mo", "dy", "hr", "min", "sec"})


# --- tokenizer -----------------------------------------------------------------


class _Token(NamedTuple):
    """Pojedynczy element skladni RTF."""

    kind: str
    """open, close, word, symbol, hex albo text."""

    word: str = ""
    param: int | None = None
    data: bytes = b""


def _is_alpha(value: int) -> bool:
    return 0x41 <= value <= 0x5A or 0x61 <= value <= 0x7A


def _is_digit(value: int) -> bool:
    return 0x30 <= value <= 0x39


def _read_param(data: bytes, index: int) -> tuple[int | None, int]:
    """Odczytuje opcjonalny, ewentualnie ujemny parametr liczbowy polecenia."""
    size = len(data)
    negative = False
    if index < size and data[index] == _MINUS and index + 1 < size and _is_digit(data[index + 1]):
        negative = True
        index += 1
    if index >= size or not _is_digit(data[index]):
        return None, index
    start = index
    while index < size and _is_digit(data[index]):
        index += 1
    value = int(data[start : min(index, start + _MAX_PARAM_DIGITS)])
    return (-value if negative else value), index


def _hex_value(pair: bytes) -> int | None:
    if len(pair) != 2 or pair[0] not in _HEX_DIGITS or pair[1] not in _HEX_DIGITS:
        return None
    return int(pair, 16)


def _tokenize(data: bytes) -> Iterator[_Token]:
    """Dzieli strumien bajtow RTF na tokeny skladniowe.

    Dane binarne po ``\\binN`` sa pomijane w calosci, zeby nie trafily do parsera
    jako pozorna skladnia.
    """
    index = 0
    size = len(data)
    while index < size:
        current = data[index]
        if current == _BACKSLASH:
            index += 1
            if index >= size:
                break
            following = data[index]
            if _is_alpha(following):
                start = index
                while index < size and _is_alpha(data[index]):
                    index += 1
                word = data[start:index].decode("ascii")
                param, index = _read_param(data, index)
                if index < size and data[index] == _SPACE:
                    index += 1
                if word == "bin":
                    if param is not None and param > 0:
                        index = min(size, index + param)
                    continue
                yield _Token("word", word, param)
            elif following == _APOSTROPHE:
                value = _hex_value(data[index + 1 : index + 3])
                if value is None:
                    index += 1
                    continue
                yield _Token("hex", param=value)
                index += 3
            elif following in (_CR, _LF):
                index += 1
                yield _Token("word", "par")
            else:
                index += 1
                yield _Token("symbol", chr(following))
        elif current == _BRACE_OPEN:
            index += 1
            yield _Token("open")
        elif current == _BRACE_CLOSE:
            index += 1
            yield _Token("close")
        elif current in (_CR, _LF, 0x00):
            index += 1
        else:
            start = index
            while index < size and data[index] not in _TEXT_STOP:
                index += 1
            yield _Token("text", data=data[start:index])


@lru_cache(maxsize=64)
def _codec_for(codepage: int) -> str:
    """Zwraca nazwe kodeka Pythona dla numeru strony kodowej RTF."""
    alias = _CODEPAGE_ALIASES.get(codepage)
    if alias is not None:
        return alias
    candidate = f"cp{codepage}"
    try:
        codecs.lookup(candidate)
    except LookupError:
        return "cp1252"
    return candidate


# --- stan parsera ---------------------------------------------------------------


@dataclass(slots=True)
class _Group:
    """Stan jednej grupy RTF. Grupa potomna dziedziczy stan rodzica."""

    codepage: int
    uc: int = 1
    ignore: bool = False
    """Zawartość grupy nie jest treścią dokumentu."""

    capture: str | None = None
    """Klucz metadanej, do której trafia tekst grupy."""

    in_info: bool = False
    in_fonttbl: bool = False
    date_key: str | None = None

    def child(self) -> _Group:
        return _Group(
            codepage=self.codepage,
            uc=self.uc,
            ignore=self.ignore,
            capture=self.capture,
            in_info=self.in_info,
            in_fonttbl=self.in_fonttbl,
        )


@dataclass(slots=True)
class RtfDocument:
    """Wynik dekodowania dokumentu RTF."""

    text: str
    metadata: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    picture_count: int = 0
    structure_broken: bool = False
    truncated: bool = False


class _RtfParser:
    """Maszyna stanu skladajaca tekst dokumentu z tokenow RTF."""

    def __init__(self, *, max_chars: int = _DEFAULT_MAX_CHARS) -> None:
        self._max_chars = max(0, max_chars)
        self._group = _Group(codepage=_DEFAULT_CODEPAGE)
        self._stack: list[_Group] = []
        self._depth_overflow = 0
        self._out: list[str] = []
        self._captures: dict[str, list[str]] = {}
        self._meta: dict[str, str] = {}
        self._buffer = bytearray()
        self._font_codepages: dict[int, int] = {}
        self._font_being_defined: int | None = None
        self._date_parts: dict[str, int] = {}
        self._skip = 0
        self._high_surrogate: int | None = None
        self._chars = 0
        self._truncated = False
        self._pictures = 0
        self._unbalanced = 0

    # -- petla glowna ------------------------------------------------------------

    def feed(self, payload: bytes, checkpoint: Callable[[], None] | None = None) -> None:
        """Przetwarza caly dokument, wolajac ``checkpoint`` co kilka tysiecy tokenow."""
        for position, token in enumerate(_tokenize(payload)):
            if checkpoint is not None and position % _CHECKPOINT_TOKENS == 0:
                checkpoint()
            kind = token.kind
            if kind == "text":
                self._handle_text(token.data)
            elif kind == "word":
                self._handle_word(token.word, token.param)
            elif kind == "hex":
                self._handle_hex(token.param or 0)
            elif kind == "open":
                self._open_group()
            elif kind == "close":
                self._close_group()
            else:
                self._handle_symbol(token.word)

    def finish(self) -> RtfDocument:
        """Domyka bufory i zwraca gotowy dokument."""
        self._flush()
        self._finalize_captures()
        warnings: list[str] = []
        if self._stack or self._depth_overflow:
            warnings.append(
                "Plik RTF kończy się przed zamknięciem wszystkich grup, tekst może być niepełny."
            )
        if self._unbalanced:
            warnings.append("Struktura grup w pliku RTF jest niespójna, tekst może być niepełny.")
        if self._truncated:
            warnings.append(f"Tekst dokumentu został skrócony do {self._max_chars} znaków.")
        return RtfDocument(
            text=_tidy("".join(self._out)),
            metadata=dict(self._meta),
            warnings=warnings,
            picture_count=self._pictures,
            structure_broken=bool(self._stack or self._unbalanced or self._depth_overflow),
            truncated=self._truncated,
        )

    # -- wyjscie tekstu ----------------------------------------------------------

    def _target(self) -> list[str] | None:
        if self._group.ignore:
            return None
        if self._group.capture is not None:
            return self._captures.setdefault(self._group.capture, [])
        return self._out

    def _append(self, text: str) -> None:
        target = self._target()
        if target is None or not text:
            return
        if target is self._out:
            remaining = self._max_chars - self._chars
            if remaining <= 0:
                self._truncated = True
                return
            if len(text) > remaining:
                text = text[:remaining]
                self._truncated = True
            self._chars += len(text)
        target.append(text)

    def _flush(self) -> None:
        """Dekoduje zebrane bajty w calosci, zeby zlozyc znaki wielobajtowe."""
        if not self._buffer:
            return
        raw = bytes(self._buffer)
        self._buffer.clear()
        if self._target() is None:
            return
        self._append(raw.decode(_codec_for(self._group.codepage), errors="replace"))

    def _emit(self, text: str) -> None:
        self._flush()
        if text:
            self._append(text)

    # -- obsluga tokenow ---------------------------------------------------------

    def _handle_text(self, raw: bytes) -> None:
        if self._skip > 0:
            consumed = min(self._skip, len(raw))
            self._skip -= consumed
            raw = raw[consumed:]
            if not raw:
                return
        if self._group.ignore:
            return
        self._buffer.extend(raw)

    def _handle_hex(self, value: int) -> None:
        if self._skip > 0:
            self._skip -= 1
            return
        if self._group.ignore:
            return
        self._buffer.append(value)

    def _handle_symbol(self, symbol: str) -> None:
        if symbol == "*":
            # Poczatek destynacji, ktorej odbiorca nie musi rozumiec: pomijamy ja.
            self._group.ignore = True
            return
        replacement = _SPECIAL_SYMBOLS.get(symbol)
        if replacement is None:
            return
        if self._skip > 0:
            self._skip -= 1
            return
        self._emit(replacement)

    def _handle_word(self, word: str, param: int | None) -> None:
        self._flush()
        self._skip = 0
        if self._group.in_fonttbl:
            self._handle_font_definition(word, param)
            return
        if word in _SKIPPED_DESTINATIONS:
            self._enter_skipped(word)
            return
        if self._group.in_info and self._handle_info(word, param):
            return
        if self._group.ignore:
            return
        if word == "u":
            self._emit_unicode(param)
            return
        if word == "uc":
            self._group.uc = max(0, param if param is not None else 1)
            return
        if word == "ansicpg" and param is not None and param > 0:
            self._group.codepage = param
            return
        if word in _CODEPAGE_WORDS:
            self._group.codepage = _CODEPAGE_WORDS[word]
            return
        if word == "f":
            if param is not None:
                codepage = self._font_codepages.get(param)
                if codepage is not None:
                    self._group.codepage = codepage
            return
        if word in _BREAK_WORDS:
            self._emit("\n")
            return
        replacement = _SPECIAL_WORDS.get(word)
        if replacement is not None:
            self._emit(replacement)

    def _emit_unicode(self, param: int | None) -> None:
        """Obsluguje ``\\uN`` wraz z para zastepcza UTF-16 i pominieciem ``\\ucN`` znaków."""
        code = param if param is not None else 0
        if code < 0:
            code += 0x10000
        self._skip = self._group.uc
        if not 0 <= code <= 0x10FFFF:
            self._high_surrogate = None
            return
        if 0xD800 <= code <= 0xDBFF:
            self._high_surrogate = code
            return
        if 0xDC00 <= code <= 0xDFFF:
            high = self._high_surrogate
            self._high_surrogate = None
            if high is None:
                return
            code = 0x10000 + ((high - 0xD800) << 10) + (code - 0xDC00)
        else:
            self._high_surrogate = None
        self._emit(chr(code))

    def _enter_skipped(self, word: str) -> None:
        already_skipped = self._group.ignore
        self._group.ignore = True
        if word == "fonttbl":
            self._group.in_fonttbl = True
            self._font_being_defined = None
        elif word == "info":
            self._group.in_info = True
        elif word == "pict" and not already_skipped:
            # Word zapisuje ten sam obraz dwa razy, w \shppict i \nonshppict.
            # Liczymy tylko obraz w grupie, ktora nie byla juz pomijana.
            self._pictures += 1

    def _handle_font_definition(self, word: str, param: int | None) -> None:
        """Zapamietuje strone kodowa fontu z tablicy ``\\fonttbl``."""
        if param is None:
            return
        if word == "f":
            self._font_being_defined = param
            return
        if word not in ("fcharset", "cpg") or self._font_being_defined is None:
            return
        codepage = param if word == "cpg" else _CHARSET_CODEPAGES.get(param)
        if codepage:
            self._font_codepages[self._font_being_defined] = codepage

    def _handle_info(self, word: str, param: int | None) -> bool:
        """Obsluguje wnetrze grupy ``\\info``. Zwraca True, gdy polecenie zostalo obsluzone."""
        capture = _INFO_CAPTURE.get(word)
        if capture is not None:
            self._group.capture = capture
            self._group.ignore = False
            return True
        date_key = _INFO_DATES.get(word)
        if date_key is not None:
            self._group.date_key = date_key
            self._date_parts = {}
            return True
        if self._group.date_key is not None and word in _DATE_PARTS:
            if param is not None:
                self._date_parts[word] = param
            return True
        if word == "nofpages" and param is not None and param > 0:
            self._meta["page_count"] = str(param)
            return True
        return False

    # -- grupy -------------------------------------------------------------------

    def _open_group(self) -> None:
        self._flush()
        self._skip = 0
        if len(self._stack) >= _MAX_GROUP_DEPTH:
            self._depth_overflow += 1
            return
        self._stack.append(self._group)
        self._group = self._group.child()

    def _close_group(self) -> None:
        self._flush()
        self._skip = 0
        if self._depth_overflow > 0:
            self._depth_overflow -= 1
            return
        if self._group.date_key is not None:
            self._store_date(self._group.date_key)
        if not self._stack:
            self._unbalanced += 1
            return
        self._group = self._stack.pop()

    # -- metadane ----------------------------------------------------------------

    def _store_date(self, key: str) -> None:
        parts = self._date_parts
        self._date_parts = {}
        year = parts.get("yr", 0)
        if not 1601 <= year <= 9999:
            return
        try:
            stamp = _dt.datetime(
                year,
                parts.get("mo") or 1,
                parts.get("dy") or 1,
                parts.get("hr", 0),
                parts.get("min", 0),
                parts.get("sec", 0),
            )
        except ValueError:
            return
        self._meta[key] = stamp.isoformat()

    def _finalize_captures(self) -> None:
        for key, parts in self._captures.items():
            value = clean_text("".join(parts)).strip(" ;")
            if value:
                self._meta[key] = value[:_MAX_META_CHARS]


# --- funkcje modulu -------------------------------------------------------------


def _tidy(text: str) -> str:
    """Porzadkuje biale znaki, zachowujac tabulatory i podzial na akapity."""
    if not text:
        return ""
    lines = [line.rstrip(" \t\u00a0") for line in text.replace("\r", "\n").split("\n")]
    return _MULTI_NEWLINE.sub("\n\n", "\n".join(lines)).strip()


def _strip_prologue(data: bytes) -> bytes:
    """Usuwa znacznik BOM i biale znaki poprzedzajace naglowek RTF."""
    payload = data.lstrip(b"\x00\t\r\n ")
    if payload.startswith(codecs.BOM_UTF8):
        payload = payload[len(codecs.BOM_UTF8) :].lstrip(b"\x00\t\r\n ")
    return payload


def parse_rtf(
    data: bytes,
    *,
    max_chars: int = _DEFAULT_MAX_CHARS,
    checkpoint: Callable[[], None] | None = None,
) -> RtfDocument:
    """Dekoduje dokument RTF do czystego tekstu, metadanych i ostrzezen.

    Rzuca ``UnsupportedFormatError``, gdy dane nie zaczynaja sie od sygnatury RTF.
    """
    payload = _strip_prologue(data)
    if not payload.startswith(_RTF_SIGNATURE):
        raise UnsupportedFormatError(
            "Plik nie jest dokumentem RTF: brak naglowka '{\\rtf' na poczatku danych.",
            details={"prefiks": payload[:16].decode("ascii", "replace")},
        )
    parser = _RtfParser(max_chars=max_chars)
    parser.feed(payload, checkpoint)
    return parser.finish()


def rtf_to_text(data: bytes) -> tuple[str, dict[str, str]]:
    """Zwraca czysty tekst dokumentu RTF oraz slownik metadanych.

    Klucze metadanych: title, author, subject, keywords, company, operator,
    created_at, modified_at, page_count. Brakujace pola sa pomijane.
    """
    document = parse_rtf(data)
    return document.text, document.metadata


def _parse_stamp(value: str | None) -> _dt.datetime | None:
    if not value:
        return None
    try:
        return _dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def _build_metadata(raw: dict[str, str]) -> DocumentMetadata:
    """Przepisuje surowe metadane RTF na strukture aplikacji."""
    metadata = DocumentMetadata(
        title=raw.get("title"),
        author=raw.get("author"),
        subject=raw.get("subject"),
        keywords=raw.get("keywords"),
        created_at=_parse_stamp(raw.get("created_at")),
        modified_at=_parse_stamp(raw.get("modified_at")),
    )
    pages = raw.get("page_count", "")
    if pages.isdigit():
        metadata.page_count = int(pages)
    for key, label in (("company", "firma"), ("operator", "operator")):
        value = raw.get(key)
        if value:
            metadata.extra[label] = value
    return metadata


def _split_sections(text: str, context: ExtractionContext) -> list[ExtractedSection]:
    """Dzieli tekst na akapity rozdzielone pusta linia."""
    sections: list[ExtractedSection] = []
    for index, block in enumerate(_PARAGRAPH_SPLIT.split(text)):
        if index % _CHECKPOINT_PARAGRAPHS == 0:
            context.checkpoint()
        cleaned = clean_text(block)
        if not cleaned:
            continue
        sections.append(
            ExtractedSection(
                text=cleaned,
                kind="text",
                order=len(sections),
                origin=TextOrigin.NATIVE,
            )
        )
    return sections


def _read_file(path: Path, context: ExtractionContext) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ExtractionError(f"Nie udało się odczytać pliku {path.name}.", cause=exc) from exc
    if size == 0:
        raise EmptyDocumentError(f"Plik {path.name} jest pusty.")
    if size > context.max_bytes:
        raise ExtractionError(
            f"Plik RTF ma {size} bajtów i przekracza limit {context.max_bytes} bajtów.",
            details={"rozmiar": size, "limit": context.max_bytes},
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise CorruptedFileError(
            f"Nie udało się wczytać zawartości pliku {path.name}.", cause=exc
        ) from exc


def _raise_empty(document: RtfDocument) -> NoReturn:
    if document.structure_broken:
        raise CorruptedFileError(
            "Struktura pliku RTF jest uszkodzona i nie zawiera czytelnego tekstu."
        )
    if document.picture_count:
        raise EmptyDocumentError(
            "Dokument RTF zawiera wyłącznie obrazy, brak warstwy tekstowej.",
            details={"obrazy": document.picture_count},
        )
    raise EmptyDocumentError("Dokument RTF nie zawiera tekstu możliwego do zaindeksowania.")


class RtfExtractor(Extractor):
    """Adapter formatu RTF oparty o wlasny dekoder, bez zewnetrznych bibliotek."""

    name = "rtf"
    extensions = (".rtf",)
    mime_types = ("application/rtf", "text/rtf")
    support_level = SupportLevel.GOOD
    priority = 100

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        context.checkpoint()
        data = _read_file(path, context)
        try:
            document = parse_rtf(data, max_chars=context.max_chars, checkpoint=context.checkpoint)
        except FindDocsError:
            raise
        except Exception as exc:
            raise CorruptedFileError(
                "Nie udało się przetworzyć struktury pliku RTF.", cause=exc
            ) from exc

        result = ExtractionResult(
            parser_name=self.name,
            support_level=self.support_level,
            origin=TextOrigin.NATIVE,
        )
        result.metadata = _build_metadata(document.metadata)
        result.warnings.extend(document.warnings)
        result.sections = _split_sections(document.text, context)
        if not result.sections:
            _raise_empty(document)

        if document.picture_count:
            result.warnings.append(
                f"Pominięto obrazy osadzone w dokumencie ({document.picture_count}). "
                "Tekst widoczny na obrazach nie zostal zaindeksowany."
            )
        if looks_like_garbage(document.text):
            result.warnings.append(
                "Odczytany tekst wygląda na uszkodzony albo zapisany w nieznanej stronie kodowej."
            )
        # RTF nie jest formatem stronicowanym i nie da sie go tutaj zrasteryzowac,
        # dlatego needs_ocr pozostaje False nawet przy dokumentach z obrazami.
        return result


__all__ = ["RtfDocument", "RtfExtractor", "parse_rtf", "rtf_to_text"]
