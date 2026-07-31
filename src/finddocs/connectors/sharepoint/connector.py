"""Konektor biblioteki dokumentow SharePoint oparty o Microsoft Graph.

Konektor wylicza pliki leniwie, katalog po katalogu, korzystajac ze stronicowania
Graph. Dokumenty sa identyfikowane trwalym identyfikatorem ``driveItem id``, a nie
nazwa pliku, wiec zmiana nazwy albo przeniesienie nie powoduje ponownego
indeksowania calej tresci. Pobierany jest zawsze pojedynczy plik, nigdy cala
biblioteka naraz.
"""

from __future__ import annotations

import datetime as _dt
import fnmatch
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

from finddocs.config import SharePointSourceSettings, SourceConfig
from finddocs.connectors.base import (
    ConnectionStatus,
    ScanCursor,
    SourceConnector,
    ensure_space_for,
    sha256_of_file,
)
from finddocs.connectors.sharepoint.graph_client import GraphClient, quote_segment
from finddocs.errors import (
    AuthenticationError,
    ConnectorError,
    FindDocsError,
    NetworkPolicyError,
    RateLimitedError,
    TransientConnectorError,
)
from finddocs.logging_setup import get_logger
from finddocs.types import CancellationToken, FetchedFile, SourceItem, SourceKind

log = get_logger(__name__)

#: Znaki niedozwolone w nazwie pliku na Windows.
INVALID_FILENAME_CHARS = '<>:"/\\|?*'

#: Maksymalna dlugosc nazwy pliku zapisywanego w przestrzeni tymczasowej.
MAX_FILENAME_LENGTH = 120

#: Nazwy zarezerwowane przez Windows, ktorych nie wolno uzyc jako nazwy pliku.
RESERVED_WINDOWS_NAMES: frozenset[str] = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

#: Ile elementow pierwszego poziomu liczymy w tescie polaczenia.
TEST_CONNECTION_LIMIT = 500

#: Znacznik konczacy czesc adresowa w polu ``parentReference.path``.
_ROOT_MARKER = "root:"

_FRACTION_RE = re.compile(r"^(?P<head>.*\.\d{6})\d+(?P<tail>.*)$")


def safe_filename(name: str, *, max_length: int = MAX_FILENAME_LENGTH) -> str:
    """Zamienia nazwe z SharePoint na nazwe bezpieczna dla systemu plikow Windows.

    Usuwa znaki niedozwolone i sterujace, przycina dlugosc zachowujac rozszerzenie
    oraz omija nazwy zarezerwowane. Polskie znaki diakrytyczne sa zachowywane.
    """
    cleaned = "".join(
        "_" if (ch in INVALID_FILENAME_CHARS or ord(ch) < 32 or ord(ch) == 127) else ch
        for ch in name
    ).strip()
    cleaned = cleaned.rstrip(" .")
    if not cleaned:
        return "dokument"
    suffix = PurePosixPath(cleaned).suffix
    if len(suffix) > 24:
        suffix = ""
    stem = cleaned[: len(cleaned) - len(suffix)] if suffix else cleaned
    if stem.rstrip(" .").upper() in RESERVED_WINDOWS_NAMES:
        stem = f"_{stem}"
    limit = max(1, max_length - len(suffix))
    if len(stem) > limit:
        stem = stem[:limit]
    stem = stem.rstrip(" .")
    if not stem:
        stem = "dokument"
    return f"{stem}{suffix}"


def normalize_extensions(values: Sequence[str] | None) -> frozenset[str]:
    """Sprowadza liste rozszerzen do postaci ``.ext`` pisanej malymi literami."""
    result: set[str] = set()
    for raw in values or ():
        candidate = raw.strip().lower()
        if not candidate:
            continue
        result.add(candidate if candidate.startswith(".") else f".{candidate}")
    return frozenset(result)


