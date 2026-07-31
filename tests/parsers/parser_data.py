r"""Generatory malych plikow testowych dla parserow formatow.

Modul buduje w pamieci pliki tych formatow, ktorych nie da sie wygenerowac
bibliotekami dostepnymi w projekcie:

* kontener OLE (CFBF) uzywany przez pliki ``.msg`` oraz ``.doc``;
* skoroszyt BIFF2 czytany przez ``xlrd`` (biblioteka umie tylko czytac);
* dokument Word 97-2003 z tablica fragmentow tekstu (piece table);
* strumienie ``PR_RTF_COMPRESSED`` w wariantach ``MELA`` i ``LZFu``;
* dokument RTF z jawna strona kodowa cp1250.

Pozostale formaty powstaja w ``conftest.py`` przy pomocy python-docx, openpyxl,
Pillow oraz generatorow z ``finddocs.demo.generate``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

# --- wspolne dane testowe ------------------------------------------------------

#: Zdanie zawierajace wszystkie polskie znaki diakrytyczne.
POLISH_SAMPLE = "Zażółć gęślą jaźń"

#: Same litery diakrytyczne, male i wielkie.
POLISH_LETTERS = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"

#: Zdanie powtarzane w plikach testowych.
DISCLAIMER = "Dokument testowy, dane fikcyjne."


def assert_polish(text: str) -> None:
    """Sprawdza, ze tekst zachowal polskie znaki i nie ma znakow zastepczych."""
    assert POLISH_SAMPLE in text, f"brak polskiego zdania w tekscie: {text[:200]!r}"
    assert "�" not in text, "tekst zawiera znak zastepczy U+FFFD"
    assert "?" * 3 not in text, "polskie znaki zostaly zamienione na znaki zapytania"


# --- kontener OLE (CFBF) -------------------------------------------------------

#: Sygnatura kontenera OLE.
OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_SECTOR_SIZE = 512
_MINI_SECTOR_SIZE = 64
_MINI_CUTOFF = 4096
_FREESECT = 0xFFFFFFFF
_ENDOFCHAIN = 0xFFFFFFFE
_FATSECT = 0xFFFFFFFD
_NOSTREAM = 0xFFFFFFFF
_MAX_HEADER_FAT_SECTORS = 109

_KIND_STORAGE = 1
_KIND_STREAM = 2
_KIND_ROOT = 5


@dataclass(slots=True)
class _OleNode:
    """Jeden wpis katalogu kontenera OLE."""

    name: str
    kind: int
    data: bytes = b""
    children: list[_OleNode] = field(default_factory=list)
    start: int = _ENDOFCHAIN
    size: int = 0
    next_sid: int = _NOSTREAM


def _build_tree(entries: list[tuple[tuple[str, ...], bytes]]) -> _OleNode:
    """Buduje drzewo wpisow katalogu z listy (sciezka, dane)."""
    root = _OleNode(name="Root Entry", kind=_KIND_ROOT)
    index: dict[tuple[str, ...], _OleNode] = {(): root}
    for path, data in entries:
        if not path:
            raise ValueError("Sciezka wpisu w kontenerze OLE nie moze byc pusta.")
        parent = root
        for depth in range(1, len(path)):
            key = path[:depth]
            node = index.get(key)
            if node is None:
                node = _OleNode(name=path[depth - 1], kind=_KIND_STORAGE)
                index[key] = node
                parent.children.append(node)
            parent = node
        leaf = _OleNode(name=path[-1], kind=_KIND_STREAM, data=data, size=len(data))
        index[path] = leaf
        parent.children.append(leaf)
    return root


def _flatten_tree(root: _OleNode) -> list[_OleNode]:
    """Zwraca wpisy katalogu w kolejnosci nadawania identyfikatorow SID."""
    order: list[_OleNode] = []

    def walk(node: _OleNode) -> None:
        order.append(node)
        for kid in node.children:
            walk(kid)

    walk(root)
    return order


def _directory_entry(node: _OleNode, sids: dict[int, int]) -> bytes:
    """Sklada 128-bajtowy wpis katalogu.

    Rodzenstwo jest polaczone wylacznie wskaznikiem "w prawo": olefile przechodzi
    drzewo rekurencyjnie i nie wymaga zrownowazonego drzewa czerwono-czarnego.
    """
    raw_name = node.name.encode("utf-16-le") + b"\x00\x00"
    if len(raw_name) > 64:
        raise ValueError(f"Nazwa wpisu OLE jest za dluga: {node.name}")
    child = _NOSTREAM
    if node.children:
        child = sids[id(node.children[0])]
        for current, following in zip(node.children, node.children[1:], strict=False):
            current.next_sid = sids[id(following)]
    out = bytearray(raw_name.ljust(64, b"\x00"))
    out += struct.pack("<H", len(raw_name))
    out += struct.pack("<BB", node.kind, 1)
    out += struct.pack("<III", _NOSTREAM, node.next_sid, child)
    out += b"\x00" * 16
    out += struct.pack("<I", 0)
    out += b"\x00" * 16
    out += struct.pack("<I", 0 if node.kind == _KIND_STORAGE else node.start)
    out += struct.pack("<Q", 0 if node.kind == _KIND_STORAGE else node.size)
    return bytes(out)


class _SectorTable:
    """Prosty alokator sektorow wraz z tablica FAT."""

    def __init__(self) -> None:
        self.sectors: list[bytes] = []
        self.fat: list[int] = []

    def add_chain(self, payload: bytes) -> int:
        """Zapisuje dane w kolejnych sektorach i zwraca numer pierwszego z nich."""
        if not payload:
            return _ENDOFCHAIN
        payload += b"\x00" * ((-len(payload)) % _SECTOR_SIZE)
        first = len(self.sectors)
        count = len(payload) // _SECTOR_SIZE
        for offset in range(count):
            self.sectors.append(payload[offset * _SECTOR_SIZE : (offset + 1) * _SECTOR_SIZE])
            self.fat.append(len(self.sectors) if offset < count - 1 else _ENDOFCHAIN)
        return first


def _build_mini_stream(order: list[_OleNode]) -> tuple[bytes, list[int]]:
    """Sklada mini strumien z malych strumieni i zwraca (dane, mini FAT)."""
    payload = bytearray()
    minifat: list[int] = []
    for node in order:
        if node.kind != _KIND_STREAM or not node.data or len(node.data) >= _MINI_CUTOFF:
            continue
        blob = node.data + b"\x00" * ((-len(node.data)) % _MINI_SECTOR_SIZE)
        count = len(blob) // _MINI_SECTOR_SIZE
        node.start = len(minifat)
        for offset in range(count):
            minifat.append(len(minifat) + 1 if offset < count - 1 else _ENDOFCHAIN)
        payload += blob
    return bytes(payload), minifat


def _ole_header(
    *,
    fat_sids: list[int],
    dir_start: int,
    minifat_start: int,
    minifat_sectors: int,
) -> bytes:
    """Sklada 512-bajtowy naglowek kontenera OLE w wersji 3."""
    difat = fat_sids + [_FREESECT] * (_MAX_HEADER_FAT_SECTORS - len(fat_sids))
    header = bytearray(OLE_SIGNATURE)
    header += b"\x00" * 16
    header += struct.pack("<HHH", 0x003E, 0x0003, 0xFFFE)
    header += struct.pack("<HH", 9, 6)
    header += b"\x00" * 6
    header += struct.pack("<III", 0, len(fat_sids), dir_start)
    header += struct.pack("<II", 0, _MINI_CUTOFF)
    header += struct.pack("<II", minifat_start, minifat_sectors)
    header += struct.pack("<II", _ENDOFCHAIN, 0)
    header += b"".join(struct.pack("<I", value) for value in difat)
    return bytes(header)


def build_ole_container(entries: list[tuple[tuple[str, ...], bytes]]) -> bytes:
    """Buduje kontener OLE (CFBF) z podanych strumieni.

    ``entries`` to lista par (sciezka, dane), gdzie sciezka jest krotka nazw
    katalogow zakonczona nazwa strumienia. Strumienie krotsze niz 4096 bajtow
    trafiaja do mini strumienia, wieksze dostaja wlasne sektory.
    """
    root = _build_tree(entries)
    order = _flatten_tree(root)
    sids = {id(node): sid for sid, node in enumerate(order)}
    table = _SectorTable()

    for node in order:
        if node.kind == _KIND_STREAM and len(node.data) >= _MINI_CUTOFF:
            node.start = table.add_chain(node.data)

    mini_payload, minifat = _build_mini_stream(order)
    root.size = len(mini_payload)
    root.start = table.add_chain(mini_payload)

    minifat_start = _ENDOFCHAIN
    minifat_sectors = 0
    if minifat:
        per_sector = _SECTOR_SIZE // 4
        padded = minifat + [_FREESECT] * ((-len(minifat)) % per_sector)
        blob = b"".join(struct.pack("<I", value) for value in padded)
        minifat_start = table.add_chain(blob)
        minifat_sectors = len(padded) // per_sector

    directory = b"".join(_directory_entry(node, sids) for node in order)
    dir_start = table.add_chain(directory)

    per_sector = _SECTOR_SIZE // 4
    fat_count = 1
    while len(table.sectors) + fat_count > fat_count * per_sector:
        fat_count += 1
    if fat_count > _MAX_HEADER_FAT_SECTORS:
        raise ValueError("Plik testowy jest za duzy na kontener OLE bez sektorow DIFAT.")
    fat_sids: list[int] = []
    for _ in range(fat_count):
        fat_sids.append(len(table.sectors))
        table.sectors.append(b"\x00" * _SECTOR_SIZE)
        table.fat.append(_FATSECT)
    full = table.fat + [_FREESECT] * (fat_count * per_sector - len(table.fat))
    blob = b"".join(struct.pack("<I", value) for value in full)
    for position, sid in enumerate(fat_sids):
        table.sectors[sid] = blob[position * _SECTOR_SIZE : (position + 1) * _SECTOR_SIZE]

    header = _ole_header(
        fat_sids=fat_sids,
        dir_start=dir_start,
        minifat_start=minifat_start,
        minifat_sectors=minifat_sectors,
    )
    return header + b"".join(table.sectors)


# --- skoroszyt BIFF2 -----------------------------------------------------------

_BIFF_BOF = 0x0009
_BIFF_EOF = 0x000A
_BIFF_CODEPAGE = 0x0042
_BIFF_DIMENSIONS = 0x0000
_BIFF_FORMAT2 = 0x001E
_BIFF_XF2 = 0x0043
_BIFF_INTEGER = 0x0002
_BIFF_NUMBER = 0x0003
_BIFF_LABEL = 0x0004
_BIFF_BOOLERR = 0x0005

#: Numer strumienia oznaczajacy arkusz w rekordzie BOF.
_BIFF_STREAM_WORKSHEET = 0x0010

#: Formaty liczbowe zapisywane w pliku. Indeks 1 jest formatem daty.
BIFF2_FORMATS: tuple[str, ...] = ("General", "yyyy-mm-dd")

#: Indeks rekordu XF wskazujacy format daty.
BIFF2_DATE_XF = 1

#: Maksymalna wartosc zapisywana rekordem INTEGER.
_BIFF_MAX_INTEGER = 0xFFFF


def _biff_record(code: int, payload: bytes) -> bytes:
    return struct.pack("<HH", code, len(payload)) + payload


def _biff_cell(row: int, column: int, value: object, xf_index: int, encoding: str) -> bytes:
    """Sklada rekord jednej komorki BIFF2, dobierajac rekord do typu wartosci."""
    head = struct.pack("<HH", row, column) + bytes([xf_index & 0x3F, 0, 0])
    if isinstance(value, str):
        raw = value.encode(encoding)
        return _biff_record(_BIFF_LABEL, head + bytes([len(raw)]) + raw)
    if isinstance(value, bool):
        return _biff_record(_BIFF_BOOLERR, head + bytes([1 if value else 0, 0]))
    if isinstance(value, int) and 0 <= value <= _BIFF_MAX_INTEGER:
        return _biff_record(_BIFF_INTEGER, head + struct.pack("<H", value))
    return _biff_record(_BIFF_NUMBER, head + struct.pack("<d", float(value)))


def build_biff2_workbook(
    rows: list[list[object | tuple[object, int]]],
    *,
    encoding: str = "cp1250",
    codepage: int = 1250,
) -> bytes:
    """Buduje minimalny skoroszyt w formacie BIFF2 czytelny dla xlrd.

    Komorka moze byc wartoscia albo para (wartosc, indeks rekordu XF). Indeks
    ``BIFF2_DATE_XF`` przypisuje komorce format daty, dzieki czemu xlrd zwraca
    typ ``XL_CELL_DATE``. Plik zawiera naglowek BOF, tablice formatow, rekordy
    XF, wymiary arkusza, komorki oraz rekord EOF.
    """
    out = bytearray()
    out += _biff_record(_BIFF_BOF, struct.pack("<HH", 0x0002, _BIFF_STREAM_WORKSHEET))
    out += _biff_record(_BIFF_CODEPAGE, struct.pack("<H", codepage))
    for name in BIFF2_FORMATS:
        raw = name.encode(encoding)
        out += _biff_record(_BIFF_FORMAT2, bytes([len(raw)]) + raw)
    for format_index in range(len(BIFF2_FORMATS)):
        out += _biff_record(_BIFF_XF2, struct.pack("<BBBB", 0, 0, format_index, 0))
    columns = max((len(row) for row in rows), default=0)
    out += _biff_record(_BIFF_DIMENSIONS, struct.pack("<HHHH", 0, len(rows), 0, columns))
    for row_index, row in enumerate(rows):
        for column_index, cell in enumerate(row):
            value, xf_index = cell if isinstance(cell, tuple) else (cell, 0)
            out += _biff_cell(row_index, column_index, value, xf_index, encoding)
    out += _biff_record(_BIFF_EOF, b"")
    return bytes(out)


# --- dokument Word 97-2003 -----------------------------------------------------

#: Pozycja, od ktorej w strumieniu WordDocument zaczyna sie tekst.
_DOC_TEXT_START = 0x0800

#: Przesuniecie struktury Clx wewnatrz strumienia tabeli.
_DOC_CLX_OFFSET = 16

_DOC_OFF_FLAGS = 0x000A
_DOC_OFF_FC_MIN = 0x0018
_DOC_OFF_FC_MAC = 0x001C
_DOC_OFF_FC_CLX = 0x01A2
_DOC_OFF_LCB_CLX = 0x01A6

_DOC_FLAG_COMPLEX = 0x0004
_DOC_FLAG_ENCRYPTED = 0x0100
_DOC_FLAG_TABLE_1 = 0x0200
_DOC_FC_COMPRESSED = 0x40000000

#: Nazwa strumienia z naglowkiem FIB i tekstem dokumentu.
DOC_WORD_STREAM = "WordDocument"

#: Nazwa strumienia tabeli uzywana przez pliki testowe.
DOC_TABLE_STREAM = "1Table"


def build_word_fib(
    pieces: list[tuple[str, bool]], *, encrypted: bool = False
) -> tuple[bytes, bytes]:
    """Sklada strumienie WordDocument i 1Table dla pliku .doc.

    ``pieces`` to lista par (tekst, czy_jednobajtowy). Fragment jednobajtowy jest
    zapisany w cp1252, pozostale w UTF-16LE, zgodnie z bitem ``fCompressed``
    struktury PCD opisanej w [MS-DOC].
    """
    body = bytearray()
    raw_positions: list[int] = []
    character_positions = [0]
    total_characters = 0
    for text, compressed in pieces:
        offset = _DOC_TEXT_START + len(body)
        body += text.encode("cp1252") if compressed else text.encode("utf-16-le")
        total_characters += len(text)
        character_positions.append(total_characters)
        raw_positions.append((_DOC_FC_COMPRESSED | (offset << 1)) if compressed else offset)

    plc = bytearray()
    for position in character_positions:
        plc += struct.pack("<i", position)
    for raw_fc in raw_positions:
        plc += struct.pack("<HIH", 0, raw_fc, 0)
    clx = bytes([0x02]) + struct.pack("<I", len(plc)) + bytes(plc)
    table = b"\x00" * _DOC_CLX_OFFSET + clx

    flags = _DOC_FLAG_COMPLEX | _DOC_FLAG_TABLE_1
    if encrypted:
        flags |= _DOC_FLAG_ENCRYPTED
    fib = bytearray(b"\x00" * _DOC_TEXT_START)
    fib[0:2] = struct.pack("<H", 0xA5EC)
    fib[_DOC_OFF_FLAGS : _DOC_OFF_FLAGS + 2] = struct.pack("<H", flags)
    fib[_DOC_OFF_FC_MIN : _DOC_OFF_FC_MIN + 4] = struct.pack("<i", _DOC_TEXT_START)
    fib[_DOC_OFF_FC_MAC : _DOC_OFF_FC_MAC + 4] = struct.pack("<i", _DOC_TEXT_START + len(body))
    fib[_DOC_OFF_FC_CLX : _DOC_OFF_FC_CLX + 4] = struct.pack("<i", _DOC_CLX_OFFSET)
    fib[_DOC_OFF_LCB_CLX : _DOC_OFF_LCB_CLX + 4] = struct.pack("<i", len(clx))
    return bytes(fib) + bytes(body), table


def build_legacy_doc(pieces: list[tuple[str, bool]], *, encrypted: bool = False) -> bytes:
    """Buduje kompletny plik .doc: kontener OLE z FIB i strumieniem tabeli."""
    fib, table = build_word_fib(pieces, encrypted=encrypted)
    return build_ole_container(
        [((DOC_WORD_STREAM,), fib), ((DOC_TABLE_STREAM,), table)],
    )


# --- strumienie PR_RTF_COMPRESSED ----------------------------------------------

#: Znaczniki COMPTYPE z MS-OXRTFCP zapisane jako liczby little-endian.
RTF_MAGIC_COMPRESSED = 0x75465A4C
RTF_MAGIC_UNCOMPRESSED = 0x414C454D

#: Slownik startowy algorytmu LZFu, dokladnie 207 bajtow (MS-OXRTFCP 3.1.1.1).
LZFU_INIT_DICTIONARY = (
    b"{\\rtf1\\ansi\\mac\\deff0\\deftab720{\\fonttbl;}{\\f0\\fnil \\froman \\fswiss "
    b"\\fmodern \\fscript \\fdecor MS Sans SerifSymbolArialTimes New RomanCourier"
    b"{\\colortbl\\red0\\green0\\blue0\r\n\\par \\pard\\plain\\f0\\fs20\\b\\i\\u\\tab\\tx"
)


def _rtf_stream_header(payload: bytes, raw_size: int, magic: int) -> bytes:
    """Naglowek strumienia RTF: rozmiar skompresowany, surowy, typ i suma CRC."""
    return struct.pack("<4I", len(payload) + 12, raw_size, magic, 0) + payload


def build_uncompressed_rtf_stream(rtf: bytes) -> bytes:
    """Buduje strumien PR_RTF_COMPRESSED w wariancie ``MELA`` (bez kompresji)."""
    return _rtf_stream_header(rtf, len(rtf), RTF_MAGIC_UNCOMPRESSED)


def compress_rtf_lzfu(rtf: bytes) -> bytes:
    """Buduje strumien ``LZFu`` zapisany wylacznie literalami.

    Zapis samymi literalami jest poprawnym strumieniem LZFu: kazdy bit kontrolny
    rowny zero oznacza, ze kolejny bajt trafia wprost na wyjscie. Na koncu
    dopisywany jest znacznik konca, czyli referencja wskazujaca biezaca pozycje
    zapisu w slowniku.
    """
    payload = bytearray()
    for start in range(0, len(rtf), 8):
        block = rtf[start : start + 8]
        payload.append(0x00)
        payload += block
    write_offset = (len(LZFU_INIT_DICTIONARY) + len(rtf)) % 4096
    payload.append(0x01)
    payload += struct.pack(">H", (write_offset << 4) & 0xFFFF)
    return _rtf_stream_header(bytes(payload), len(rtf), RTF_MAGIC_COMPRESSED)


def build_lzfu_dictionary_reference(offset: int, length: int) -> bytes:
    """Buduje strumien LZFu zlozony z jednej referencji do slownika startowego."""
    if not 2 <= length <= 17:
        raise ValueError("Dlugosc referencji LZFu musi miescic sie w zakresie 2..17.")
    token = (offset << 4) | (length - 2)
    payload = bytes([0x01]) + struct.pack(">H", token)
    return _rtf_stream_header(payload, length, RTF_MAGIC_COMPRESSED)


# --- dokument RTF --------------------------------------------------------------


def rtf_escape_cp1250(text: str) -> str:
    r"""Zamienia tekst na sekwencje RTF, kodujac znaki spoza ASCII jako ``\'hh``."""
    out: list[str] = []
    for char in text:
        if char in "\\{}":
            out.append("\\" + char)
        elif ord(char) < 128:
            out.append(char)
        else:
            out.append(f"\\'{char.encode('cp1250')[0]:02x}")
    return "".join(out)


