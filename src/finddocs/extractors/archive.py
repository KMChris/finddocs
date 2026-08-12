"""Parsery archiwow: ZIP, 7z i RAR. Spis zawartosci i wpisy do zaindeksowania.

Adaptery sa rejestrowane wylacznie po wlaczeniu opcji indeksowania archiwow
(``indexing.index_archives``). Kazdy plik z archiwum trafia na liste
``ExtractionResult.attachments``, a warstwa potoku indeksuje go jako osobny
dokument podrzedny, ta sama sciezka co zalaczniki wiadomosci e-mail.

Sam dokument archiwum dostaje sekcje ze spisem plikow, dzieki czemu archiwum
mozna znalezc po nazwie pliku w srodku nawet wtedy, gdy wpis nie dal sie
rozpakowac.

Wspolne limity chronia pamiec i indeks przed bombami dekompresyjnymi:
ograniczona jest liczba wpisow, laczny rozmiar po rozpakowaniu oraz stosunek
kompresji pojedynczego wpisu (tam, gdzie format podaje rozmiar spakowany).

Archiwum RAR ma osobne zastrzezenie: wpisy zapisane bez kompresji czyta sama
biblioteka rarfile, ale wpisy skompresowane wymagaja zewnetrznego narzedzia
(unrar, bsdtar albo 7z). Bez narzedzia dokument dostaje spis plikow
i ostrzezenie, zamiast cichego pominiecia.
"""

from __future__ import annotations

import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from finddocs.errors import (
    CorruptedFileError,
    DependencyUnavailableError,
    EmptyDocumentError,
    ExtractionError,
    FindDocsError,
    PasswordProtectedError,
)
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


@dataclass(slots=True)
class _Member:
    """Jeden wpis archiwum w postaci wspolnej dla wszystkich formatow."""

    name: str
    size: int
    encrypted: bool = False
    suspicious: bool = False
    """Podejrzany stosunek kompresji: prawdopodobna bomba dekompresyjna."""


def _keep_member(name: str) -> bool:
    """Czy wpis jest dokumentem, a nie smieciem systemowym."""
    return not name.startswith(_JUNK_PREFIXES) and Path(name).name not in _JUNK_NAMES


def _looks_like_bomb(unpacked: int, packed: int) -> bool:
    """Wpis o ekstremalnym stosunku kompresji to prawdopodobnie bomba."""
    if unpacked < _BOMB_SIZE_THRESHOLD:
        return False
    return unpacked / max(1, packed) > _BOMB_RATIO


