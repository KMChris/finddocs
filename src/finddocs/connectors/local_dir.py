"""Konektor katalogu lokalnego.

Zrodlo oparte o katalog na dysku albo o zasob sieciowy zamontowany w systemie.
Enumeracja jest leniwa i deterministyczna: wpisy kazdego katalogu sortujemy po
nazwie, a katalogi odwiedzamy w gleb w tej samej kolejnosci. Dzieki temu pozycja
w skanowaniu daje sie zapisac jako zwykly licznik i wznowic po przerwaniu.

Konektor nie wychodzi poza katalog korzenia: dowiazania symboliczne sa domyslnie
pomijane, a sciezki obiektow sa sprawdzane przed zlozeniem pelnej sciezki pliku.
"""

from __future__ import annotations

import datetime as _dt
import fnmatch
import mimetypes
import os
import shutil
import stat
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from finddocs.config import LocalDirSourceSettings, SourceConfig
from finddocs.connectors.base import (
    ConnectionStatus,
    ScanCursor,
    SourceConnector,
    ensure_space_for,
    sha256_of_file,
)
from finddocs.errors import (
    ConfigurationError,
    ConnectorError,
    DownloadError,
    SourceUnavailableError,
    TemporaryStorageError,
)
from finddocs.logging_setup import get_logger
from finddocs.types import CancellationToken, FetchedFile, SourceItem, SourceKind

log = get_logger(__name__)

CANCEL_CHECK_INTERVAL = 200
"""Co tyle obejrzanych pozycji sprawdzamy zadanie anulowania."""

MAX_TOP_LEVEL_PROBE = 5000
"""Górny limit zliczania pozycji przy tescie połączenia."""

ESTIMATE_BUDGET_SECONDS = 15.0
"""Ile czasu wolno poświęcić na policzenie plików przed skanowaniem."""

HIDDEN_ATTRIBUTES = stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM
"""Atrybuty Windows uznawane za oznaczenie pozycji ukrytej."""

SYSTEM_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        "$recycle.bin",
        "recycler",
        "system volume information",
        "msocache",
        "config.msi",
        "$windows.~bt",
        "$windows.~ws",
        "found.000",
    }
)
"""Katalogi systemowe Windows, których nie ma sensu przeglądać."""

FALLBACK_FILE_NAME = "dokument"
"""Nazwa zastępcza, gdy pozycja nie niesie poprawnej nazwy pliku."""


# --- funkcje pomocnicze ---------------------------------------------------------


def _normalize_extensions(values: Iterable[str]) -> frozenset[str]:
    """Sprowadza rozszerzenia do postaci '.ext' pisanej malymi literami."""
    normalized: set[str] = set()
    for raw in values:
        text = raw.strip().lower()
        if not text:
            continue
        normalized.add(text if text.startswith(".") else f".{text}")
    return frozenset(normalized)


def _normalize_root(raw: str) -> Path | None:
    """Zwraca bezwzgledna sciezke korzenia albo None, gdy katalogu nie wskazano."""
    text = raw.strip()
    if not text:
        return None
    path = Path(text).expanduser()
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _local_datetime(timestamp: float) -> _dt.datetime | None:
    """Zamienia znacznik czasu systemu plikow na date ze strefa lokalna."""
    try:
        return _dt.datetime.fromtimestamp(timestamp).astimezone()
    except (OSError, OverflowError, ValueError):
        return None


def _file_uri(path: Path) -> str | None:
    """Adres file:// wskazujacy plik albo katalog. None, gdy sciezka wzgledna."""
    try:
        return path.as_uri()
    except ValueError:
        return None


def _format_size(value: int | None) -> str:
    """Czytelny opis rozmiaru w MB albo GB."""
    if value is None:
        return "nieznane"
    gigabytes = value / 1024**3
    if gigabytes >= 1.0:
        return f"{gigabytes:.1f} GB"
    return f"{value / 1024**2:.0f} MB"


