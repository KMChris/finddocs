"""Testy integracyjne klienta Microsoft Graph na podstawionym transporcie HTTP.

Zaden test w tym module nie wychodzi do sieci. Warstwa HTTP jest zastapiona
przez ``httpx.MockTransport``, uwierzytelnienie przez atrape zwracajaca staly
token, a funkcja usypiania przez liste zapisujaca zadane opoznienia. Dzieki temu
mozna sprawdzic stronicowanie, ponawianie prob i obsluge bledow bez czekania.
"""

from __future__ import annotations

import datetime as _dt
import logging
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from finddocs.config import SharePointSourceSettings
from finddocs.connectors.sharepoint.connector import SharePointConnector
from finddocs.connectors.sharepoint.graph_client import GraphClient
from finddocs.errors import (
    AuthenticationError,
    ConnectorError,
    DownloadError,
    NetworkPolicyError,
    RateLimitedError,
    TransientConnectorError,
)
from finddocs.security.network import EgressCategory, NetworkPolicy

#: Token uzywany przez atrape autoryzacji. Nie pasuje do zadnego wzorca redakcji,
#: wiec gdyby wyciekl do logow, test to zauwazy.
TOKEN = "TAJNY-TOKEN-DOSTEPU-DO-GRAPH-1234567890"

#: Adres uslugi Graph uzywany w testach.
GRAPH = "https://graph.microsoft.com/v1.0"

DRIVE_ID = "drive-1"
ROOT_ID = "root-1"
FOLDER_ID = "folder-umowy"

Handler = Callable[[httpx.Request], httpx.Response]


class FakeAuthenticator:
    """Atrapa uwierzytelnienia: zwraca staly token i nie dotyka sieci ani MSAL."""

    def __init__(self, token: str = TOKEN) -> None:
        self.token = token
        self.refresh_flags: list[bool] = []

    def get_token(self, *, force_refresh: bool = False) -> str:
        self.refresh_flags.append(force_refresh)
        return self.token

    def acquire_token_silent(self, *, force_refresh: bool = False) -> str:
        self.refresh_flags.append(force_refresh)
        return self.token


def graph_policy() -> NetworkPolicy:
    """Polityka dopuszczajaca wylacznie ruch do Microsoft Graph."""
    return NetworkPolicy(enabled_categories={EgressCategory.MICROSOFT_GRAPH})


def graph_settings(**kwargs: object) -> SharePointSourceSettings:
    """Ustawienia zrodla SharePoint z rozwiazanymi identyfikatorami witryny i biblioteki."""
    settings = SharePointSourceSettings(
        tenant_id="tenant-testowy",
        client_id="klient-testowy",
        graph_endpoint=GRAPH,
        site_id="site-1",
        drive_id=DRIVE_ID,
        drive_name="Dokumenty",
        site_url="https://contoso.sharepoint.com/sites/Finanse",
        request_timeout_seconds=5.0,
        max_retries=4,
        page_size=2,
    )
    for name, value in kwargs.items():
        setattr(settings, name, value)
    return settings


def build_client(
    handler: Handler,
    *,
    settings: SharePointSourceSettings | None = None,
    sleeps: list[float] | None = None,
    authenticator: FakeAuthenticator | None = None,
) -> GraphClient:
    """Sklada klienta Graph z podstawionym transportem, autoryzacja i usypianiem."""
    return GraphClient(
        authenticator or FakeAuthenticator(),  # type: ignore[arg-type]
        settings or graph_settings(),
        graph_policy(),
        transport=httpx.MockTransport(handler),
        sleep=(sleeps if sleeps is not None else []).append,
    )


