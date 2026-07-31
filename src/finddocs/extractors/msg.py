"""Parser wiadomosci Microsoft Outlook w formacie MSG.

Format MSG to kontener OLE (CFBF), w ktorym wlasciwosci MAPI sa rozrzucone po
strumieniach ``__substg1.0_<PPPPTTTT>`` (PPPP to identyfikator wlasciwosci, TTTT
typ) oraz po strumieniu ``__properties_version1.0`` z wartosciami stalej dlugosci.
Zalaczniki siedza w podkatalogach ``__attach_version1.0_#XXXXXXXX``.

Modul czyta ten format bezposrednio na bazie ``olefile`` (licencja BSD). Swiadomie
nie korzystamy z biblioteki ``extract-msg``, bo jej licencja GPL-3.0 nie jest
akceptowalna w tym projekcie.

Kolejnosc szukania tresci: PR_BODY (0x1000), potem PR_HTML (0x1013), na koncu
PR_RTF_COMPRESSED (0x1009) rozpakowany algorytmem LZFu z MS-OXRTFCP. Publiczna
funkcja ``decompress_rtf`` udostepnia sama dekompresje.
"""

from __future__ import annotations

import codecs
import datetime as _dt
import re
import struct
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from email.parser import HeaderParser
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

import olefile

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
    ExtractedAttachment,
    ExtractedSection,
    ExtractionResult,
    SupportLevel,
    TextOrigin,
)

#: Sciezka wewnatrz kontenera OLE jako krotka nazw katalogow i strumienia.
OlePath = tuple[str, ...]

# --- stale formatu MSG ---------------------------------------------------------

_SUBSTG_PREFIX = "__substg1.0_"
_PROPERTIES_STREAM = "__properties_version1.0"
_ATTACH_PREFIX = "__attach_version1.0_#"

# Typy wlasciwosci MAPI.
_PT_LONG = 0x0003
_PT_BOOLEAN = 0x000B
_PT_OBJECT = 0x000D
_PT_STRING8 = 0x001E
_PT_UNICODE = 0x001F
_PT_SYSTIME = 0x0040
_PT_BINARY = 0x0102

#: Kolejnosc prob przy odczycie wlasciwosci tekstowej.
_STRING_TYPES: tuple[int, ...] = (_PT_UNICODE, _PT_STRING8)

#: Typy uznawane za poprawne przy dobieraniu rozmiaru naglowka __properties.
_KNOWN_TYPES: frozenset[int] = frozenset(
    {
        0x0002,
        0x0003,
        0x0004,
        0x0005,
        0x0006,
        0x0007,
        0x000A,
        0x000B,
        0x0014,
        0x001E,
        0x001F,
        0x0040,
        0x0048,
        0x00FD,
        0x00FE,
        0x0102,
        0x1002,
        0x1003,
        0x1004,
        0x1005,
        0x1006,
        0x1007,
        0x100A,
        0x100B,
        0x1014,
        0x101E,
        0x101F,
        0x1040,
        0x1048,
        0x1102,
    }
)

# Identyfikatory wlasciwosci wiadomosci.
_PID_MESSAGE_CLASS = 0x001A
_PID_SUBJECT = 0x0037
_PID_CLIENT_SUBMIT_TIME = 0x0039
_PID_SENT_REPRESENTING_EMAIL = 0x0065
_PID_SENDER_NAME = 0x0C1A
_PID_SENDER_EMAIL = 0x0C1F
_PID_DISPLAY_BCC = 0x0E02
_PID_DISPLAY_CC = 0x0E03
_PID_DISPLAY_TO = 0x0E04
_PID_DELIVERY_TIME = 0x0E06
_PID_NORMALIZED_SUBJECT = 0x0E1D
_PID_TRANSPORT_HEADERS = 0x007D
_PID_BODY = 0x1000
_PID_RTF_COMPRESSED = 0x1009
_PID_BODY_HTML = 0x1013
_PID_CREATION_TIME = 0x3007
_PID_LAST_MODIFICATION_TIME = 0x3008
_PID_INTERNET_CPID = 0x3FDE
_PID_MESSAGE_CODEPAGE = 0x3FFD
_PID_CODE_PAGE_ID = 0x66C3
_PID_SENDER_SMTP = 0x5D01
_PID_SENT_REPRESENTING_SMTP = 0x5D02

# Identyfikatory wlasciwosci zalacznika.
_PID_ATTACH_DATA = 0x3701
_PID_ATTACH_FILENAME = 0x3704
_PID_ATTACH_EXTENSION = 0x3703
_PID_ATTACH_LONG_FILENAME = 0x3707
_PID_ATTACH_MIME_TAG = 0x370E
_PID_ATTACH_FLAGS = 0x3714
_PID_ATTACH_METHOD = 0x3705