class _ArchiveExtractorBase(Extractor):
    """Wspolny szkielet adapterow archiwow: spis tresci, limity, zalaczniki."""

    def _new_result(self, path: Path) -> ExtractionResult:
        return ExtractionResult(
            metadata=DocumentMetadata(title=path.stem),
            origin=TextOrigin.NATIVE,
            parser_name=self.name,
            support_level=self.support_level,
        )

    def _require_members(self, members: list[_Member], path: Path) -> None:
        if not members:
            raise EmptyDocumentError(
                f"Archiwum {path.name} nie zawiera żadnych plików.",
                details={"plik": path.name},
            )

    def _add_listing(
        self,
        members: list[_Member],
        context: ExtractionContext,
        result: ExtractionResult,
    ) -> None:
        """Sekcje ze spisem plikow: archiwum daje sie znalezc po nazwach wpisow."""
        names = [clean_text(member.name) for member in members]
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

    def _nesting_warning(self, result: ExtractionResult) -> None:
        result.warnings.append(
            "Zawartość zagnieżdżonego archiwum została pominięta, osiągnięto limit zagnieżdżenia."
        )

    def _select_members(
        self,
        members: list[_Member],
        context: ExtractionContext,
        result: ExtractionResult,
    ) -> list[_Member]:
        """Wybiera wpisy miesczace sie w limitach, resztę opisuje ostrzezeniami."""
        selected: list[_Member] = []
        used = 0
        skipped_limit = 0
        for position, member in enumerate(members):
            context.checkpoint()
            if len(selected) >= MAX_MEMBERS:
                skipped_limit = len(members) - position
                break
            if member.encrypted:
                result.warnings.append(f"Wpis {member.name} jest zaszyfrowany i został pominięty.")
                continue
            if member.size > context.max_bytes:
                result.warnings.append(
                    f"Wpis {member.name} przekracza limit rozmiaru pliku i został pominięty."
                )
                continue
            if member.size > MAX_TOTAL_MEMBER_BYTES - used:
                result.warnings.append(
                    f"Wpis {member.name} nie zmieścił się w limicie łącznego rozmiaru "
                    "rozpakowanej zawartości i został pominięty."
                )
                continue
            if member.suspicious:
                result.warnings.append(
                    f"Wpis {member.name} ma podejrzany stosunek kompresji i został pominięty."
                )
                continue
            used += member.size
            selected.append(member)
        if skipped_limit:
            result.warnings.append(
                f"Archiwum zawiera więcej plików niż limit {MAX_MEMBERS}, "
                f"pominięto {skipped_limit} wpisów."
            )
        return selected

    def _read_selected(
        self,
        selected: list[_Member],
        read: Callable[[_Member], bytes | None],
        context: ExtractionContext,
        result: ExtractionResult,
    ) -> None:
        """Rozpakowuje wybrane wpisy do listy zalacznikow."""
        for member in selected:
            context.checkpoint()
            data = read(member)
            if not data:
                continue
            result.attachments.append(
                ExtractedAttachment(
                    name=member.name,
                    mime_type=guess_mime_from_name(member.name),
                    data=data,
                )
            )


class ZipArchiveExtractor(_ArchiveExtractorBase):
    """Adapter archiwow ZIP oparty o modul standardowy zipfile."""

    name = "zip"
    extensions = (".zip",)
    mime_types = ("application/zip",)
    support_level = SupportLevel.GOOD
    priority = 80

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        """Buduje spis zawartosci archiwum i wyciaga wpisy jako zalaczniki."""
        context.checkpoint()
        result = self._new_result(path)
        try:
            with zipfile.ZipFile(path) as archive:
                members, by_name = self._document_members(archive)
                self._require_members(members, path)
                self._add_listing(members, context, result)
                if not context.extract_attachments:
                    self._nesting_warning(result)
                    return result
                selected = self._select_members(members, context, result)

                def read(member: _Member) -> bytes | None:
                    try:
                        return archive.read(by_name[member.name].filename)
                    except (zipfile.BadZipFile, RuntimeError, OSError, ValueError) as exc:
                        log.warning("archive.member_failed", error_type=type(exc).__name__)
                        result.warnings.append(f"Nie udało się rozpakować wpisu {member.name}.")
                        return None

                self._read_selected(selected, read, context, result)
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

    def _document_members(
        self, archive: zipfile.ZipFile
    ) -> tuple[list[_Member], dict[str, zipfile.ZipInfo]]:
        """Wpisy bedace plikami, bez katalogow i smieci systemowych."""
        members: list[_Member] = []
        by_name: dict[str, zipfile.ZipInfo] = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if not _keep_member(name):
                continue
            members.append(
                _Member(
                    name=name,
                    size=info.file_size,
                    encrypted=bool(info.flag_bits & 0x1),
                    suspicious=_looks_like_bomb(info.file_size, info.compress_size),
                )
            )
            by_name[name] = info
        return members, by_name