def rtf_escape_unicode(text: str) -> str:
    r"""Zamienia znaki spoza ASCII na polecenia ``\uN`` z zastepczym znakiem zapytania."""
    out: list[str] = []
    for char in text:
        if char in "\\{}":
            out.append("\\" + char)
        elif ord(char) < 128:
            out.append(char)
        else:
            out.append(f"\\u{ord(char)}?")
    return "".join(out)


def build_rtf_document(
    paragraphs: list[str],
    *,
    title: str = "",
    author: str = "",
    table_rows: list[list[str]] | None = None,
    unicode_paragraphs: list[str] | None = None,
    pages: int = 0,
) -> bytes:
    r"""Buduje dokument RTF w stronie kodowej cp1250.

    Akapity z ``paragraphs`` sa kodowane sekwencjami ``\'hh``, a te
    z ``unicode_paragraphs`` poleceniami ``\uN``. Wiersze ``table_rows`` sa
    zapisywane komorkami ``\cell``.
    """
    parts: list[str] = [
        r"{\rtf1\ansi\ansicpg1250\deff0\uc1",
        r"{\fonttbl{\f0\fswiss\fcharset238 Arial;}}",
    ]
    info: list[str] = []
    if title:
        info.append(r"{\title " + rtf_escape_cp1250(title) + "}")
    if author:
        info.append(r"{\author " + rtf_escape_cp1250(author) + "}")
    info.append(r"{\creatim\yr2024\mo3\dy15\hr10\min20}")
    if pages > 0:
        info.append(rf"\nofpages{pages}")
    parts.append(r"{\info" + "".join(info) + "}")
    parts.append(r"\viewkind4\pard\f0\fs24 ")
    parts.extend(rtf_escape_cp1250(text) + r"\par" for text in paragraphs)
    parts.extend(rtf_escape_unicode(text) + r"\par" for text in unicode_paragraphs or [])
    for row in table_rows or []:
        parts.append(r"\trowd")
        parts.extend(rtf_escape_cp1250(cell) + r"\cell" for cell in row)
        parts.append(r"\row")
    parts.append("}")
    return "\r\n".join(parts).encode("cp1250")


__all__ = [
    "BIFF2_DATE_XF",
    "BIFF2_FORMATS",
    "DISCLAIMER",
    "DOC_TABLE_STREAM",
    "DOC_WORD_STREAM",
    "LZFU_INIT_DICTIONARY",
    "OLE_SIGNATURE",
    "POLISH_LETTERS",
    "POLISH_SAMPLE",
    "RTF_MAGIC_COMPRESSED",
    "RTF_MAGIC_UNCOMPRESSED",
    "assert_polish",
    "build_biff2_workbook",
    "build_legacy_doc",
    "build_lzfu_dictionary_reference",
    "build_ole_container",
    "build_rtf_document",
    "build_uncompressed_rtf_stream",
    "build_word_fib",
    "compress_rtf_lzfu",
    "rtf_escape_cp1250",
    "rtf_escape_unicode",
]