#: Rozmiary naglowka strumienia __properties_version1.0 wedlug MS-OXMSG.
#: Pierwsza wartosc jest najbardziej prawdopodobna, reszta sluzy jako zapas,
#: bo czesc generatorow MSG zapisuje naglowek niezgodnie ze specyfikacja.
_TOP_LEVEL_HEADERS: tuple[int, ...] = (32, 24, 8)
_ATTACH_HEADERS: tuple[int, ...] = (8, 24, 32)
_EMBEDDED_HEADERS: tuple[int, ...] = (24, 8, 32)

#: Poczatek epoki FILETIME.
_FILETIME_EPOCH = _dt.datetime(1601, 1, 1, tzinfo=_dt.UTC)
_MIN_SANE_YEAR = 1800
_MAX_SANE_YEAR = 2200

#: Ponizej tej dlugosci nie oceniamy tresci heurystyka wykrywania smieci,
#: bo krotkie wiadomosci potrafia skladac sie prawie wylacznie z interpunkcji.
_GARBAGE_MIN_CHARS = 200

_CHARSET_RE = re.compile(rb"""charset\s*=\s*["']?([A-Za-z0-9_.:\-]+)""", re.IGNORECASE)

# --- dekompresja RTF (MS-OXRTFCP) ----------------------------------------------

_RTF_DICTIONARY_SIZE = 4096

#: Slownik startowy algorytmu LZFu, dokladnie 207 bajtow (MS-OXRTFCP 3.1.1.1).
_RTF_INIT_DICTIONARY = (
    b"{\\rtf1\\ansi\\mac\\deff0\\deftab720{\\fonttbl;}{\\f0\\fnil \\froman \\fswiss "
    b"\\fmodern \\fscript \\fdecor MS Sans SerifSymbolArialTimes New RomanCourier"
    b"{\\colortbl\\red0\\green0\\blue0\r\n\\par \\pard\\plain\\f0\\fs20\\b\\i\\u\\tab\\tx"
)

#: Znaczniki COMPTYPE zapisane jako liczby little-endian: "LZFu" oraz "MELA".
_RTF_COMPRESSED_MAGIC = 0x75465A4C
_RTF_UNCOMPRESSED_MAGIC = 0x414C454D

#: Zabezpieczenie przed bomba dekompresyjna, gdy naglowek nie podaje rozmiaru.
_RTF_MAX_OUTPUT = 64 * 1024 * 1024


def decompress_rtf(data: bytes) -> bytes:
    """Rozpakowuje strumien PR_RTF_COMPRESSED zgodnie z MS-OXRTFCP.

    Obsluguje oba warianty naglowka: "MELA" (tekst zapisany wprost) oraz "LZFu"
    (kompresja slownikowa z 4096-bajtowym slownikiem). Gdy dane zaczynaja sie od
    ``{\\rtf``, zwraca je bez zmian.
    """
    if data[:5] == b"{\\rtf":
        return data
    if len(data) < 16:
        raise CorruptedFileError(
            "Strumien RTF wiadomosci jest zbyt krotki, brakuje naglowka kompresji.",
            details={"dlugosc": len(data)},
        )
    try:
        comp_size, raw_size, comp_type, _crc = struct.unpack("<4I", data[:16])
    except struct.error as exc:  # pragma: no cover - dlugosc sprawdzona wyzej
        raise CorruptedFileError(
            "Naglowek skompresowanego RTF jest uszkodzony.", cause=exc
        ) from exc

    end = 4 + comp_size
    payload = data[16:end] if 16 < end <= len(data) else data[16:]
    if comp_type == _RTF_UNCOMPRESSED_MAGIC:
        return payload[:raw_size] if 0 < raw_size < len(payload) else payload
    if comp_type != _RTF_COMPRESSED_MAGIC:
        raise CorruptedFileError(
            "Nieznany typ kompresji tresci RTF w wiadomosci.",
            details={"comptype": f"0x{comp_type:08X}"},
        )
    return _lzfu_decompress(payload, raw_size)