def logical_path_from_reference(raw: str) -> str:
    """Wycina czytelna sciezke katalogu z pola ``parentReference.path``.

    Graph zwraca wartosci w rodzaju ``/drive/root:/Umowy/2024`` albo
    ``/drives/<id>/root:/Umowy``. Interesuje nas czesc po znaczniku ``root:``.
    """
    if not raw:
        return ""
    index = raw.find(_ROOT_MARKER)
    tail = raw[index + len(_ROOT_MARKER) :] if index >= 0 else raw
    return unquote(tail).strip("/")


def join_logical_path(parent: str, name: str) -> str:
    """Laczy sciezke katalogu z nazwa elementu, separatorem jest ukosnik."""
    cleaned_parent = parent.strip("/")
    return f"{cleaned_parent}/{name}" if cleaned_parent else name


def parse_graph_datetime(value: Any) -> _dt.datetime | None:
    """Zamienia znacznik czasu z Graph na obiekt ``datetime`` ze strefa UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text[-1] in {"Z", "z"}:
        text = f"{text[:-1]}+00:00"
    match = _FRACTION_RE.match(text)
    if match:
        text = f"{match.group('head')}{match.group('tail')}"
    try:
        return _dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def person_name(value: Any) -> str | None:
    """Wyciaga nazwe osoby z pola ``createdBy`` albo ``lastModifiedBy``."""
    if not isinstance(value, dict):
        return None
    user = value.get("user")
    if isinstance(user, dict):
        for key in ("displayName", "email", "userPrincipalName"):
            candidate = user.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    candidate = value.get("displayName")
    return candidate.strip() if isinstance(candidate, str) and candidate.strip() else None


def parent_url_from(web_url: str | None) -> str | None:
    """Buduje adres katalogu nadrzednego przez odciecie ostatniego segmentu adresu."""
    if not web_url:
        return None
    base, separator, _last = web_url.rstrip("/").rpartition("/")
    return base if separator and base else None


@dataclass(slots=True)
class _Folder:
    """Katalog oczekujacy na przejscie podczas enumeracji."""

    item_id: str
    logical_path: str
    web_url: str


class SharePointConnector(SourceConnector):
    """Zrodlo dokumentow oparte o biblioteke dokumentow SharePoint."""

    kind = SourceKind.SHAREPOINT

    def __init__(
        self,
        source_id: str,
        label: str,
        settings: SharePointSourceSettings,
        client: GraphClient,
        *,
        include_extensions: Sequence[str] | None = None,
        exclude_extensions: Sequence[str] | None = None,
        exclude_globs: Sequence[str] | None = None,
        max_file_size_mb: int = 512,
    ) -> None:
        self.source_id = source_id
        self.label = label
        self._settings = settings
        self._client = client
        self._include = normalize_extensions(include_extensions)
        self._exclude = normalize_extensions(exclude_extensions)
        self._exclude_globs = [g.strip().lower() for g in (exclude_globs or ()) if g.strip()]
        self._max_bytes = max(0, int(max_file_size_mb)) * 1024 * 1024
        self._cursor = ScanCursor()
        self._site_id = settings.site_id.strip()
        self._drive_id = settings.drive_id.strip()
        self._site_name = ""
        self._site_web_url = settings.site_url.strip()
        self._drive_name = settings.drive_name.strip()
        self._drive_web_url = ""

    @classmethod
    def from_config(cls, source: SourceConfig, client: GraphClient) -> SharePointConnector:
        """Tworzy konektor na podstawie wpisu konfiguracji zrodla."""
        return cls(
            source.source_id,
            source.label,
            source.sharepoint,
            client,
            include_extensions=source.include_extensions,
            exclude_extensions=source.exclude_extensions,
            exclude_globs=source.exclude_globs,
            max_file_size_mb=source.max_file_size_mb,
        )

    # --- rozwiazywanie zasobow -------------------------------------------

    def ensure_resolved(self) -> None:
        """Ustala identyfikatory witryny i biblioteki, gdy w ustawieniach sa same nazwy."""
        if self._site_id and self._drive_id and self._drive_name:
            return
        if not self._site_id:
            if not self._settings.site_url.strip():
                raise ConnectorError(
                    "Źródło SharePoint nie ma wskazanej witryny. Podaj adres witryny "
                    "w rodzaju https://firma.sharepoint.com/sites/Nazwa."
                )
            site = self._client.resolve_site(self._settings.site_url)
            self._site_id = str(site.get("id") or "").strip()
            if not self._site_id:
                raise ConnectorError("Microsoft Graph nie zwrócił identyfikatora witryny.")
            self._site_name = str(site.get("displayName") or site.get("name") or "").strip()
            self._site_web_url = str(site.get("webUrl") or self._settings.site_url).strip()
        if not self._drive_id:
            drive = self._client.resolve_drive(self._site_id, self._settings.drive_name)
            self._drive_id = str(drive.get("id") or "").strip()
            if not self._drive_id:
                raise ConnectorError(
                    "Microsoft Graph nie zwrócił identyfikatora biblioteki dokumentów."
                )
            self._drive_name = str(drive.get("name") or self._settings.drive_name).strip()
            self._drive_web_url = str(drive.get("webUrl") or "").strip()
        elif not self._drive_name:
            drive = self._client.get_drive(self._drive_id)
            self._drive_name = str(drive.get("name") or "").strip()
            self._drive_web_url = str(drive.get("webUrl") or "").strip()
        log.info(
            "sharepoint.resolved",
            source_id=self.source_id,
            site=self._site_name or self._site_id,
            library=self._drive_name,
        )

    # --- test polaczenia --------------------------------------------------

    def test_connection(self) -> ConnectionStatus:
        """Sprawdza dostep do witryny i biblioteki oraz liczy elementy pierwszego poziomu."""
        try:
            self.ensure_resolved()
            start = self._settings.folder_path.strip().strip("/")
            root = self._client.get_item_by_path(self._drive_id, start)
            root_id = str(root.get("id") or "").strip()
            if not root_id:
                raise ConnectorError(
                    "Microsoft Graph nie zwrócił identyfikatora katalogu startowego."
                )
            counted = 0
            truncated = False
            for _entry in self._client.list_children(self._drive_id, root_id):
                counted += 1
                if counted >= TEST_CONNECTION_LIMIT:
                    truncated = True
                    break
        except NetworkPolicyError as exc:
            return self._failure(
                "Polaczenia z Microsoft Graph sa zablokowane przez polityke sieciowa "
                f"aplikacji. {exc.user_message}",
                exc,
            )
        except AuthenticationError as exc:
            return self._failure(
                "Uwierzytelnienie wygasło albo zostało odrzucone. Zaloguj się ponownie "
                f"do źródła SharePoint. {exc.user_message}",
                exc,
            )
        except RateLimitedError as exc:
            return self._failure(
                f"Microsoft Graph chwilowo ogranicza liczbę zapytań. {exc.user_message}", exc
            )
        except TransientConnectorError as exc:
            return self._failure(
                "Brak polaczenia z SharePoint. Sprawdz siec firmowa, dostep do VPN "
                f"i ustawienia serwera proxy. {exc.user_message}",
                exc,
            )
        except ConnectorError as exc:
            return self._failure(exc.user_message, exc)
        except FindDocsError as exc:
            return self._failure(f"Nie udało się połączyć ze źródłem. {exc.user_message}", exc)

        site_label = self._site_name or self._site_web_url or self._site_id
        library_label = self._drive_name or "(biblioteka domyślna)"
        suffix = " lub więcej" if truncated else ""
        return ConnectionStatus(
            ok=True,
            message=(
                f"Połączono z witryna '{site_label}', biblioteka '{library_label}'. "
                f"Elementow na pierwszym poziomie: {counted}{suffix}."
            ),
            details={
                "witryna": site_label,
                "biblioteka": library_label,
                "elementow_pierwszego_poziomu": counted,
                "katalog_startowy": self._settings.folder_path.strip("/") or "(korzeń)",
                "konto": self._settings.tenant_id or "organizations",
            },
        )

    def _failure(self, message: str, exc: FindDocsError) -> ConnectionStatus:
        """Buduje negatywny wynik testu polaczenia i zapisuje zdarzenie diagnostyczne."""
        log.warning(
            "sharepoint.test_connection_failed",
            source_id=self.source_id,
            error_code=exc.code,
            error_type=type(exc).__name__,
        )
        return ConnectionStatus(ok=False, message=message, details={"kod_bledu": exc.code})

    # --- enumeracja -------------------------------------------------------

    def iter_items(
        self,
        *,
        cursor: ScanCursor | None = None,
        cancel: CancellationToken | None = None,
    ) -> Iterator[SourceItem]:
        """Przechodzi po strukturze katalogow i oddaje kolejne pliki."""
        self.ensure_resolved()
        self._cursor = ScanCursor(
            token=cursor.token if cursor is not None else None,
            visited=cursor.visited if cursor is not None else 0,
            complete=False,
        )
        start = self._settings.folder_path.strip().strip("/")
        root = self._client.get_item_by_path(self._drive_id, start)
        root_id = str(root.get("id") or "").strip()
        if not root_id:
            raise ConnectorError("Microsoft Graph nie zwrócił identyfikatora katalogu startowego.")
        pending: list[_Folder] = [
            _Folder(
                item_id=root_id,
                logical_path=start,
                web_url=str(root.get("webUrl") or self._drive_web_url),
            )
        ]

        while pending:
            folder = pending.pop()
            if cancel is not None:
                cancel.raise_if_cancelled()
            for entry in self._client.list_children(self._drive_id, folder.item_id, cancel=cancel):
                if cancel is not None:
                    cancel.raise_if_cancelled()
                self._cursor.token = self._client.last_next_link
                name = str(entry.get("name") or "").strip()
                if not name:
                    continue
                if isinstance(entry.get("folder"), dict):
                    if self._settings.recursive:
                        child_id = str(entry.get("id") or "").strip()
                        if child_id:
                            pending.append(
                                _Folder(
                                    item_id=child_id,
                                    logical_path=join_logical_path(folder.logical_path, name),
                                    web_url=str(entry.get("webUrl") or folder.web_url),
                                )
                            )
                    continue
                if not isinstance(entry.get("file"), dict):
                    # Elementy bez czesci "file", np. pakiety OneNote, nie sa plikami.
                    continue
                item = self._build_item(entry, folder)
                self._cursor.visited += 1
                reason = self._skip_reason(item)
                if reason is not None:
                    log.debug(
                        "sharepoint.item_skipped",
                        source_id=self.source_id,
                        external_id=item.external_id,
                        reason=reason,
                    )
                    continue
                yield item

        self._cursor.token = None
        self._cursor.complete = True

    def cursor(self) -> ScanCursor:
        """Biezaca pozycja enumeracji wraz z ostatnim odsylaczem nextLink."""
        return self._cursor

    def _build_item(self, entry: dict[str, Any], folder: _Folder) -> SourceItem:
        """Buduje opis pliku na podstawie obiektu ``driveItem``."""
        name = str(entry.get("name") or "").strip()
        parent = entry.get("parentReference")
        parent_path = ""
        if isinstance(parent, dict):
            parent_path = logical_path_from_reference(str(parent.get("path") or ""))
        if not parent_path:
            parent_path = folder.logical_path
        file_info = entry.get("file")
        file_info = file_info if isinstance(file_info, dict) else {}
        hashes = file_info.get("hashes")
        hashes = hashes if isinstance(hashes, dict) else {}
        content_hash: str | None = None
        for key in ("quickXorHash", "sha256Hash", "sha1Hash", "crc32Hash"):
            candidate = hashes.get(key)
            if isinstance(candidate, str) and candidate.strip():
                content_hash = candidate.strip()
                break
        etag = str(entry.get("eTag") or entry.get("cTag") or "").strip() or None
        raw_size = entry.get("size")
        size = int(raw_size) if isinstance(raw_size, int | float) else None
        web_url = str(entry.get("webUrl") or "").strip() or None
        mime_type = str(file_info.get("mimeType") or "").strip() or None
        return SourceItem(
            source_id=self.source_id,
            external_id=str(entry.get("id") or "").strip(),
            name=name,
            logical_path=join_logical_path(parent_path, name),
            size=size,
            modified_at=parse_graph_datetime(entry.get("lastModifiedDateTime")),
            created_at=parse_graph_datetime(entry.get("createdDateTime")),
            etag=etag,
            content_hash=content_hash,
            author=person_name(entry.get("createdBy")) or person_name(entry.get("lastModifiedBy")),
            mime_type=mime_type,
            web_url=web_url,
            parent_url=folder.web_url.strip() or parent_url_from(web_url),
            library=self._drive_name or None,
            is_folder=False,
            extra={"drive_id": self._drive_id, "site_id": self._site_id},
        )

    def _skip_reason(self, item: SourceItem) -> str | None:
        """Zwraca powod pominiecia pliku albo ``None``, gdy plik nalezy przetworzyc."""
        extension = item.extension
        if self._include and extension not in self._include:
            return "rozszerzenie spoza listy dozwolonych"
        if extension in self._exclude:
            return "rozszerzenie wykluczone"
        lowered_path = item.logical_path.lower()
        lowered_name = item.name.lower()
        for pattern in self._exclude_globs:
            if fnmatch.fnmatch(lowered_path, pattern) or fnmatch.fnmatch(lowered_name, pattern):
                return "dopasowanie do wzorca wykluczającego"
        if self._max_bytes and item.size is not None and item.size > self._max_bytes:
            return "plik przekracza dozwolony rozmiar"
        return None

    # --- pobieranie -------------------------------------------------------

    def fetch(
        self,
        item: SourceItem,
        destination: Path,
        *,
        cancel: CancellationToken | None = None,
    ) -> FetchedFile:
        """Pobiera pojedynczy dokument do wskazanego katalogu roboczego."""
        self.ensure_resolved()
        if not item.external_id:
            raise ConnectorError(
                f"Dokument '{item.name}' nie ma identyfikatora SharePoint, "
                "nie można go pobrać. Uruchom ponowne skanowanie źródła."
            )
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / safe_filename(item.name)
        expected = item.size if isinstance(item.size, int) and item.size > 0 else None
        ensure_space_for(destination, expected or 0)
        drive_id = str(item.extra.get("drive_id") or self._drive_id)
        path = f"/drives/{quote_segment(drive_id)}/items/{quote_segment(item.external_id)}/content"
        written = self._client.download(path, target, expected_size=expected, cancel=cancel)
        digest = sha256_of_file(target)
        log.info(
            "sharepoint.fetched",
            source_id=self.source_id,
            external_id=item.external_id,
            bytes=written,
        )
        return FetchedFile(item=item, path=target, size=written, sha256=digest)

    # --- adresy -----------------------------------------------------------

    def open_url(self, item: SourceItem) -> str | None:
        """Adres dokumentu w SharePoint."""
        return item.web_url or self._drive_web_url or self._site_web_url or None

    def folder_url(self, item: SourceItem) -> str | None:
        """Adres katalogu SharePoint, w ktorym lezy dokument."""
        return (
            item.parent_url
            or parent_url_from(item.web_url)
            or self._drive_web_url
            or self._site_web_url
            or None
        )

    def describe(self) -> dict[str, Any]:
        """Opis zrodla na potrzeby ekranu diagnostyki."""
        base = super().describe()
        base.update(
            {
                "witryna": self._site_web_url or self._site_id,
                "biblioteka": self._drive_name,
                "katalog_startowy": self._settings.folder_path.strip("/") or "(korzeń)",
                "rekurencyjnie": self._settings.recursive,
            }
        )
        return base

    def close(self) -> None:
        """Zamyka sesje HTTP klienta Graph."""
        self._client.close()


__all__ = [
    "INVALID_FILENAME_CHARS",
    "MAX_FILENAME_LENGTH",
    "RESERVED_WINDOWS_NAMES",
    "TEST_CONNECTION_LIMIT",
    "SharePointConnector",
    "join_logical_path",
    "logical_path_from_reference",
    "normalize_extensions",
    "parent_url_from",
    "parse_graph_datetime",
    "person_name",
    "safe_filename",
]
