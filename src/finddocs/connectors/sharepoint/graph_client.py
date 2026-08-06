"""Klient HTTP dla Microsoft Graph z ponawianiem prob i kontrola polityki sieciowej.

Klasa :class:`GraphClient` owija ``httpx.Client`` i dodaje:

1. sprawdzenie kazdego adresu (takze po przekierowaniu) wzgledem polityki sieciowej,
2. naglowek autoryzacji pobierany z :class:`GraphAuthenticator`,
3. ponawianie prob z rosnacym opoznieniem dla kodow 429 oraz 5xx,
4. stronicowanie odpowiedzi Graph i strumieniowe pobieranie plikow.

Naglowki zapytan nigdy nie trafiaja do logow, a adresy sa zapisywane bez czesci
z parametrami, poniewaz moga zawierac jednorazowe tokeny pobrania.
"""

from __future__ import annotations

import datetime as _dt
import json
import time
from collections.abc import Callable, Iterator
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from finddocs.config import SharePointSourceSettings
from finddocs.connectors.sharepoint.auth import GraphAuthenticator
from finddocs.errors import (
    AuthenticationError,
    ConnectorError,
    DownloadError,
    RateLimitedError,
    TransientConnectorError,
)
from finddocs.logging_setup import get_logger
from finddocs.security.network import EgressCategory, NetworkPolicy, get_policy
from finddocs.security.redaction import redact_text, safe_url
from finddocs.types import CancellationToken

log = get_logger(__name__)

#: Kody odpowiedzi, przy ktorych ma sens ponowienie zapytania.
RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

#: Rozmiar bloku przy pobieraniu strumieniowym.
DOWNLOAD_BLOCK_BYTES = 1024 * 1024

#: Podstawa i gorne ograniczenie wykladniczego opoznienia miedzy probami.
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 60.0

#: Gorne ograniczenie czasu oczekiwania podanego przez naglowek Retry-After.
RETRY_AFTER_MAX_SECONDS = 300.0

#: Deterministyczne przesuniecia opoznienia. Zastepuja losowy jitter, zeby
#: zachowanie klienta bylo powtarzalne w testach.
JITTER_STEPS: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75)

#: Znaki dozwolone w pojedynczym segmencie sciezki, poza znakami niezastrzezonymi.
_SEGMENT_SAFE = ",!$&'()*+;=:@"


def quote_segment(value: str) -> str:
    """Koduje identyfikator zasobu jako pojedynczy segment sciezki URL."""
    cleaned = value.strip().strip("/")
    if not cleaned:
        raise ConnectorError("Brak identyfikatora zasobu SharePoint w adresie zapytania.")
    return quote(cleaned, safe=_SEGMENT_SAFE)


def quote_path(value: str) -> str:
    """Koduje sciezke wzgledna zachowujac separatory katalogow."""
    return quote(value, safe=f"/{_SEGMENT_SAFE}")