def _lzfu_decompress(payload: bytes, raw_size: int) -> bytes:
    """Wlasciwa petla dekompresji LZFu."""
    limit = raw_size if 0 < raw_size <= _RTF_MAX_OUTPUT else _RTF_MAX_OUTPUT
    dictionary = bytearray(_RTF_DICTIONARY_SIZE)
    dictionary[: len(_RTF_INIT_DICTIONARY)] = _RTF_INIT_DICTIONARY
    write_offset = len(_RTF_INIT_DICTIONARY)
    out = bytearray()
    pos = 0
    size = len(payload)

    while pos < size and len(out) < limit:
        control = payload[pos]
        pos += 1
        for bit in range(8):
            if pos >= size or len(out) >= limit:
                break
            if not (control >> bit) & 1:
                literal = payload[pos]
                pos += 1
                out.append(literal)
                dictionary[write_offset] = literal
                write_offset = (write_offset + 1) % _RTF_DICTIONARY_SIZE
                continue
            if pos + 1 >= size:
                pos = size
                break
            token = (payload[pos] << 8) | payload[pos + 1]
            pos += 2
            dict_offset = token >> 4
            length = (token & 0x0F) + 2
            if dict_offset == write_offset:
                # Znacznik konca strumienia: referencja wskazuje pozycje zapisu.
                return bytes(out)
            for step in range(length):
                copied = dictionary[(dict_offset + step) % _RTF_DICTIONARY_SIZE]
                out.append(copied)
                dictionary[write_offset] = copied
                write_offset = (write_offset + 1) % _RTF_DICTIONARY_SIZE
    return bytes(out[:limit])


# --- pomocnicze funkcje kodowania ----------------------------------------------


def _is_known_codec(name: str) -> bool:
    try:
        codecs.lookup(name)
    except (LookupError, TypeError, ValueError):
        return False
    return True


def _codec_for_codepage(number: int) -> str | None:
    """Tlumaczy numer strony kodowej Windows na nazwe kodeka Pythona."""
    if number <= 0:
        return None
    special: dict[int, str] = {
        1200: "utf-16-le",
        1201: "utf-16-be",
        12000: "utf-32-le",
        12001: "utf-32-be",
        20127: "ascii",
        20866: "koi8-r",
        21866: "koi8-u",
        28603: "iso8859-13",
        28605: "iso8859-15",
        50220: "iso2022-jp",
        51932: "euc-jp",
        51949: "euc-kr",
        54936: "gb18030",
        65000: "utf-7",
        65001: "utf-8",
    }
    name = special.get(number)
    if name is None and 28591 <= number <= 28599:
        name = f"iso8859-{number - 28590}"
    if name is None:
        name = f"cp{number}"
    return name if _is_known_codec(name) else None


