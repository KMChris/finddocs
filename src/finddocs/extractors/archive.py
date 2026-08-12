"""Parser archiwow ZIP: spis zawartosci i wpisy do zaindeksowania.

Adapter jest rejestrowany wylacznie po wlaczeniu opcji indeksowania archiwow
(``indexing.index_archives``). Kazdy plik z archiwum trafia na liste
``ExtractionResult.attachments``, a warstwa potoku indeksuje go jako osobny
dokument podrzedny, ta sama sciezka co zalaczniki wiadomosci e-mail.

Sam dokument archiwum dostaje sekcje ze spisem plikow, dzieki czemu archiwum
mozna znalezc po nazwie pliku w srodku nawet wtedy, gdy wpis nie dal sie
rozpakowac.

Limity chronia pamiec i indeks przed bombami dekompresyjnymi: ograniczona jest
liczba wpisow, laczny rozmiar po rozpakowaniu oraz stosunek kompresji
pojedynczego wpisu.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Final

from finddocs.errors import CorruptedFileError, EmptyDocumentError, ExtractionError
from finddocs.extractors.base import ExtractionContext, Extractor
from finddocs.extractors.detect import guess_mime_from_name
from finddocs.logging_setup import get_logger
from finddocs.normalization.text import clean_text
from finddocs.types import (
    DocumentMetadata,
    ExtractedAttachment,
    ExtractedSection,
    ExtractionResult,
    SupportLevel,
    TextOrigin,
)

log = get_logger(__name__)

#: Maksymalna liczba wpisow rozpakowywanych z jednego archiwum.
MAX_MEMBERS: Final[int] = 200

#: Maksymalny laczny rozmiar rozpakowanych wpisow w bajtach.
MAX_TOTAL_MEMBER_BYTES: Final[int] = 200 * 1024 * 1024

#: Powyzej tego rozmiaru wpis o podejrzanym stosunku kompresji jest pomijany.
_BOMB_SIZE_THRESHOLD: Final[int] = 10 * 1024 * 1024

#: Stosunek rozmiaru po rozpakowaniu do spakowanego uznawany za bombe.
_BOMB_RATIO: Final[int] = 200

#: Ile wpisow spisu tresci laczyc w jedna sekcje.
_LISTING_CHUNK: Final[int] = 50

#: Prefiksy i nazwy plikow systemowych pomijanych bez ostrzezenia.
_JUNK_PREFIXES: Final[tuple[str, ...]] = ("__MACOSX/",)
_JUNK_NAMES: Final[frozenset[str]] = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})


class ZipArchiveExtractor(Extractor):
    """Adapter archiwow ZIP oparty o modul standardowy zipfile."""

    name = "zip"
    extensions = (".zip",)
    mime_types = ("application/zip",)
    support_level = SupportLevel.GOOD
    priority = 80

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        """Buduje spis zawartosci archiwum i wyciaga wpisy jako zalaczniki."""
        context.checkpoint()
        result = ExtractionResult(
            metadata=DocumentMetadata(title=path.stem),
            origin=TextOrigin.NATIVE,
            parser_name=self.name,
            support_level=self.support_level,
        )
        try:
            with zipfile.ZipFile(path) as archive:
                members = self._document_members(archive)
                if not members:
                    raise EmptyDocumentError(
                        f"Archiwum {path.name} nie zawiera żadnych plików.",
                        details={"plik": path.name},
                    )
                self._add_listing(members, context, result)
                if context.extract_attachments:
                    self._read_members(archive, members, context, result)
                else:
                    result.warnings.append(
                        "Zawartość zagnieżdżonego archiwum została pominięta, "
                        "osiągnięto limit zagnieżdżenia."
                    )
        except zipfile.BadZipFile as exc:
            raise CorruptedFileError(
                f"Archiwum {path.name} jest uszkodzone i nie da się go otworzyć.",
                details={"plik": path.name},
            ) from exc
        except (EmptyDocumentError, CorruptedFileError):
            raise
        except OSError as exc:
            raise ExtractionError(
                f"Nie udało się odczytać archiwum {path.name}.",
                details={"plik": path.name},
            ) from exc
        return result

    # --- wpisy archiwum ---------------------------------------------------------

    def _document_members(self, archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
        """Wpisy bedace plikami, bez katalogow i smieci systemowych."""
        members: list[zipfile.ZipInfo] = []
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if name.startswith(_JUNK_PREFIXES) or Path(name).name in _JUNK_NAMES:
                continue
            members.append(info)
        return members

    def _add_listing(
        self,
        members: list[zipfile.ZipInfo],
        context: ExtractionContext,
        result: ExtractionResult,
    ) -> None:
        """Sekcje ze spisem plikow: archiwum daje sie znalezc po nazwach wpisow."""
        names = [clean_text(info.filename.replace("\\", "/")) for info in members]
        names = [name for name in names if name]
        for order, start in enumerate(range(0, len(names), _LISTING_CHUNK)):
            context.checkpoint()
            block = names[start : start + _LISTING_CHUNK]
            result.sections.append(
                ExtractedSection(
                    text="\n".join(block),
                    kind="text",
                    order=order,
                    origin=TextOrigin.NATIVE,
                    heading="Spis zawartości archiwum",
                )
            )

    def _read_members(
        self,
        archive: zipfile.ZipFile,
        members: list[zipfile.ZipInfo],
        context: ExtractionContext,
        result: ExtractionResult,
    ) -> None:
        """Rozpakowuje wpisy do listy zalacznikow, pilnujac limitow."""
        budget = MAX_TOTAL_MEMBER_BYTES
        used = 0
        skipped_limit = 0
        for position, info in enumerate(members):
            context.checkpoint()
            if len(result.attachments) >= MAX_MEMBERS:
                skipped_limit = len(members) - position
                break
            size = info.file_size
            if info.flag_bits & 0x1:
                result.warnings.append(
                    f"Wpis {info.filename} jest zaszyfrowany i został pominięty."
                )
                continue
            if size > context.max_bytes:
                result.warnings.append(
                    f"Wpis {info.filename} przekracza limit rozmiaru pliku i został pominięty."
                )
                continue
            if size > budget - used:
                result.warnings.append(
                    f"Wpis {info.filename} nie zmieścił się w limicie łącznego rozmiaru "
                    "rozpakowanej zawartości i został pominięty."
                )
                continue
            if _looks_like_bomb(info):
                result.warnings.append(
                    f"Wpis {info.filename} ma podejrzany stosunek kompresji i został pominięty."
                )
                continue
            try:
                data = archive.read(info.filename)
            except (zipfile.BadZipFile, RuntimeError, OSError, ValueError) as exc:
                log.warning(
                    "archive.member_failed",
                    error_type=type(exc).__name__,
                )
                result.warnings.append(f"Nie udało się rozpakować wpisu {info.filename}.")
                continue
            if not data:
                continue
            used += len(data)
            name = info.filename.replace("\\", "/")
            result.attachments.append(
                ExtractedAttachment(
                    name=name,
                    mime_type=guess_mime_from_name(name),
                    data=data,
                )
            )
        if skipped_limit:
            result.warnings.append(
                f"Archiwum zawiera więcej plików niż limit {MAX_MEMBERS}, "
                f"pominięto {skipped_limit} wpisów."
            )


def _looks_like_bomb(info: zipfile.ZipInfo) -> bool:
    """Wpis o ekstremalnym stosunku kompresji to prawdopodobnie bomba dekompresyjna."""
    if info.file_size < _BOMB_SIZE_THRESHOLD:
        return False
    compressed = max(1, info.compress_size)
    return info.file_size / compressed > _BOMB_RATIO


__all__ = ["MAX_MEMBERS", "MAX_TOTAL_MEMBER_BYTES", "ZipArchiveExtractor"]