class GraphClient:
    """Cienki klient Microsoft Graph przygotowany pod testy z ``httpx.MockTransport``."""

    def __init__(
        self,
        authenticator: GraphAuthenticator,
        settings: SharePointSourceSettings,
        policy: NetworkPolicy | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._auth = authenticator
        self._settings = settings
        self._policy = policy if policy is not None else get_policy()
        self._sleep = sleep if sleep is not None else time.sleep
        self._client = httpx.Client(
            timeout=httpx.Timeout(settings.request_timeout_seconds),
            follow_redirects=True,
            transport=transport,
            event_hooks={"request": [self._enforce_policy]},
        )
        self.last_next_link: str | None = None
        """Ostatni odsyłacz nextLink zwrócony przez stronicowana odpowiedź."""

    # --- adresy i polityka ------------------------------------------------

    def build_url(self, url_or_path: str) -> str:
        """Buduje pelny adres z podanej sciezki wzglednej albo zwraca gotowy adres."""
        candidate = url_or_path.strip()
        if not candidate:
            raise ConnectorError("Puste zapytanie do Microsoft Graph.")
        if candidate.lower().startswith(("http://", "https://")):
            return candidate
        base = (self._settings.graph_endpoint or "").strip().rstrip("/")
        if not base:
            raise ConnectorError(
                "Nie skonfigurowano adresu uslugi Microsoft Graph (graph_endpoint)."
            )
        return f"{base}/{candidate.lstrip('/')}"

    def _enforce_policy(self, request: httpx.Request) -> None:
        """Hook httpx: sprawdza kazde zapytanie, takze powstale po przekierowaniu."""
        self._policy.check(str(request.url), EgressCategory.MICROSOFT_GRAPH)

    # --- zapytania --------------------------------------------------------

    def request(self, method: str, url_or_path: str, **kwargs: Any) -> httpx.Response:
        """Wykonuje zapytanie do Graph z ponawianiem prob i odswiezeniem tokenu.

        Odpowiedz 404 jest zwracana wolajacemu, poniewaz brak zasobu bywa
        poprawnym wynikiem. Kod 403 konczy sie bledem o brakujacych uprawnieniach.
        """
        url = self.build_url(url_or_path)
        self._policy.check(url, EgressCategory.MICROSOFT_GRAPH)
        extra_headers = dict(kwargs.pop("headers", None) or {})
        timeout = kwargs.pop("timeout", self._settings.request_timeout_seconds)
        max_attempts = max(1, int(self._settings.max_retries))

        token_refreshed = False
        force_refresh = False
        attempt = 0
        last_status: int | None = None
        last_retry_after: float | None = None
        last_reason = "Nie udało się wykonać zapytania do Microsoft Graph."

        while attempt < max_attempts:
            attempt += 1
            headers = self._headers(extra_headers, force_refresh=force_refresh)
            force_refresh = False
            try:
                response = self._client.request(
                    method, url, headers=headers, timeout=timeout, **kwargs
                )
            except httpx.HTTPError as exc:
                last_status = None
                last_reason = (
                    "Brak polaczenia z usluga Microsoft Graph "
                    f"({type(exc).__name__}). Sprawdź sieć firmowa i ustawienia proxy."
                )
                log.warning(
                    "graph.request_failed",
                    method=method,
                    url=safe_url(url),
                    attempt=attempt,
                    reason=type(exc).__name__,
                )
                if attempt < max_attempts:
                    self._sleep(self._backoff_seconds(attempt))
                    continue
                break

            status = response.status_code
            log.debug("graph.response", method=method, url=safe_url(url), status=status)

            if status == 401:
                detail = self._error_message(response)
                response.close()
                if token_refreshed:
                    raise AuthenticationError(
                        "Microsoft Graph odrzucił token dostępu. Zaloguj się ponownie "
                        f"do źródła SharePoint. Szczegóły: {detail}"
                    )
                token_refreshed = True
                force_refresh = True
                # Odswiezenie tokenu nie zuzywa proby ponowienia.
                attempt -= 1
                continue

            if status == 403:
                detail = self._error_message(response)
                response.close()
                raise ConnectorError(
                    "Brak uprawnień do wskazanego zasobu SharePoint. Konto nie ma "
                    "przyznanych uprawnien Files.Read.All albo Sites.Read.All, albo "
                    f"administrator nie wyrazil na nie zgody. Szczegóły: {detail}"
                )

            if status in RETRYABLE_STATUSES:
                last_status = status
                last_retry_after = self._retry_after_seconds(response)
                last_reason = self._error_message(response)
                response.close()
                if attempt < max_attempts:
                    delay = (
                        last_retry_after
                        if last_retry_after is not None
                        else self._backoff_seconds(attempt)
                    )
                    log.info(
                        "graph.retry",
                        method=method,
                        url=safe_url(url),
                        status=status,
                        attempt=attempt,
                        delay=delay,
                    )
                    self._sleep(delay)
                    continue
                break

            return response

        if last_status == 429:
            raise RateLimitedError(
                "Microsoft Graph ograniczyl liczbe zapytan i limit nie zostal zwolniony "
                f"po {max_attempts} próbach. Spróbuj ponownie za chwilę.",
                retry_after=last_retry_after,
                details={"url": safe_url(url)},
            )
        raise TransientConnectorError(
            f"Zapytanie do Microsoft Graph nie powiodło się po {max_attempts} próbach. "
            f"{last_reason}",
            details={"url": safe_url(url), "status": last_status},
        )

    def get_json(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Wykonuje GET i zwraca odpowiedz w postaci slownika."""
        response = self.request("GET", path_or_url, params=params)
        return self._json_body(response)

    def iter_paged(
        self,
        path_or_url: str,
        params: dict[str, Any] | None = None,
        cancel: CancellationToken | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Iteruje po elementach kolekcji, podazajac za odsylaczem ``@odata.nextLink``.

        Przed oddaniem elementow strony atrybut :attr:`last_next_link` wskazuje
        adres kolejnej strony, wiec wolajacy moze zapisac go jako punkt wznowienia.
        Po ostatniej stronie atrybut wraca do wartosci ``None``.
        """
        query: dict[str, Any] | None = dict(params) if params else {}
        if query is not None and "$top" not in query:
            query["$top"] = max(1, int(self._settings.page_size))
        url: str | None = path_or_url
        while url:
            if cancel is not None:
                cancel.raise_if_cancelled()
            payload = self.get_json(url, params=query)
            query = None  # odsylacz nextLink zawiera juz komplet parametrow
            raw_next = payload.get("@odata.nextLink")
            self.last_next_link = raw_next if isinstance(raw_next, str) and raw_next else None
            values = payload.get("value")
            if isinstance(values, list):
                for entry in values:
                    if isinstance(entry, dict):
                        yield entry
            url = self.last_next_link
        self.last_next_link = None

    # --- pobieranie plikow ------------------------------------------------

    def download(
        self,
        url_or_path: str,
        destination: Path,
        expected_size: int | None = None,
        cancel: CancellationToken | None = None,
    ) -> int:
        """Pobiera zasob strumieniowo do wskazanego pliku i zwraca liczbe bajtow.

        Dane trafiaja najpierw do pliku tymczasowego, a dopiero kompletny plik jest
        przenoszony na miejsce docelowe. Anulowanie jest sprawdzane miedzy blokami.
        """
        url = self.build_url(url_or_path)
        self._policy.check(url, EgressCategory.MICROSOFT_GRAPH)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = destination.with_name(destination.name + ".part")
        max_attempts = max(1, int(self._settings.max_retries))
        timeout = self._settings.request_timeout_seconds

        token_refreshed = False
        force_refresh = False
        attempt = 0
        last_reason = "Nie udało się pobrać pliku ze źródła."

        try:
            while attempt < max_attempts:
                attempt += 1
                headers = self._headers({"Accept": "*/*"}, force_refresh=force_refresh)
                force_refresh = False
                try:
                    with self._client.stream(
                        "GET", url, headers=headers, timeout=timeout
                    ) as response:
                        status = response.status_code
                        if status == 401:
                            if token_refreshed:
                                raise AuthenticationError(
                                    "Microsoft Graph odrzucil token dostepu przy pobieraniu "
                                    "pliku. Zaloguj się ponownie do źródła SharePoint."
                                )
                            token_refreshed = True
                            force_refresh = True
                            attempt -= 1
                            continue
                        if status == 403:
                            raise DownloadError(
                                "Brak uprawnień do pobrania pliku z SharePoint. "
                                f"Szczegóły: {self._error_message(response)}"
                            )
                        if status in RETRYABLE_STATUSES:
                            last_reason = self._error_message(response)
                            retry_after = self._retry_after_seconds(response)
                            if attempt < max_attempts:
                                self._sleep(
                                    retry_after
                                    if retry_after is not None
                                    else self._backoff_seconds(attempt)
                                )
                                continue
                            break
                        if not response.is_success:
                            raise DownloadError(
                                f"Serwer odrzucił pobranie pliku (kod {status}). "
                                f"Szczegóły: {self._error_message(response)}"
                            )
                        written = self._write_stream(response, temp_path, cancel)
                except httpx.HTTPError as exc:
                    last_reason = (
                        f"Połączenie zostało przerwane ({type(exc).__name__}). "
                        "Sprawdz siec firmowa i ustawienia proxy."
                    )
                    log.warning(
                        "graph.download_failed",
                        url=safe_url(url),
                        attempt=attempt,
                        reason=type(exc).__name__,
                    )
                    if attempt < max_attempts:
                        self._sleep(self._backoff_seconds(attempt))
                        continue
                    break
                except OSError as exc:
                    raise DownloadError(
                        "Nie udało się zapisać pobieranego pliku w przestrzeni tymczasowej.",
                        cause=exc,
                    ) from exc

                if expected_size is not None and expected_size >= 0 and written != expected_size:
                    raise DownloadError(
                        "Pobrany plik ma inny rozmiar niz zapowiadaly metadane "
                        f"({written} zamiast {expected_size} bajtow). "
                        "Dokument mogl zmienic sie w trakcie pobierania."
                    )
                temp_path.replace(destination)
                log.debug("graph.download_ok", url=safe_url(url), bytes=written)
                return written

            raise DownloadError(
                f"Nie udało się pobrać pliku po {max_attempts} próbach. {last_reason}",
                details={"url": safe_url(url)},
            )
        finally:
            temp_path.unlink(missing_ok=True)

    def _write_stream(
        self,
        response: httpx.Response,
        temp_path: Path,
        cancel: CancellationToken | None,
    ) -> int:
        """Zapisuje strumien odpowiedzi do pliku tymczasowego blokami po 1 MB."""
        written = 0
        with temp_path.open("wb") as handle:
            for block in response.iter_bytes(chunk_size=DOWNLOAD_BLOCK_BYTES):
                if cancel is not None:
                    cancel.raise_if_cancelled()
                handle.write(block)
                written += len(block)
        return written

    # --- zasoby SharePoint ------------------------------------------------

    def resolve_site(self, site_url: str) -> dict[str, Any]:
        """Zamienia adres witryny na obiekt site z Microsoft Graph."""
        candidate = site_url.strip()
        if not candidate:
            raise ConnectorError("Nie podano adresu witryny SharePoint.")
        if "://" not in candidate:
            candidate = f"https://{candidate}"
        parsed = urlparse(candidate)
        host = (parsed.hostname or "").strip()
        if not host:
            raise ConnectorError(
                f"Adres witryny SharePoint jest nieprawidłowy: {safe_url(site_url)}. "
                "Poprawny adres wyglada tak: https://firma.sharepoint.com/sites/Nazwa."
            )
        path = quote_path(parsed.path.rstrip("/"))
        resource = f"/sites/{host}:{path}" if path else f"/sites/{host}"
        response = self.request("GET", resource)
        if response.status_code == 404:
            raise ConnectorError(
                f"Nie znaleziono witryny SharePoint pod adresem {safe_url(site_url)}. "
                "Sprawdz, czy adres jest poprawny i czy masz do niej dostep."
            )
        return self._json_body(response)

    def list_drives(self, site_id: str) -> list[dict[str, Any]]:
        """Zwraca biblioteki dokumentow dostepne w witrynie."""
        return list(self.iter_paged(f"/sites/{quote_segment(site_id)}/drives"))

    def resolve_drive(self, site_id: str, drive_name: str) -> dict[str, Any]:
        """Znajduje biblioteke po nazwie. Pusta nazwa oznacza biblioteke domyslna."""
        wanted = drive_name.strip()
        if not wanted:
            return self.get_json(f"/sites/{quote_segment(site_id)}/drive")
        folded = wanted.casefold()
        drives = self.list_drives(site_id)
        for drive in drives:
            if str(drive.get("name") or "").casefold() == folded:
                return drive
        for drive in drives:
            web_url = str(drive.get("webUrl") or "")
            if web_url.rstrip("/").rsplit("/", 1)[-1].casefold() == folded:
                return drive
        available = ", ".join(sorted(str(d.get("name") or "?") for d in drives)) or "brak"
        raise ConnectorError(
            f"Nie znaleziono biblioteki dokumentów '{wanted}' we wskazanej witrynie. "
            f"Dostępne biblioteki: {available}."
        )

    def get_drive(self, drive_id: str) -> dict[str, Any]:
        """Zwraca opis biblioteki dokumentow o podanym identyfikatorze."""
        return self.get_json(f"/drives/{quote_segment(drive_id)}")

    def list_children(
        self,
        drive_id: str,
        item_path_or_id: str = "",
        params: dict[str, Any] | None = None,
        cancel: CancellationToken | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Iteruje po zawartosci katalogu, strona po stronie.

        Pusta wartosc oznacza korzen biblioteki, wartosc zaczynajaca sie od ukosnika
        jest traktowana jako sciezka, a kazda inna jako identyfikator elementu.
        """
        drive = quote_segment(drive_id)
        reference = item_path_or_id.strip()
        if not reference or reference == "/":
            resource = f"/drives/{drive}/root/children"
        elif reference.startswith("/"):
            resource = f"/drives/{drive}/root:{quote_path(reference.rstrip('/'))}:/children"
        else:
            resource = f"/drives/{drive}/items/{quote_segment(reference)}/children"
        return self.iter_paged(resource, params=params, cancel=cancel)

    def get_item_by_path(self, drive_id: str, path: str) -> dict[str, Any]:
        """Zwraca element biblioteki wskazany sciezka wzgledna wzgledem korzenia."""
        drive = quote_segment(drive_id)
        relative = path.strip().strip("/")
        if not relative:
            return self.get_json(f"/drives/{drive}/root")
        response = self.request("GET", f"/drives/{drive}/root:/{quote_path(relative)}")
        if response.status_code == 404:
            raise ConnectorError(
                f"Nie znaleziono katalogu '{relative}' w bibliotece dokumentów. "
                "Sprawdź ścieżkę katalogu startowego w ustawieniach źródła."
            )
        return self._json_body(response)

    def delta(
        self, drive_id: str, token: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Pobiera zmiany w bibliotece. Zwraca liste zmian i nowy odsylacz deltaLink."""
        url: str | None
        params: dict[str, Any] | None
        if token and token.strip().lower().startswith("http"):
            url, params = token.strip(), None
        else:
            url = f"/drives/{quote_segment(drive_id)}/root/delta"
            params = {"token": token} if token else None
        changes: list[dict[str, Any]] = []
        delta_link: str | None = None
        while url:
            payload = self.get_json(url, params=params)
            params = None
            values = payload.get("value")
            if isinstance(values, list):
                changes.extend(entry for entry in values if isinstance(entry, dict))
            raw_delta = payload.get("@odata.deltaLink")
            if isinstance(raw_delta, str) and raw_delta:
                delta_link = raw_delta
            raw_next = payload.get("@odata.nextLink")
            url = raw_next if isinstance(raw_next, str) and raw_next else None
        return changes, delta_link

    # --- pomocnicze -------------------------------------------------------

    def close(self) -> None:
        """Zamyka sesje HTTP."""
        self._client.close()

    def _headers(self, extra: dict[str, str], *, force_refresh: bool) -> dict[str, str]:
        """Buduje naglowki zapytania. Naglowek autoryzacji nie jest nigdzie zapisywany."""
        token = self._auth.get_token(force_refresh=force_refresh)
        headers: dict[str, str] = {"Accept": "application/json"}
        headers.update(extra)
        headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def _backoff_seconds(attempt: int) -> float:
        """Wykladnicze opoznienie z deterministycznym przesunieciem, bez losowosci."""
        base = BACKOFF_BASE_SECONDS * float(2 ** max(0, attempt - 1))
        jitter = JITTER_STEPS[(attempt - 1) % len(JITTER_STEPS)]
        return min(BACKOFF_MAX_SECONDS, base + jitter)

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        """Odczytuje naglowek Retry-After w postaci liczby sekund albo daty."""
        raw = response.headers.get("Retry-After")
        if not raw:
            return None
        value = raw.strip()
        try:
            return min(RETRY_AFTER_MAX_SECONDS, max(0.0, float(value)))
        except ValueError:
            pass
        try:
            moment = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        now = _dt.datetime.now(tz=moment.tzinfo)
        delta = float((moment - now).total_seconds())
        return min(RETRY_AFTER_MAX_SECONDS, max(0.0, delta))

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        """Krotki opis bledu z tresci odpowiedzi Graph, bez danych wrazliwych."""
        try:
            body = response.read()
        except (httpx.HTTPError, RuntimeError):
            return f"kod odpowiedzi {response.status_code}"
        try:
            payload = json.loads(body.decode("utf-8", errors="replace")) if body else None
        except ValueError:
            return f"kod odpowiedzi {response.status_code}"
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message") or error.get("code") or ""
                if str(message).strip():
                    return redact_text(str(message).strip())
        return f"kod odpowiedzi {response.status_code}"

    def _json_body(self, response: httpx.Response) -> dict[str, Any]:
        """Zamienia odpowiedz na slownik albo rzuca blad z czytelnym komunikatem."""
        if not response.is_success:
            raise ConnectorError(
                f"Microsoft Graph zwrócił błąd {response.status_code}. "
                f"Szczegóły: {self._error_message(response)}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ConnectorError(
                "Odpowiedź Microsoft Graph nie jest poprawnym dokumentem JSON.",
                cause=exc,
            ) from exc
        if not isinstance(payload, dict):
            raise ConnectorError("Odpowiedź Microsoft Graph ma nieoczekiwana strukturę.")
        return payload


__all__ = [
    "BACKOFF_MAX_SECONDS",
    "DOWNLOAD_BLOCK_BYTES",
    "RETRYABLE_STATUSES",
    "GraphClient",
    "quote_path",
    "quote_segment",
]