def _filetime_to_datetime(value: int) -> _dt.datetime | None:
    """Zamienia FILETIME (100 ns od 1601-01-01 UTC) na date z ustawiona strefa."""
    if value <= 0:
        return None
    try:
        moment = _FILETIME_EPOCH + _dt.timedelta(microseconds=value // 10)
    except (OverflowError, ValueError):
        return None
    if not _MIN_SANE_YEAR <= moment.year <= _MAX_SANE_YEAR:
        return None
    return moment


def _format_timestamp(value: _dt.datetime) -> str:
    """Data w postaci czytelnej i dobrze wyszukiwalnej.

    Wlasciwosci czasowe MAPI sa zapisane w UTC, wiec strefa jest podana wprost,
    zeby godzina w wynikach wyszukiwania nie byla mylaca.
    """
    if value.tzinfo is None:
        return value.strftime("%Y-%m-%d %H:%M")
    return value.astimezone(_dt.UTC).strftime("%Y-%m-%d %H:%M UTC")


def _parse_tag(name: str) -> tuple[int, int] | None:
    """Rozklada nazwe strumienia wlasciwosci na (identyfikator, typ)."""
    if not name.startswith(_SUBSTG_PREFIX):
        return None
    tag = name[len(_SUBSTG_PREFIX) :]
    if len(tag) > 8:
        # Warianty wielowartosciowe maja sufiks "-XXXXXXXX" z numerem elementu.
        tag = tag[:8]
    if len(tag) != 8:
        return None
    try:
        value = int(tag, 16)
    except ValueError:
        return None
    return (value >> 16) & 0xFFFF, value & 0xFFFF


def _parse_fixed_properties(
    data: bytes, header_sizes: tuple[int, ...]
) -> dict[int, tuple[int, bytes]]:
    """Parsuje strumien ``__properties_version1.0``.

    Rozmiar naglowka zalezy od rodzaju obiektu, a czesc generatorow MSG zapisuje
    go niezgodnie ze specyfikacja. Sprawdzamy wiec kilka wariantow i wybieramy ten,
    ktory daje najwiecej rekordow o poprawnym typie wlasciwosci.
    """
    best: dict[int, tuple[int, bytes]] = {}
    best_score = -1.0
    for header in header_sizes:
        if len(data) < header + 16:
            continue
        body = data[header:]
        count = len(body) // 16
        if count == 0:
            continue
        parsed: dict[int, tuple[int, bytes]] = {}
        known = 0
        for index in range(count):
            offset = index * 16
            tag = int.from_bytes(body[offset : offset + 4], "little")
            prop_id = (tag >> 16) & 0xFFFF
            prop_type = tag & 0xFFFF
            if prop_id != 0 and prop_type in _KNOWN_TYPES:
                known += 1
            parsed.setdefault(prop_id, (prop_type, body[offset + 8 : offset + 16]))
        score = known / count
        if len(body) % 16 == 0:
            score += 0.05
        if score > best_score:
            best_score = score
            best = parsed
    return best


def _decode_mime_words(value: str) -> str:
    """Dekoduje naglowek RFC 2047, np. ``=?utf-8?B?...?=``."""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _parse_transport_headers(raw: str) -> dict[str, str]:
    """Wyciaga wybrane naglowki RFC 822 z wlasciwosci PR_TRANSPORT_MESSAGE_HEADERS."""
    try:
        message = HeaderParser().parsestr(raw, headersonly=True)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for key in ("From", "To", "Cc", "Bcc", "Subject", "Date"):
        value = message.get(key)
        if value:
            out[key] = _decode_mime_words(str(value)).strip()
    return out


def _strip_subject_prefix(subject: str) -> str:
    """Usuwa binarny prefiks tematu zapisywany przez czesc klientow MAPI."""
    if len(subject) >= 2 and subject[0] == "\x01":
        return subject[2:]
    return subject


def _html_to_plain(html: str) -> str:
    """Konwersja HTML na tekst. Import lokalny, zeby nie ladowac parsera bez potrzeby."""
    from finddocs.extractors.html_text import html_to_text

    return html_to_text(html)


def _rtf_to_plain(rtf: bytes) -> str:
    """Konwersja RTF na tekst. Import lokalny, zeby nie ladowac parsera bez potrzeby."""
    from finddocs.extractors.rtf import rtf_to_text

    text, _metadata = rtf_to_text(rtf)
    return text


# --- odczyt kontenera OLE ------------------------------------------------------


@dataclass(slots=True)
class _ObjectEntries:
    """Wykaz strumieni, podkatalogow i wlasciwosci stalych jednego obiektu MSG."""

    prefix: OlePath
    streams: dict[tuple[int, int], OlePath] = field(default_factory=dict)
    storages: dict[tuple[int, int], OlePath] = field(default_factory=dict)
    fixed: dict[int, tuple[int, bytes]] = field(default_factory=dict)
    has_properties: bool = False


class _MsgContainer:
    """Cienka warstwa nad ``olefile`` udostepniajaca wlasciwosci MAPI."""

    def __init__(self, ole: olefile.OleFileIO) -> None:
        self._ole = ole
        self.warnings: list[str] = []
        self.encoding: str = "cp1252"
        self.html_encoding: str = "cp1252"
        try:
            streams = ole.listdir(streams=True, storages=False)
            storages = ole.listdir(streams=False, storages=True)
        except (OSError, ValueError, KeyError, IndexError, struct.error) as exc:
            raise CorruptedFileError(
                "Nie udalo sie odczytac struktury katalogow pliku MSG.", cause=exc
            ) from exc
        self._streams: list[OlePath] = [tuple(entry) for entry in streams]
        self._storages: list[OlePath] = [tuple(entry) for entry in storages]

    # --- struktura ---

    def object_at(self, prefix: OlePath, header_sizes: tuple[int, ...]) -> _ObjectEntries:
        """Zbiera wlasciwosci obiektu lezacego pod wskazanym prefiksem sciezki."""
        depth = len(prefix) + 1
        obj = _ObjectEntries(prefix=prefix)
        properties_path: OlePath | None = None
        for path in self._streams:
            if len(path) != depth or path[:-1] != prefix:
                continue
            name = path[-1]
            if name == _PROPERTIES_STREAM:
                obj.has_properties = True
                properties_path = path
                continue
            tag = _parse_tag(name)
            if tag is not None:
                obj.streams.setdefault(tag, path)
        for path in self._storages:
            if len(path) != depth or path[:-1] != prefix:
                continue
            tag = _parse_tag(path[-1])
            if tag is not None:
                obj.storages.setdefault(tag, path)
        if properties_path is not None:
            obj.fixed = _parse_fixed_properties(self.read_stream(properties_path), header_sizes)
        return obj

    def child_storages(self, prefix: OlePath, name_prefix: str) -> list[OlePath]:
        """Podkatalogi obiektu o nazwie zaczynajacej sie od ``name_prefix``."""
        depth = len(prefix) + 1
        found = [
            path
            for path in self._storages
            if len(path) == depth and path[:-1] == prefix and path[-1].startswith(name_prefix)
        ]
        return sorted(found)

    def has_msg_streams(self) -> bool:
        """Czy kontener wyglada na wiadomosc MSG, a nie na inny plik OLE."""
        for path in self._streams:
            name = path[-1]
            if name.startswith(_SUBSTG_PREFIX) or name == _PROPERTIES_STREAM:
                return True
        return any(path[-1].startswith(_ATTACH_PREFIX) for path in self._storages)

    # --- surowy odczyt ---

    def read_stream(self, path: OlePath, limit: int | None = None) -> bytes:
        """Odczyt strumienia. Blad pojedynczego strumienia nie przerywa ekstrakcji."""
        try:
            with self._ole.openstream(list(path)) as stream:
                raw = stream.read() if limit is None else stream.read(limit)
        except (OSError, ValueError, KeyError, IndexError, struct.error):
            self.warnings.append(f"Nie udalo sie odczytac strumienia wiadomosci: {'/'.join(path)}.")
            return b""
        return bytes(raw)

    def stream_size(self, path: OlePath) -> int:
        try:
            size = self._ole.get_size(list(path))
        except (OSError, ValueError, KeyError, IndexError, struct.error):
            return -1
        return int(size)

    # --- dekodowanie ---

    def resolve_encodings(self, root: _ObjectEntries) -> None:
        """Ustala strony kodowe uzywane przy dekodowaniu tekstu i HTML."""
        self.encoding = self._codepage(
            root, (_PID_MESSAGE_CODEPAGE, _PID_INTERNET_CPID, _PID_CODE_PAGE_ID)
        )
        self.html_encoding = self._codepage(
            root, (_PID_INTERNET_CPID, _PID_CODE_PAGE_ID, _PID_MESSAGE_CODEPAGE)
        )

    def _codepage(self, root: _ObjectEntries, order: tuple[int, ...]) -> str:
        for prop_id in order:
            entry = root.fixed.get(prop_id)
            if entry is None or entry[0] not in (_PT_LONG, _PT_BOOLEAN):
                continue
            codec = _codec_for_codepage(int.from_bytes(entry[1][:4], "little"))
            if codec is not None:
                return codec
        return "cp1252"

    def decode_string8(self, raw: bytes) -> str:
        """Dekoduje PT_STRING8 wedlug strony kodowej wiadomosci, z lancuchem zapasowym."""
        for encoding in dict.fromkeys([self.encoding, "cp1252", "cp1250"]):
            try:
                return raw.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode("latin-1", errors="replace")

    @staticmethod
    def decode_unicode(raw: bytes) -> str:
        usable = raw[: len(raw) - (len(raw) % 2)]
        return usable.decode("utf-16-le", errors="replace")

    def decode_html(self, raw: bytes) -> str:
        """Dekoduje tresc HTML: BOM, deklaracja charset, potem strony kodowe wiadomosci."""
        candidates: list[str] = []
        if raw.startswith(codecs.BOM_UTF8):
            candidates.append("utf-8-sig")
        match = _CHARSET_RE.search(raw[:4096])
        if match is not None:
            declared = match.group(1).decode("ascii", "ignore")
            if _is_known_codec(declared):
                candidates.append(declared)
        candidates.extend([self.html_encoding, self.encoding, "utf-8", "cp1252"])
        for encoding in dict.fromkeys(candidates):
            try:
                return raw.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode("latin-1", errors="replace")

    # --- wlasciwosci ---

    def get_string(
        self, obj: _ObjectEntries, prop_id: int, types: tuple[int, ...] = _STRING_TYPES
    ) -> str:
        for prop_type in types:
            path = obj.streams.get((prop_id, prop_type))
            if path is None:
                continue
            raw = self.read_stream(path)
            if not raw:
                continue
            text = (
                self.decode_unicode(raw) if prop_type == _PT_UNICODE else self.decode_string8(raw)
            )
            text = text.rstrip("\x00").strip()
            if text:
                return text
        return ""

    def first_string(self, obj: _ObjectEntries, prop_ids: tuple[int, ...]) -> str:
        for prop_id in prop_ids:
            value = self.get_string(obj, prop_id)
            if value:
                return value
        return ""

    def get_binary(self, obj: _ObjectEntries, prop_id: int, limit: int | None = None) -> bytes:
        path = obj.streams.get((prop_id, _PT_BINARY))
        if path is None:
            return b""
        return self.read_stream(path, limit=limit)

    def get_uint32(self, obj: _ObjectEntries, prop_id: int) -> int | None:
        entry = obj.fixed.get(prop_id)
        if entry is None or entry[0] not in (_PT_LONG, _PT_BOOLEAN):
            return None
        return int.from_bytes(entry[1][:4], "little")

    def get_time(self, obj: _ObjectEntries, prop_id: int) -> _dt.datetime | None:
        entry = obj.fixed.get(prop_id)
        if entry is not None and entry[0] == _PT_SYSTIME:
            moment = _filetime_to_datetime(int.from_bytes(entry[1], "little"))
            if moment is not None:
                return moment
        path = obj.streams.get((prop_id, _PT_SYSTIME))
        if path is not None:
            raw = self.read_stream(path, limit=8)
            if len(raw) == 8:
                return _filetime_to_datetime(int.from_bytes(raw, "little"))
        return None

    def first_time(self, obj: _ObjectEntries, prop_ids: tuple[int, ...]) -> _dt.datetime | None:
        for prop_id in prop_ids:
            moment = self.get_time(obj, prop_id)
            if moment is not None:
                return moment
        return None


# --- parser --------------------------------------------------------------------


@dataclass(slots=True)
class _Envelope:
    """Naglowek wiadomosci zlozony z wlasciwosci MAPI i naglowkow transportowych."""

    sender: str = ""
    to: str = ""
    cc: str = ""
    bcc: str = ""
    subject: str = ""
    sent_at: _dt.datetime | None = None
    modified_at: _dt.datetime | None = None
    message_class: str = ""


class MsgExtractor(Extractor):
    """Adapter wiadomosci Outlook MSG oparty o wlasny czytnik kontenera OLE."""

    name = "msg"
    extensions = (".msg",)
    mime_types = ("application/vnd.ms-outlook",)
    support_level = SupportLevel.GOOD
    priority = 120

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        context.checkpoint()
        try:
            is_ole = olefile.isOleFile(str(path))
        except OSError as exc:
            raise CorruptedFileError(
                "Nie udalo sie otworzyc pliku wiadomosci MSG.",
                details={"plik": path.name},
                cause=exc,
            ) from exc
        if not is_ole:
            raise CorruptedFileError(
                "Plik nie jest kontenerem OLE, wiec nie jest poprawna wiadomoscia MSG.",
                details={"plik": path.name},
            )
        try:
            with olefile.OleFileIO(str(path)) as ole:
                return self._extract_from_ole(ole, path, context)
        except FindDocsError:
            raise
        except Exception as exc:
            raise ExtractionError(
                "Nie udalo sie odczytac wiadomosci MSG.",
                details={"plik": path.name, "blad": type(exc).__name__},
                cause=exc,
            ) from exc

    # --- czesci skladowe ---

    def _extract_from_ole(
        self, ole: olefile.OleFileIO, path: Path, context: ExtractionContext
    ) -> ExtractionResult:
        container = _MsgContainer(ole)
        if not container.has_msg_streams():
            raise UnsupportedFormatError(
                "Plik OLE nie zawiera strumieni wiadomosci MSG.",
                details={"plik": path.name},
            )
        root = container.object_at((), _TOP_LEVEL_HEADERS)
        container.resolve_encodings(root)

        warnings: list[str] = []
        envelope = self._read_envelope(container, root)
        sections: list[ExtractedSection] = []
        order = 0

        header_text = clean_text(_envelope_text(envelope))
        if header_text:
            sections.append(ExtractedSection(text=header_text, kind="email_header", order=order))
            order += 1

        context.checkpoint()
        body_text, body_source = self._read_body(container, root, warnings)
        if body_text and len(body_text) > context.max_chars:
            body_text = body_text[: context.max_chars]
            warnings.append("Tresc wiadomosci zostala przycieta do limitu znakow.")
        if body_text:
            sections.append(
                ExtractedSection(
                    text=body_text,
                    kind="text",
                    order=order,
                    extra={"zrodlo_tresci": body_source},
                )
            )
            order += 1

        attachments: list[ExtractedAttachment] = []
        attachment_storages = container.child_storages((), _ATTACH_PREFIX)
        if context.extract_attachments and attachment_storages:
            order = self._read_attachments(
                container, attachment_storages, context, sections, attachments, warnings, order
            )
        elif attachment_storages:
            warnings.append(
                "Zalaczniki wiadomosci zostaly pominiete zgodnie z konfiguracja "
                f"(liczba: {len(attachment_storages)})."
            )

        warnings.extend(container.warnings)
        if not body_text and not envelope.subject and not attachments:
            raise EmptyDocumentError(
                "Wiadomosc MSG nie zawiera tematu, tresci ani zalacznikow.",
                details={"plik": path.name},
            )

        return ExtractionResult(
            sections=sections,
            metadata=_build_metadata(envelope, len(attachment_storages)),
            attachments=attachments,
            origin=TextOrigin.NATIVE,
            total_pages=0,
            parser_name=self.name,
            support_level=self.support_level,
            warnings=warnings,
            needs_ocr=False,
        )

    def _read_envelope(self, container: _MsgContainer, root: _ObjectEntries) -> _Envelope:
        """Sklada naglowek z wlasciwosci MAPI, uzupelniajac braki z naglowkow SMTP."""
        envelope = _Envelope()
        envelope.subject = _strip_subject_prefix(
            container.first_string(root, (_PID_SUBJECT, _PID_NORMALIZED_SUBJECT))
        ).strip()
        envelope.to = container.get_string(root, _PID_DISPLAY_TO)
        envelope.cc = container.get_string(root, _PID_DISPLAY_CC)
        envelope.bcc = container.get_string(root, _PID_DISPLAY_BCC)
        envelope.message_class = container.get_string(root, _PID_MESSAGE_CLASS)
        envelope.sent_at = container.first_time(
            root, (_PID_CLIENT_SUBMIT_TIME, _PID_DELIVERY_TIME, _PID_CREATION_TIME)
        )
        envelope.modified_at = container.get_time(root, _PID_LAST_MODIFICATION_TIME)
        sender_name = container.get_string(root, _PID_SENDER_NAME)
        sender_address = container.first_string(
            root,
            (
                _PID_SENDER_SMTP,
                _PID_SENT_REPRESENTING_SMTP,
                _PID_SENDER_EMAIL,
                _PID_SENT_REPRESENTING_EMAIL,
            ),
        )
        if not _is_usable_address(sender_address):
            # Exchange zapisuje tu nazwe X.500 (/O=.../CN=...), ktora nic nie wnosi.
            sender_address = ""

        raw_headers = container.get_string(root, _PID_TRANSPORT_HEADERS)
        if not raw_headers:
            envelope.sender = _join_sender(sender_name, sender_address)
            return envelope
        headers = _parse_transport_headers(raw_headers)
        if not sender_address and "From" in headers:
            header_name, header_address = parseaddr(headers["From"])
            sender_name = sender_name or header_name.strip()
            if _is_usable_address(header_address):
                sender_address = header_address
        envelope.sender = _join_sender(sender_name, sender_address) or headers.get("From", "")
        envelope.to = envelope.to or headers.get("To", "")
        envelope.cc = envelope.cc or headers.get("Cc", "")
        envelope.bcc = envelope.bcc or headers.get("Bcc", "")
        envelope.subject = envelope.subject or headers.get("Subject", "")
        if envelope.sent_at is None and "Date" in headers:
            try:
                envelope.sent_at = parsedate_to_datetime(headers["Date"])
            except (TypeError, ValueError):
                envelope.sent_at = None
        return envelope

    def _read_body(
        self, container: _MsgContainer, root: _ObjectEntries, warnings: list[str]
    ) -> tuple[str, str]:
        """Zwraca (tekst, zrodlo). Zrodlo to ``body``, ``html`` albo ``rtf``."""
        fallback: tuple[str, str] | None = None
        for source in ("body", "html", "rtf"):
            raw_text = self._body_candidate(container, root, source, warnings)
            cleaned = clean_text(raw_text)
            if not cleaned:
                continue
            if len(cleaned) >= _GARBAGE_MIN_CHARS and looks_like_garbage(cleaned):
                if fallback is None:
                    fallback = (cleaned, source)
                continue
            return cleaned, source
        if fallback is not None:
            warnings.append(
                "Tresc wiadomosci wyglada na uszkodzona lub zle zakodowana, "
                "zaindeksowano ja mimo to."
            )
            return fallback
        return "", ""

    def _body_candidate(
        self, container: _MsgContainer, root: _ObjectEntries, source: str, warnings: list[str]
    ) -> str:
        if source == "body":
            return container.get_string(root, _PID_BODY)
        if source == "html":
            raw = container.get_binary(root, _PID_BODY_HTML)
            html = container.decode_html(raw) if raw else container.get_string(root, _PID_BODY_HTML)
            if not html:
                return ""
            try:
                return _html_to_plain(html)
            except FindDocsError as exc:
                warnings.append(
                    f"Nie udalo sie odczytac tresci HTML wiadomosci: {exc.user_message}"
                )
                return ""
        raw_rtf = container.get_binary(root, _PID_RTF_COMPRESSED)
        if not raw_rtf:
            return ""
        try:
            decompressed = decompress_rtf(raw_rtf)
        except FindDocsError as exc:
            warnings.append(f"Nie udalo sie rozpakowac tresci RTF wiadomosci: {exc.user_message}")
            return ""
        if not decompressed:
            warnings.append("Skompresowana tresc RTF wiadomosci jest pusta.")
            return ""
        try:
            return _rtf_to_plain(decompressed)
        except FindDocsError as exc:
            warnings.append(f"Nie udalo sie odczytac tresci RTF wiadomosci: {exc.user_message}")
            return ""

    def _read_attachments(
        self,
        container: _MsgContainer,
        storages: list[OlePath],
        context: ExtractionContext,
        sections: list[ExtractedSection],
        attachments: list[ExtractedAttachment],
        warnings: list[str],
        order: int,
    ) -> int:
        """Czyta zalaczniki i dopisuje notatki do listy sekcji. Zwraca kolejny numer sekcji."""
        used_bytes = 0
        for index, storage in enumerate(storages, start=1):
            if index % 8 == 1:
                context.checkpoint()
            attach = container.object_at(storage, _ATTACH_HEADERS)
            name = container.first_string(attach, (_PID_ATTACH_LONG_FILENAME, _PID_ATTACH_FILENAME))
            if not name:
                extension = container.get_string(attach, _PID_ATTACH_EXTENSION)
                name = f"zalacznik_{index}{extension}"
            mime = container.get_string(attach, _PID_ATTACH_MIME_TAG) or None
            flags = container.get_uint32(attach, _PID_ATTACH_FLAGS)
            method = container.get_uint32(attach, _PID_ATTACH_METHOD)

            embedded = attach.storages.get((_PID_ATTACH_DATA, _PT_OBJECT))
            data_path = attach.streams.get((_PID_ATTACH_DATA, _PT_BINARY))
            note = ""
            if data_path is not None:
                size = container.stream_size(data_path)
                if size > context.max_bytes or used_bytes + max(size, 0) > context.max_bytes:
                    warnings.append(f"Pominieto zbyt duzy zalacznik: {name}.")
                    continue
                data = container.read_stream(data_path)
                if not data:
                    warnings.append(f"Zalacznik jest pusty lub nieczytelny: {name}.")
                    continue
                used_bytes += len(data)
                attachments.append(ExtractedAttachment(name=name, mime_type=mime, data=data))
                note = _attachment_note(name, mime, len(data))
            elif embedded is not None:
                inner = container.object_at(embedded, _EMBEDDED_HEADERS)
                inner_subject = _strip_subject_prefix(
                    container.first_string(inner, (_PID_SUBJECT, _PID_NORMALIZED_SUBJECT))
                ).strip()
                label = inner_subject or name
                note = f"Zalacznik: osadzona wiadomosc Outlook, temat: {label}"
                warnings.append(
                    "Zalacznik jest osadzona wiadomoscia Outlook, jej tresc nie zostala "
                    f"rozpakowana: {label}."
                )
            else:
                warnings.append(f"Zalacznik nie zawiera danych mozliwych do odczytu: {name}.")
                continue

            cleaned_note = clean_text(note)
            if not cleaned_note:
                continue
            sections.append(
                ExtractedSection(
                    text=cleaned_note,
                    kind="attachment_note",
                    order=order,
                    extra={
                        "nazwa": name,
                        "mime": mime,
                        "flagi": flags,
                        "metoda": method,
                        "osadzona_wiadomosc": embedded is not None,
                    },
                )
            )
            order += 1
        return order


def _is_usable_address(address: str) -> bool:
    """Czy adres nadaje sie do pokazania: adres SMTP, a nie nazwa X.500 z Exchange."""
    value = address.strip()
    return bool(value) and "@" in value and not value.startswith("/")


def _join_sender(display_name: str, address: str) -> str:
    """Laczy nazwe nadawcy z adresem, pomijajac duplikaty i puste wartosci."""
    name = display_name.strip()
    email = address.strip()
    if name and email and name.casefold() != email.casefold():
        return f"{name} <{email}>"
    return name or email


def _envelope_text(envelope: _Envelope) -> str:
    lines: list[str] = []
    if envelope.sender:
        lines.append(f"Od: {envelope.sender}")
    if envelope.to:
        lines.append(f"Do: {envelope.to}")
    if envelope.cc:
        lines.append(f"DW: {envelope.cc}")
    if envelope.bcc:
        lines.append(f"UDW: {envelope.bcc}")
    if envelope.subject:
        lines.append(f"Temat: {envelope.subject}")
    if envelope.sent_at is not None:
        lines.append(f"Data: {_format_timestamp(envelope.sent_at)}")
    return "\n".join(lines)


def _attachment_note(name: str, mime: str | None, size: int) -> str:
    parts = [f"Zalacznik: {name}"]
    if mime:
        parts.append(f"typ: {mime}")
    parts.append(f"rozmiar: {size} B")
    return ", ".join(parts)


def _build_metadata(envelope: _Envelope, attachment_count: int) -> DocumentMetadata:
    extra: dict[str, object] = {
        "to": envelope.to,
        "cc": envelope.cc,
        "from": envelope.sender,
        "liczba_zalacznikow": attachment_count,
    }
    if envelope.bcc:
        extra["bcc"] = envelope.bcc
    if envelope.message_class:
        extra["message_class"] = envelope.message_class
    return DocumentMetadata(
        title=envelope.subject or None,
        author=envelope.sender or None,
        subject=envelope.subject or None,
        created_at=envelope.sent_at,
        modified_at=envelope.modified_at,
        extra=extra,
    )


__all__ = ["MsgExtractor", "decompress_rtf"]