def json_response(status: int, payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(status, json=payload)


def error_body(code: str, message: str) -> dict[str, object]:
    return {"error": {"code": code, "message": message}}


# --- stronicowanie ---------------------------------------------------------------


def test_stronicowanie_po_next_link_przez_trzy_strony() -> None:
    strony = [
        {
            "value": [{"id": "1"}, {"id": "2"}],
            "@odata.nextLink": f"{GRAPH}/drives/{DRIVE_ID}/root/children?$skiptoken=abc",
        },
        {
            "value": [{"id": "3"}, {"id": "4"}],
            "@odata.nextLink": f"{GRAPH}/drives/{DRIVE_ID}/root/children?$skiptoken=def",
        },
        {"value": [{"id": "5"}]},
    ]
    zapytania: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        zapytania.append(request.url)
        return json_response(200, strony[len(zapytania) - 1])

    client = build_client(handler)
    elementy = list(client.iter_paged(f"/drives/{DRIVE_ID}/root/children"))

    assert [e["id"] for e in elementy] == ["1", "2", "3", "4", "5"]
    assert len(zapytania) == 3
    # Pierwsze zapytanie dostaje rozmiar strony z ustawien, kolejne ida za nextLink.
    assert zapytania[0].params["$top"] == "2"
    assert zapytania[1].params["$skiptoken"] == "abc"
    assert zapytania[2].params["$skiptoken"] == "def"
    assert client.last_next_link is None


def test_stronicowanie_przerwane_gdy_next_link_wskazuje_obcy_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(
            200,
            {"value": [{"id": "1"}], "@odata.nextLink": "https://zlosliwy.example.com/dane"},
        )

    client = build_client(handler)
    strumien = client.iter_paged(f"/drives/{DRIVE_ID}/root/children")

    assert next(strumien)["id"] == "1"
    with pytest.raises(NetworkPolicyError):
        next(strumien)


# --- enumeracja katalogow --------------------------------------------------------


def drive_item(
    item_id: str,
    name: str,
    *,
    parent_path: str,
    size: int = 1024,
    folder: bool = False,
) -> dict[str, object]:
    """Buduje obiekt driveItem w postaci zwracanej przez Microsoft Graph."""
    entry: dict[str, object] = {
        "id": item_id,
        "name": name,
        "size": size,
        "eTag": f'"{{{item_id.upper()}}},3"',
        "cTag": f'"c:{{{item_id.upper()}}},2"',
        "createdDateTime": "2024-03-01T08:15:00Z",
        "lastModifiedDateTime": "2024-05-12T11:30:45.1234567Z",
        "webUrl": f"https://contoso.sharepoint.com/sites/Finanse/Dokumenty/{name}",
        "createdBy": {"user": {"displayName": "Anna Kowalska"}},
        "lastModifiedBy": {"user": {"displayName": "Piotr Nowak"}},
        "parentReference": {"driveId": DRIVE_ID, "path": f"/drives/{DRIVE_ID}/root:{parent_path}"},
    }
    if folder:
        entry["folder"] = {"childCount": 1}
    else:
        entry["file"] = {"mimeType": "application/pdf", "hashes": {"quickXorHash": "SKROT123"}}
    return entry


def library_handler(request: httpx.Request) -> httpx.Response:
    """Odpowiada na zapytania o biblioteke z jednym katalogiem i dwoma plikami."""
    path = request.url.path
    if path == f"/v1.0/drives/{DRIVE_ID}/root":
        return json_response(
            200,
            {"id": ROOT_ID, "webUrl": "https://contoso.sharepoint.com/sites/Finanse/Dokumenty"},
        )
    if path == f"/v1.0/drives/{DRIVE_ID}/items/{ROOT_ID}/children":
        return json_response(
            200,
            {
                "value": [
                    drive_item(FOLDER_ID, "Umowy", parent_path="", folder=True),
                    drive_item("plik-1", "raport.pdf", parent_path="", size=2048),
                ]
            },
        )
    if path == f"/v1.0/drives/{DRIVE_ID}/items/{FOLDER_ID}/children":
        return json_response(
            200,
            {"value": [drive_item("plik-2", "umowa-2024.pdf", parent_path="/Umowy", size=4096)]},
        )
    return json_response(404, error_body("itemNotFound", f"Nie znaleziono {path}."))


def build_connector(handler: Handler = library_handler) -> SharePointConnector:
    return SharePointConnector(
        source_id="sharepoint",
        label="Biblioteka testowa",
        settings=graph_settings(),
        client=build_client(handler),
    )


def test_enumeracja_wchodzi_rekurencyjnie_w_katalogi() -> None:
    connector = build_connector()

    items = list(connector.iter_items())

    assert [i.logical_path for i in items] == ["raport.pdf", "Umowy/umowa-2024.pdf"]
    assert connector.cursor().complete is True
    assert connector.cursor().visited == 2


def test_budowa_source_item_z_drive_item() -> None:
    connector = build_connector()

    item = next(i for i in connector.iter_items() if i.name == "umowa-2024.pdf")

    assert item.external_id == "plik-2"
    assert item.logical_path == "Umowy/umowa-2024.pdf"
    assert item.etag == '"{PLIK-2},3"'
    assert item.size == 4096
    assert item.mime_type == "application/pdf"
    assert item.content_hash == "SKROT123"
    assert item.author == "Anna Kowalska"
    assert item.library == "Dokumenty"
    assert item.web_url == ("https://contoso.sharepoint.com/sites/Finanse/Dokumenty/umowa-2024.pdf")
    assert item.created_at == _dt.datetime(2024, 3, 1, 8, 15, tzinfo=_dt.UTC)
    assert item.modified_at == _dt.datetime(2024, 5, 12, 11, 30, 45, 123456, tzinfo=_dt.UTC)
    assert item.extra == {"drive_id": DRIVE_ID, "site_id": "site-1"}


def test_enumeracja_pomija_pozycje_bez_czesci_file() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/v1.0/drives/{DRIVE_ID}/root":
            return json_response(200, {"id": ROOT_ID, "webUrl": "https://contoso.sharepoint.com"})
        notatnik = {"id": "onenote-1", "name": "Notatnik", "package": {"type": "oneNote"}}
        return json_response(
            200, {"value": [notatnik, drive_item("plik-1", "raport.pdf", parent_path="")]}
        )

    items = list(build_connector(handler).iter_items())

    assert [i.name for i in items] == ["raport.pdf"]


# --- ponawianie prob -------------------------------------------------------------


def test_ponowienie_po_429_uzywa_naglowka_retry_after() -> None:
    sleeps: list[float] = []
    wywolania: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        wywolania.append(1)
        if len(wywolania) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "7"},
                json=error_body("activityLimitReached", "Za duzo zapytan."),
            )
        return json_response(200, {"value": []})

    client = build_client(handler, sleeps=sleeps)
    payload = client.get_json(f"/drives/{DRIVE_ID}/root/children")

    assert payload == {"value": []}
    assert len(wywolania) == 2
    assert sleeps == [7.0]