def _free_space(path: Path) -> int | None:
    """Wolne miejsce na wolumenie ze wskazana sciezka. None, gdy nie da sie ustalic."""
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


# --- konektor -------------------------------------------------------------------


class LocalDirectoryConnector(SourceConnector):
    """Zrodlo dokumentow oparte o katalog w systemie plikow."""

    kind = SourceKind.LOCAL_DIR

    #: ``fetch`` czyta wylacznie pola niezmienne po konstrukcji i pisze do
    #: katalogu roboczego wlasnego dokumentu, wiec rownolegle pobieranie
    #: z kilku watkow jest bezpieczne.
    supports_parallel_fetch = True

    def __init__(
        self,
        source_id: str,
        label: str,
        settings: LocalDirSourceSettings,
        include_extensions: list[str],
        exclude_extensions: list[str],
        exclude_globs: list[str],
        max_file_size_mb: int,
    ) -> None:
        self.source_id = source_id
        self.label = label
        self.settings = settings
        self.include_extensions = _normalize_extensions(include_extensions)
        self.exclude_extensions = _normalize_extensions(exclude_extensions)
        self.exclude_globs: tuple[str, ...] = tuple(
            pattern.strip() for pattern in exclude_globs if pattern.strip()
        )
        self.max_file_size_mb = int(max_file_size_mb)
        self._max_bytes = max(0, self.max_file_size_mb) * 1024 * 1024
        self._root = _normalize_root(settings.root_path)
        self._visited = 0
        self._complete = False

    @classmethod
    def from_config(cls, source: SourceConfig) -> LocalDirectoryConnector:
        """Buduje konektor na podstawie wpisu konfiguracji."""
        if source.kind is not SourceKind.LOCAL_DIR:
            raise ConfigurationError(
                f"Źródło '{source.source_id}' nie jest katalogiem lokalnym, "
                f"tylko zrodlem typu '{source.kind.value}'.",
                details={"source_id": source.source_id},
            )
        return cls(
            source.source_id,
            source.label,
            source.local,
            list(source.include_extensions),
            list(source.exclude_extensions),
            list(source.exclude_globs),
            source.max_file_size_mb,
        )

    # --- podstawowe informacje -------------------------------------------

    @property
    def root(self) -> Path | None:
        """Katalog korzenia zrodla albo None, gdy nie zostal wskazany."""
        return self._root

    def describe(self) -> dict[str, Any]:
        opis = super().describe()
        opis["katalog"] = str(self._root) if self._root is not None else ""
        return opis

    def _configured_root(self) -> Path:
        if self._root is None:
            raise ConfigurationError(
                f"Źródło '{self.label}' nie ma wskazanego katalogu. "
                "Uzupełnij ścieżkę w ustawieniach źródła.",
                details={"source_id": self.source_id},
            )
        return self._root

    def _existing_root(self) -> Path:
        root = self._configured_root()
        try:
            is_directory = root.is_dir()
        except OSError as exc:
            raise SourceUnavailableError(
                f"Nie udało się odczytać katalogu {root}: {type(exc).__name__}.",
                details={"source_id": self.source_id},
                cause=exc,
            ) from exc
        if not is_directory:
            raise SourceUnavailableError(
                f"Katalog {root} nie istnieje albo nie jest dostępny.",
                details={"source_id": self.source_id},
            )
        return root

    # --- test polaczenia --------------------------------------------------

    def test_connection(self) -> ConnectionStatus:
        """Sprawdza, czy katalog istnieje, jest katalogiem i da sie go odczytac."""
        if self._root is None:
            return ConnectionStatus(
                ok=False,
                message="Nie wskazano katalogu źródłowego. Wybierz katalog w ustawieniach.",
                details={"katalog": ""},
            )

        root = self._root
        details: dict[str, Any] = {"katalog": str(root)}
        try:
            exists = root.exists()
            is_directory = root.is_dir()
        except OSError as exc:
            return ConnectionStatus(
                ok=False,
                message=f"Nie udało się sprawdzić katalogu {root}: {type(exc).__name__}.",
                details=details,
            )
        if not exists:
            return ConnectionStatus(
                ok=False,
                message=f"Katalog {root} nie istnieje albo jest chwilowo niedostępny.",
                details=details,
            )
        if not is_directory:
            return ConnectionStatus(
                ok=False,
                message=f"Ścieżka {root} wskazuje plik, a nie katalog.",
                details=details,
            )

        try:
            count, truncated = self._count_top_level(root)
        except PermissionError:
            return ConnectionStatus(
                ok=False,
                message=f"Brak uprawnień do odczytu katalogu {root}.",
                details=details,
            )
        except OSError as exc:
            return ConnectionStatus(
                ok=False,
                message=f"Nie udało się odczytać katalogu {root}: {type(exc).__name__}.",
                details=details,
            )

        free = _free_space(root)
        details["pozycji_na_pierwszym_poziomie"] = count
        details["licznik_ograniczony"] = truncated
        details["wolne_miejsce_bajty"] = free
        details["wolne_miejsce_opis"] = _format_size(free)
        suffix = " lub więcej" if truncated else ""
        log.info("local_dir.connection_ok", source_id=self.source_id, entries=count)
        return ConnectionStatus(
            ok=True,
            message=(
                f"Katalog jest dostępny. Pozycji na pierwszym poziomie: {count}{suffix}. "
                f"Wolne miejsce: {_format_size(free)}."
            ),
            details=details,
        )

    def _count_top_level(self, root: Path) -> tuple[int, bool]:
        """Liczy pozycje na pierwszym poziomie, nie dluzej niz do limitu sondy."""
        count = 0
        with os.scandir(root) as entries:
            for _entry in entries:
                count += 1
                if count >= MAX_TOP_LEVEL_PROBE:
                    return count, True
        return count, False

    # --- enumeracja -------------------------------------------------------

    def iter_items(
        self,
        *,
        cursor: ScanCursor | None = None,
        cancel: CancellationToken | None = None,
    ) -> Iterator[SourceItem]:
        """Wylicza pliki w katalogu, schodzac rekurencyjnie w podkatalogi.

        Kolejnosc jest deterministyczna, wiec ``cursor.visited`` wystarczy, zeby
        pominac pozycje przetworzone w poprzednim przebiegu. Pliki wieksze niz
        dozwolony limit sa zwracane z ``extra['too_large']`` ustawionym na True,
        zeby warstwa wyzsza mogla policzyc je jako pominiete.
        """
        root = self._existing_root()
        start = max(0, cursor.visited) if cursor is not None else 0
        self._visited = 0
        self._complete = False
        log.info("local_dir.scan_started", source_id=self.source_id, resume_from=start)
        return self._walk(root, start=start, cancel=cancel)

    def _walk(
        self,
        root: Path,
        *,
        start: int,
        cancel: CancellationToken | None,
    ) -> Iterator[SourceItem]:
        position = 0
        for item in self._traverse(root, cancel=cancel):
            position += 1
            self._visited = position
            if position <= start:
                continue
            yield item

        self._visited = position
        self._complete = True
        log.info("local_dir.scan_finished", source_id=self.source_id, items=position)

    def _traverse(
        self,
        root: Path,
        *,
        cancel: CancellationToken | None,
    ) -> Iterator[SourceItem]:
        """Przechodzi drzewo katalogow i zwraca pozycje przechodzace filtry.

        Kolejnosc jest deterministyczna. Metoda nie zna pojecia pozycji ani
        wznowienia: tym zajmuje sie ``_walk``. Dzieki temu liczenie plikow
        na potrzeby postepu uzywa dokladnie tych samych filtrow co skanowanie.
        """
        library = root.name or str(root)
        stack: list[Path] = [root]
        visited_dirs: set[str] = set()
        examined = 0

        while stack:
            current = stack.pop()
            if self.settings.follow_symlinks and not self._first_visit(current, visited_dirs):
                continue
            subdirectories: list[Path] = []
            for entry in self._scan(current):
                examined += 1
                if cancel is not None and examined % CANCEL_CHECK_INTERVAL == 0:
                    cancel.raise_if_cancelled()
                item = self._inspect(entry, root, library, subdirectories)
                if item is not None:
                    yield item
            stack.extend(reversed(subdirectories))

    def estimate_total(self, *, cancel: CancellationToken | None = None) -> int | None:
        """Liczy pliki pasujace do filtrow, zeby postep mial mianownik.

        Przejscie po katalogach bez czytania plikow jest o rzedy wielkosci
        tansze niz ich przetworzenie, wiec oplaca sie zrobic je raz na poczatku.
        Na bardzo duzym zasobie samo liczenie tez trwa, dlatego ma budzet czasu:
        po jego przekroczeniu konektor zwraca None i pasek zostaje nieokreslony.
        """
        try:
            root = self._existing_root()
        except SourceUnavailableError:
            return None
        deadline = time.monotonic() + ESTIMATE_BUDGET_SECONDS
        total = 0
        for _item in self._traverse(root, cancel=cancel):
            total += 1
            if total % CANCEL_CHECK_INTERVAL == 0 and time.monotonic() > deadline:
                log.info("local_dir.estimate_abandoned", source_id=self.source_id, counted=total)
                return None
        log.info("local_dir.estimate_ready", source_id=self.source_id, total=total)
        return total

    def _first_visit(self, directory: Path, visited: set[str]) -> bool:
        """Zabezpiecza przed petla przy wlaczonym podazaniu za dowiazaniami."""
        try:
            key = str(directory.resolve())
        except OSError:
            key = str(directory)
        if key in visited:
            log.debug("local_dir.loop_skipped", source_id=self.source_id)
            return False
        visited.add(key)
        return True

    def _scan(self, directory: Path) -> list[os.DirEntry[str]]:
        """Zwraca posortowana zawartosc katalogu. Blad katalogu nie przerywa skanu."""
        try:
            with os.scandir(directory) as iterator:
                entries = list(iterator)
        except PermissionError:
            log.warning(
                "local_dir.directory_forbidden",
                source_id=self.source_id,
                directory=directory.name,
            )
            return []
        except OSError as exc:
            log.warning(
                "local_dir.directory_unreadable",
                source_id=self.source_id,
                directory=directory.name,
                reason=type(exc).__name__,
            )
            return []
        entries.sort(key=lambda item: item.name)
        return entries

    def _inspect(
        self,
        entry: os.DirEntry[str],
        root: Path,
        library: str,
        subdirectories: list[Path],
    ) -> SourceItem | None:
        """Ocenia pozycje katalogu: zwraca obiekt zrodla albo dopisuje podkatalog."""
        follow = self.settings.follow_symlinks
        try:
            if entry.is_symlink() and not follow:
                return None
            info = entry.stat()
            is_directory = entry.is_dir()
            is_file = entry.is_file()
        except OSError as exc:
            log.warning(
                "local_dir.entry_unreadable",
                source_id=self.source_id,
                reason=type(exc).__name__,
            )
            return None

        name = entry.name
        if not self.settings.include_hidden and self._is_hidden(name, info):
            return None

        path = Path(entry.path)
        relative = self._relative(path, root)
        if relative is None:
            return None
        if self._matches_exclude_glob(relative, name):
            return None

        if is_directory:
            if not self.settings.include_hidden and name.lower() in SYSTEM_DIRECTORY_NAMES:
                return None
            subdirectories.append(path)
            return None
        if not is_file:
            return None
        if not self._extension_allowed(name):
            return None
        return self._build_item(path, relative, library, info)

    def _is_hidden(self, name: str, info: os.stat_result) -> bool:
        """Rozpoznaje pozycje ukryta po nazwie z kropka albo po atrybutach Windows."""
        if name.startswith("."):
            return True
        attributes = int(getattr(info, "st_file_attributes", 0))
        return bool(attributes & HIDDEN_ATTRIBUTES)

    def _relative(self, path: Path, root: Path) -> str | None:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return None

    def _matches_exclude_glob(self, relative: str, name: str) -> bool:
        """Dopasowuje wzorce do sciezki wzglednej oraz do samej nazwy pliku."""
        return any(
            fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(name, pattern)
            for pattern in self.exclude_globs
        )

    def _extension_allowed(self, name: str) -> bool:
        extension = Path(name).suffix.lower()
        if extension in self.exclude_extensions:
            return False
        return not (self.include_extensions and extension not in self.include_extensions)

    def _build_item(
        self,
        path: Path,
        relative: str,
        library: str,
        info: os.stat_result,
    ) -> SourceItem:
        size = int(info.st_size)
        extra: dict[str, Any] = {}
        if self._max_bytes > 0 and size > self._max_bytes:
            extra["too_large"] = True
            extra["limit_mb"] = self.max_file_size_mb
        return SourceItem(
            source_id=self.source_id,
            external_id=relative,
            name=path.name,
            logical_path=relative,
            size=size,
            modified_at=_local_datetime(info.st_mtime),
            created_at=_local_datetime(info.st_ctime),
            etag=f"{size}-{int(info.st_mtime)}",
            mime_type=mimetypes.guess_type(path.name)[0],
            web_url=_file_uri(path),
            parent_url=_file_uri(path.parent),
            library=library,
            extra=extra,
        )

    def cursor(self) -> ScanCursor:
        """Pozycja enumeracji: liczba odwiedzonych pozycji i znacznik zakonczenia."""
        return ScanCursor(token=None, visited=self._visited, complete=self._complete)

    # --- pobieranie -------------------------------------------------------

    def local_path(self, item: SourceItem) -> Path:
        """Pelna sciezka pliku opisanego przez pozycje zrodla.

        Ścieżka wzgledna nie moze wychodzic poza korzen zrodla. Segment '..',
        sciezka pusta i sciezka bezwzgledna sa odrzucane.
        """
        root = self._configured_root()
        parts = [
            part for part in item.external_id.replace("\\", "/").split("/") if part not in {"", "."}
        ]
        if not parts or ".." in parts:
            raise ConnectorError(
                f"Identyfikator '{item.external_id}' nie wskazuje pliku w katalogu źródła.",
                details={"source_id": self.source_id},
            )
        candidate = root.joinpath(*parts)
        if not self._inside_root(candidate, root):
            raise ConnectorError(
                f"Identyfikator '{item.external_id}' wskazuje poza katalog źródła.",
                details={"source_id": self.source_id},
            )
        return candidate

    def _inside_root(self, candidate: Path, root: Path) -> bool:
        """Sprawdza, czy zlozona sciezka nadal lezy w katalogu korzenia."""
        try:
            candidate.relative_to(root)
        except ValueError:
            return False
        return candidate != root

    def fetch(
        self,
        item: SourceItem,
        destination: Path,
        *,
        cancel: CancellationToken | None = None,
    ) -> FetchedFile:
        """Kopiuje plik do katalogu roboczego i liczy jego skrot sha256.

        Kopiowanie jest pomijane, gdy w katalogu docelowym lezy juz kopia o tym
        samym rozmiarze i czasie modyfikacji albo gdy zrodlo i cel to ten sam plik.
        """
        if cancel is not None:
            cancel.raise_if_cancelled()

        source_path = self.local_path(item)
        info = self._source_stat(source_path, item)
        size = int(info.st_size)
        target = self._prepare_target(destination, item)

        if target == source_path:
            return FetchedFile(
                item=item,
                path=source_path,
                size=size,
                sha256=self._digest(source_path, item),
            )

        if self._already_copied(target, info):
            log.debug("local_dir.fetch_reused", source_id=self.source_id)
        else:
            ensure_space_for(destination, size)
            self._copy(source_path, target, item)

        if cancel is not None:
            cancel.raise_if_cancelled()

        try:
            copied_size = int(target.stat().st_size)
        except OSError as exc:
            raise DownloadError(
                f"Nie udało się odczytać kopii pliku {item.logical_path}.",
                details={"source_id": self.source_id, "external_id": item.external_id},
                cause=exc,
            ) from exc
        return FetchedFile(
            item=item,
            path=target,
            size=copied_size,
            sha256=self._digest(target, item),
        )

    def _source_stat(self, source_path: Path, item: SourceItem) -> os.stat_result:
        try:
            info = source_path.stat()
        except FileNotFoundError as exc:
            raise DownloadError(
                f"Plik {item.logical_path} nie istnieje już w katalogu źródłowym.",
                details={"source_id": self.source_id, "external_id": item.external_id},
                cause=exc,
            ) from exc
        except PermissionError as exc:
            raise DownloadError(
                f"Brak uprawnień do odczytu pliku {item.logical_path}.",
                details={"source_id": self.source_id, "external_id": item.external_id},
                cause=exc,
            ) from exc
        except OSError as exc:
            raise DownloadError(
                f"Nie udało się odczytać pliku {item.logical_path}: {type(exc).__name__}.",
                details={"source_id": self.source_id, "external_id": item.external_id},
                cause=exc,
            ) from exc
        if not stat.S_ISREG(info.st_mode):
            raise DownloadError(
                f"Ścieżka {item.logical_path} nie wskazuje zwykłego pliku.",
                details={"source_id": self.source_id, "external_id": item.external_id},
            )
        return info

    def _prepare_target(self, destination: Path, item: SourceItem) -> Path:
        """Przygotowuje katalog docelowy i zwraca sciezke pliku wynikowego."""
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise TemporaryStorageError(
                f"Nie udało się przygotować katalogu roboczego {destination}.",
                details={"source_id": self.source_id},
                cause=exc,
            ) from exc
        name = Path(item.name).name or FALLBACK_FILE_NAME
        return destination / name

    def _already_copied(self, target: Path, source_info: os.stat_result) -> bool:
        """Sprawdza, czy w celu lezy juz aktualna kopia pliku zrodlowego."""
        try:
            target_info = target.stat()
        except OSError:
            return False
        return target_info.st_size == source_info.st_size and int(target_info.st_mtime) == int(
            source_info.st_mtime
        )

    def _copy(self, source_path: Path, target: Path, item: SourceItem) -> None:
        try:
            shutil.copy2(source_path, target)
        except shutil.SameFileError:
            return
        except FileNotFoundError as exc:
            raise DownloadError(
                f"Plik {item.logical_path} zniknął z katalogu źródłowego w trakcie kopiowania.",
                details={"source_id": self.source_id, "external_id": item.external_id},
                cause=exc,
            ) from exc
        except PermissionError as exc:
            raise DownloadError(
                f"Brak uprawnień do skopiowania pliku {item.logical_path}.",
                details={"source_id": self.source_id, "external_id": item.external_id},
                cause=exc,
            ) from exc
        except OSError as exc:
            raise DownloadError(
                f"Nie udało się skopiować pliku {item.logical_path}: {type(exc).__name__}.",
                details={"source_id": self.source_id, "external_id": item.external_id},
                cause=exc,
            ) from exc

    def _digest(self, path: Path, item: SourceItem) -> str:
        try:
            return sha256_of_file(path)
        except FileNotFoundError as exc:
            raise DownloadError(
                f"Plik {item.logical_path} zniknął przed policzeniem sumy kontrolnej.",
                details={"source_id": self.source_id, "external_id": item.external_id},
                cause=exc,
            ) from exc
        except OSError as exc:
            raise DownloadError(
                f"Nie udało się policzyć sumy kontrolnej pliku {item.logical_path}: "
                f"{type(exc).__name__}.",
                details={"source_id": self.source_id, "external_id": item.external_id},
                cause=exc,
            ) from exc


__all__ = [
    "CANCEL_CHECK_INTERVAL",
    "MAX_TOP_LEVEL_PROBE",
    "SYSTEM_DIRECTORY_NAMES",
    "LocalDirectoryConnector",
]