class SevenZipArchiveExtractor(_ArchiveExtractorBase):
    """Adapter archiwow 7z oparty o biblioteke py7zr."""

    name = "7z"
    extensions = (".7z",)
    mime_types = ("application/x-7z-compressed",)
    support_level = SupportLevel.GOOD
    priority = 80

    def is_available(self) -> bool:
        try:
            import py7zr  # noqa: F401
        except ImportError:
            return False
        return True

    def unavailable_reason(self) -> str:
        if self.is_available():
            return ""
        return "Brak biblioteki py7zr wymaganej do odczytu archiwów 7z."

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        """Buduje spis zawartosci archiwum 7z i wyciaga wpisy jako zalaczniki."""
        try:
            import py7zr
        except ImportError as exc:
            raise DependencyUnavailableError(
                "Brak biblioteki py7zr wymaganej do odczytu archiwów 7z.",
                details={"parser": self.name},
                cause=exc,
            ) from exc

        context.checkpoint()
        result = self._new_result(path)
        try:
            with py7zr.SevenZipFile(str(path)) as archive:
                members = self._document_members(archive)
                self._require_members(members, path)
                self._add_listing(members, context, result)
                if not context.extract_attachments:
                    self._nesting_warning(result)
                    return result
                # Szyfrowanie w 7z obejmuje caly blok danych, wiec archiwum
                # z haslem daje sam spis tresci, jak zaszyfrowane wpisy ZIP.
                if archive.needs_password():
                    result.warnings.append("Wpisy archiwum są zaszyfrowane i zostały pominięte.")
                    return result
                selected = self._select_members(members, context, result)
                self._extract_selected(archive, selected, path, context, result)
        except py7zr.exceptions.PasswordRequired as exc:
            raise PasswordProtectedError(
                f"Archiwum {path.name} jest zaszyfrowane albo zabezpieczone hasłem.",
                details={"plik": path.name},
            ) from exc
        except py7zr.exceptions.Bad7zFile as exc:
            raise CorruptedFileError(
                f"Archiwum {path.name} jest uszkodzone i nie da się go otworzyć.",
                details={"plik": path.name},
            ) from exc
        except FindDocsError:
            raise
        except OSError as exc:
            raise ExtractionError(
                f"Nie udało się odczytać archiwum {path.name}.",
                details={"plik": path.name},
            ) from exc
        except Exception as exc:
            raise CorruptedFileError(
                f"Nie udało się rozpakować archiwum {path.name}.",
                details={"plik": path.name, "typ_bledu": type(exc).__name__},
            ) from exc
        return result

    def _document_members(self, archive: Any) -> list[_Member]:
        members: list[_Member] = []
        for info in archive.list():
            if info.is_directory:
                continue
            name = str(info.filename).replace("\\", "/")
            if not _keep_member(name):
                continue
            # Archiwum 7z pakuje pliki we wspolnych blokach, wiec rozmiar
            # spakowany pojedynczego wpisu nie jest znany. Przed bomba chroni
            # limit lacznego rozmiaru rozpakowanej zawartosci.
            members.append(_Member(name=name, size=int(info.uncompressed or 0)))
        return members

    def _extract_selected(
        self,
        archive: Any,
        selected: list[_Member],
        path: Path,
        context: ExtractionContext,
        result: ExtractionResult,
    ) -> None:
        """Rozpakowuje wybrane wpisy przez katalog tymczasowy obok archiwum.

        py7zr nie ma odczytu do pamieci, a katalog obok pliku wejsciowego
        lezy w tej samej bezpiecznej przestrzeni tymczasowej potoku.
        """
        if not selected:
            return
        with tempfile.TemporaryDirectory(dir=str(path.parent), prefix=".7z-") as tmp:
            archive.extract(path=tmp, targets=[member.name for member in selected])

            def read(member: _Member) -> bytes | None:
                target = Path(tmp).joinpath(*member.name.split("/"))
                try:
                    return target.read_bytes()
                except OSError:
                    result.warnings.append(f"Nie udało się rozpakować wpisu {member.name}.")
                    return None

            self._read_selected(selected, read, context, result)