def test_ponowienie_po_503_uzywa_opoznienia_wykladniczego() -> None:
    sleeps: list[float] = []
    wywolania: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        wywolania.append(1)
        if len(wywolania) <= 2:
            return json_response(503, error_body("serviceNotAvailable", "Usluga niedostepna."))
        return json_response(200, {"id": ROOT_ID})

    client = build_client(handler, sleeps=sleeps)
    payload = client.get_json(f"/drives/{DRIVE_ID}/root")

    assert payload == {"id": ROOT_ID}
    assert len(wywolania) == 3
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]


def test_wyczerpanie_prob_po_429_konczy_sie_bledem_limitu() -> None:
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "1"},
            json=error_body("activityLimitReached", "Za duzo zapytan."),
        )

    client = build_client(handler, sleeps=sleeps, settings=graph_settings(max_retries=3))

    with pytest.raises(RateLimitedError) as info:
        client.get_json(f"/drives/{DRIVE_ID}/root")

    assert info.value.retry_after == 1.0
    assert "ograniczyl liczbe zapytan" in info.value.user_message
    assert len(sleeps) == 2


def test_wyczerpanie_prob_po_503_konczy_sie_bledem_przejsciowym() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(503, error_body("serviceNotAvailable", "Usluga niedostepna."))

    client = build_client(handler, settings=graph_settings(max_retries=2))

    with pytest.raises(TransientConnectorError):
        client.get_json(f"/drives/{DRIVE_ID}/root")


# --- uwierzytelnienie i uprawnienia ----------------------------------------------


def test_401_raz_odswieza_token_i_ponawia() -> None:
    auth = FakeAuthenticator()
    wywolania: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        wywolania.append(1)
        if len(wywolania) == 1:
            return json_response(401, error_body("InvalidAuthenticationToken", "Token wygasl."))
        return json_response(200, {"id": ROOT_ID})

    client = build_client(handler, authenticator=auth)
    payload = client.get_json(f"/drives/{DRIVE_ID}/root")

    assert payload == {"id": ROOT_ID}
    assert len(wywolania) == 2
    assert auth.refresh_flags == [False, True]


def test_drugie_401_konczy_sie_bledem_uwierzytelnienia() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(401, error_body("InvalidAuthenticationToken", "Token wygasl."))

    client = build_client(handler)

    with pytest.raises(AuthenticationError) as info:
        client.get_json(f"/drives/{DRIVE_ID}/root")

    assert "Zaloguj się ponownie" in info.value.user_message


