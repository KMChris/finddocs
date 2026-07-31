"""Wykrywanie typu pliku na podstawie zawartosci, rozszerzenia i typu MIME.

Kolejnosc: najpierw sygnatura binarna (magic bytes), potem rozszerzenie, na koncu
typ MIME podany przez zrodlo. Sygnatura ma pierwszenstwo, bo nazwa pliku w SharePoint
bywa mylaca (np. skan zapisany jako ``.pdf``, ktory w rzeczywistosci jest obrazem TIFF).
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

#: Mapowanie rozszerzenie -> typ MIME.
EXTENSION_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".docm": "application/vnd.ms-word.document.macroEnabled.12",
    ".doc": "application/msword",
    ".dot": "application/msword",
    ".rtf": "application/rtf",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".xls": "application/vnd.ms-excel",
    ".xlt": "application/vnd.ms-excel",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".txt": "text/plain",
    ".log": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".xml": "application/xml",
    ".html": "text/html",
    ".htm": "text/html",
    ".eml": "message/rfc822",
    ".msg": "application/vnd.ms-outlook",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".zip": "application/zip",
}

#: Sygnatury binarne. Klucz to prefiks bajtow, wartosc to ogolna rodzina formatu.
MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "application/x-ole-storage"),
    (b"PK\x03\x04", "application/zip"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
    (b"BM", "image/bmp"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"{\\rtf", "application/rtf"),
    (b"\x1f\x8b", "application/gzip"),
    (b"7z\xbc\xaf\x27\x1c", "application/x-7z-compressed"),
    (b"Rar!\x1a\x07", "application/vnd.rar"),
)

#: Wpisy w archiwum ZIP charakterystyczne dla formatow Office Open XML.
OOXML_MARKERS: tuple[tuple[str, str], ...] = (
    (
        "word/document.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    ("xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    (
        "ppt/presentation.xml",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    ("content.xml", "application/vnd.oasis.opendocument.text"),
)

#: Nazwy strumieni OLE pozwalajace odroznic stare formaty Microsoft Office.
OLE_STREAM_HINTS: tuple[tuple[str, str], ...] = (
    ("WordDocument", "application/msword"),
    ("Workbook", "application/vnd.ms-excel"),
    ("Book", "application/vnd.ms-excel"),
    ("PowerPoint Document", "application/vnd.ms-powerpoint"),
    ("__properties_version1.0", "application/vnd.ms-outlook"),
)

IMAGE_MIME_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/tiff", "image/bmp", "image/gif", "image/webp"}
)

TEXT_MIME_TYPES = frozenset(
    {
        "text/plain",
        "text/csv",
        "text/tab-separated-values",
        "text/markdown",
        "application/json",
        "application/xml",
        "text/html",
    }
)


@dataclass(frozen=True, slots=True)
class FileTypeInfo:
    """Wynik rozpoznania typu pliku."""

    mime_type: str
    extension: str
    detected_by: str
    """magic, zip_entry, ole_stream, extension albo source."""

    is_container: bool = False
    is_encrypted: bool = False

    @property
    def is_image(self) -> bool:
        return self.mime_type in IMAGE_MIME_TYPES

    @property
    def is_text(self) -> bool:
        return self.mime_type in TEXT_MIME_TYPES


def _read_head(path: Path, size: int = 512) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(size)
    except OSError:
        return b""


def _detect_zip_family(path: Path) -> tuple[str, bool]:
    """Rozroznia formaty oparte o ZIP. Zwraca (mime, czy_zaszyfrowany)."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            encrypted = any(info.flag_bits & 0x1 for info in archive.infolist())
            for marker, mime in OOXML_MARKERS:
                if marker in names:
                    return mime, encrypted
            if "mimetype" in names:
                try:
                    declared = archive.read("mimetype").decode("ascii", "ignore").strip()
                except (KeyError, OSError):
                    declared = ""
                if declared:
                    return declared, encrypted
            return "application/zip", encrypted
    except (zipfile.BadZipFile, OSError):
        return "application/zip", False


def _detect_ole_family(path: Path) -> tuple[str, bool]:
    """Rozroznia stare formaty Microsoft Office oparte o OLE."""
    try:
        import olefile
    except ImportError:  # pragma: no cover - olefile jest zaleznoscia obowiazkowa
        return "application/x-ole-storage", False
    try:
        if not olefile.isOleFile(str(path)):
            return "application/x-ole-storage", False
        with olefile.OleFileIO(str(path)) as ole:
            entries = {"/".join(part) for part in ole.listdir()}
            flat = {part[0] for part in ole.listdir() if part}
            encrypted = "EncryptedPackage" in flat or "EncryptionInfo" in flat
            if encrypted:
                return "application/x-ole-encrypted", True
            for hint, mime in OLE_STREAM_HINTS:
                if hint in flat or any(e.startswith(hint) for e in entries):
                    return mime, False
    except (OSError, ValueError):
        return "application/x-ole-storage", False
    return "application/x-ole-storage", False


def detect_file_type(
    path: Path, *, declared_mime: str | None = None, file_name: str | None = None
) -> FileTypeInfo:
    """Rozpoznaje typ pliku. Nazwa pliku moze pochodzic ze zrodla, gdy sciezka jest tymczasowa."""
    name = file_name or path.name
    extension = Path(name).suffix.lower()
    head = _read_head(path)

    for signature, family in MAGIC_SIGNATURES:
        if not head.startswith(signature):
            continue
        if family == "application/zip":
            mime, encrypted = _detect_zip_family(path)
            if mime == "application/zip" and extension in EXTENSION_MIME:
                mime = EXTENSION_MIME[extension]
            return FileTypeInfo(
                mime_type=mime,
                extension=extension,
                detected_by="zip_entry",
                is_container=mime == "application/zip",
                is_encrypted=encrypted,
            )
        if family == "application/x-ole-storage":
            mime, encrypted = _detect_ole_family(path)
            if mime == "application/x-ole-storage" and extension in EXTENSION_MIME:
                mime = EXTENSION_MIME[extension]
            return FileTypeInfo(
                mime_type=mime,
                extension=extension,
                detected_by="ole_stream",
                is_encrypted=encrypted,
            )
        return FileTypeInfo(mime_type=family, extension=extension, detected_by="magic")

    if extension in EXTENSION_MIME:
        return FileTypeInfo(
            mime_type=EXTENSION_MIME[extension],
            extension=extension,
            detected_by="extension",
        )

    if declared_mime:
        return FileTypeInfo(mime_type=declared_mime, extension=extension, detected_by="source")

    if head and _looks_like_text(head):
        return FileTypeInfo(mime_type="text/plain", extension=extension, detected_by="heuristic")

    return FileTypeInfo(
        mime_type="application/octet-stream", extension=extension, detected_by="fallback"
    )


def _looks_like_text(head: bytes) -> bool:
    """Prosta heurystyka: brak bajtu zerowego i wysoki udzial znakow drukowalnych."""
    if b"\x00" in head:
        return False
    printable = sum(1 for b in head if 9 <= b <= 13 or 32 <= b <= 126 or b >= 160)
    return bool(head) and printable / len(head) > 0.9


def guess_mime_from_name(name: str) -> str | None:
    return EXTENSION_MIME.get(Path(name).suffix.lower())


__all__ = [
    "EXTENSION_MIME",
    "IMAGE_MIME_TYPES",
    "MAGIC_SIGNATURES",
    "OLE_STREAM_HINTS",
    "OOXML_MARKERS",
    "TEXT_MIME_TYPES",
    "FileTypeInfo",
    "detect_file_type",
    "guess_mime_from_name",
]