class RarArchiveExtractor(_ArchiveExtractorBase):
    """Adapter archiwow RAR oparty o biblioteke rarfile.

    Wpisy zapisane bez kompresji sa czytane bezposrednio. Wpisy skompresowane
    wymagaja zewnetrznego narzedzia (unrar, bsdtar albo 7z); bez niego dokument
    dostaje spis plikow i ostrzezenie.
    """

    name = "rar"
    extensions = (".rar",)
    mime_types = ("application/vnd.rar",)
    support_level = SupportLevel.LIMITED
    priority = 80

    def is_available(self) -> bool:
        try:
            import rarfile  # noqa: F401
        except ImportError:
            return False
        return True

    def unavailable_reason(self) -> str:
        if self.is_available():
            return ""
        return "Brak biblioteki rarfile wymaganej do odczytu archiwów RAR."

    def extract(self, path: Path, context: ExtractionContext) -> ExtractionResult:
        """Buduje spis zawartosci archiwum RAR i wyciaga wpisy jako zalaczniki."""
        try:
            import rarfile
        except ImportError as exc:
            raise DependencyUnavailableError(
                "Brak biblioteki rarfile wymaganej do odczytu archiwów RAR.",
                details={"parser": self.name},
                cause=exc,
            ) from exc

        context.checkpoint()
        result = self._new_result(path)
        try:
            with rarfile.RarFile(str(path)) as archive:
                members = self._document_members(archive)
                self._require_members(members, path)
                self._add_listing(members, context, result)
                if not context.extract_attachments:
                    self._nesting_warning(result)
                    return result
                selected = self._select_members(members, context, result)
                tool_missing = False

                def read(member: _Member) -> bytes | None:
                    nonlocal tool_missing
                    if tool_missing:
                        return None
                    try:
                        return bytes(archive.read(member.name))
                    except rarfile.RarCannotExec:
                        tool_missing = True
                        result.warnings.append(
                            "Brak narzędzia do rozpakowania archiwum RAR (unrar, bsdtar "
                            "albo 7z). Zaindeksowano tylko spis plików."
                        )
                        return None
                    except rarfile.Error as exc:
                        log.warning("archive.member_failed", error_type=type(exc).__name__)
                        result.warnings.append(f"Nie udało się rozpakować wpisu {member.name}.")
                        return None

                self._read_selected(selected, read, context, result)
        except rarfile.PasswordRequired as exc:
            raise PasswordProtectedError(
                f"Archiwum {path.name} jest zaszyfrowane albo zabezpieczone hasłem.",
                details={"plik": path.name},
            ) from exc
        except (rarfile.NotRarFile, rarfile.BadRarFile) as exc:
            raise CorruptedFileError(
                f"Archiwum {path.name} jest uszkodzone i nie da się go otworzyć.",
                details={"plik": path.name},
            ) from exc
        except rarfile.NeedFirstVolume as exc:
            raise ExtractionError(
                f"Plik {path.name} to dalsza część archiwum wielotomowego. "
                "Zaindeksować można tylko pierwszy tom.",
                details={"plik": path.name},
            ) from exc
        except FindDocsError:
            raise
        except rarfile.Error as exc:
            raise CorruptedFileError(
                f"Nie udało się rozpakować archiwum {path.name}.",
                details={"plik": path.name, "typ_bledu": type(exc).__name__},
            ) from exc
        except OSError as exc:
            raise ExtractionError(
                f"Nie udało się odczytać archiwum {path.name}.",
                details={"plik": path.name},
            ) from exc
        return result

    def _document_members(self, archive: Any) -> list[_Member]:
        members: list[_Member] = []
        for info in archive.infolist():
            if info.isdir():
                continue
            name = str(info.filename).replace("\\", "/")
            if not _keep_member(name):
                continue
            size = int(info.file_size or 0)
            packed = int(info.compress_size or 0)
            members.append(
                _Member(
                    name=name,
                    size=size,
                    encrypted=bool(info.needs_password()),
                    suspicious=_looks_like_bomb(size, packed),
                )
            )
        return members


__all__ = [
    "MAX_MEMBERS",
    "MAX_TOTAL_MEMBER_BYTES",
    "RarArchiveExtractor",
    "SevenZipArchiveExtractor",
    "ZipArchiveExtractor",
]