def test_403_daje_czytelny_komunikat_o_uprawnieniach() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(
            403, error_body("accessDenied", "Konto nie ma dostepu do tej biblioteki.")
        )

    client = build_client(handler)

    with pytest.raises(ConnectorError) as info:
        client.get_json(f"/drives/{DRIVE_ID}/root")

    message = info.value.user_message
    assert "Brak uprawnień" in message
    assert "Files.Read.All" in message
    assert "Sites.Read.All" in message


# --- pobieranie plikow -----------------------------------------------------------


def test_download_zapisuje_plik_strumieniowo(tmp_path: Path) -> None:
    dane = b"Tresc dokumentu testowego. " * 200

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=dane)

    client = build_client(handler)
    cel = tmp_path / "pobrane" / "raport.pdf"

    zapisano = client.download(
        f"/drives/{DRIVE_ID}/items/plik-1/content", cel, expected_size=len(dane)
    )

    assert zapisano == len(dane)
    assert cel.read_bytes() == dane
    assert not cel.with_name(cel.name + ".part").exists()


def test_download_wykrywa_niezgodny_rozmiar(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"za krotka tresc")

    client = build_client(handler)
    cel = tmp_path / "raport.pdf"

    with pytest.raises(DownloadError) as info:
        client.download(f"/drives/{DRIVE_ID}/items/plik-1/content", cel, expected_size=9999)

    assert "inny rozmiar" in info.value.user_message
    assert not cel.exists()
    assert not cel.with_name(cel.name + ".part").exists()


def test_download_ponawia_po_503(tmp_path: Path) -> None:
    sleeps: list[float] = []
    wywolania: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        wywolania.append(1)
        if len(wywolania) == 1:
            return json_response(503, error_body("serviceNotAvailable", "Usluga niedostepna."))
        return httpx.Response(200, content=b"gotowe")

    client = build_client(handler, sleeps=sleeps)
    cel = tmp_path / "raport.pdf"

    assert client.download(f"/drives/{DRIVE_ID}/items/plik-1/content", cel) == 6
    assert cel.read_bytes() == b"gotowe"
    assert len(sleeps) == 1


# --- polityka sieciowa -----------------------------------------------------------


def test_polityka_blokuje_host_spoza_listy() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:  # pragma: no cover - nie powinien zadzialac
        raise AssertionError("Zapytanie nie powinno opuscic klienta.")

    client = build_client(handler)

    with pytest.raises(NetworkPolicyError) as info:
        client.get_json("https://zlosliwy.example.com/dane")

    assert "nie znajduje sie na liscie dozwolonych" in info.value.user_message


def test_polityka_blokuje_wylaczona_kategorie() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("Zapytanie nie powinno opuscic klienta.")

    client = GraphClient(
        FakeAuthenticator(),  # type: ignore[arg-type]
        graph_settings(),
        NetworkPolicy.offline(),
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(NetworkPolicyError) as info:
        client.get_json(f"/drives/{DRIVE_ID}/root")

    assert "jest wylaczona" in info.value.user_message


# --- logi ------------------------------------------------------------------------


def test_logi_nie_zawieraja_tokenu(caplog: pytest.LogCaptureFixture) -> None:
    wywolania: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        wywolania.append(1)
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if len(wywolania) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "1"},
                json=error_body("activityLimitReached", f"Odrzucono token Bearer {TOKEN}."),
            )
        return json_response(200, {"id": ROOT_ID})

    caplog.set_level(logging.DEBUG)
    client = build_client(handler)
    client.get_json(f"/drives/{DRIVE_ID}/root?$select=id")

    wlasne = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("finddocs"))

    # Kontrola samego przechwytywania: bez tego asercje o braku tokenu bylyby puste.
    assert "graph.retry" in wlasne
    assert TOKEN not in caplog.text
    assert "Authorization" not in wlasne
    # Adresy w logach aplikacji sa pozbawione czesci z parametrami, bo parametry
    # moga niesc jednorazowe tokeny pobrania.
    #
    # UWAGA: logger biblioteki httpx (nazwa "httpx") zapisuje na poziomie INFO pelny
    # adres zapytania razem z czescia po znaku zapytania. Aplikacja nie wycisza tego
    # loggera, wiec przy wlaczonym zapisie do pliku pelne adresy Graph trafiaja do
    # dziennika. Ta asercja celowo obejmuje wylacznie zdarzenia loggerow FindDocs.
    assert "$select" not in wlasne
