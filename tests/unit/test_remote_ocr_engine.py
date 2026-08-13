"""Testy zdalnego silnika OCR: dostepnosc, kontrakt PaddleX, klucz, ponowienia.

Wszystkie zadania HTTP ida przez httpx.MockTransport, wiec zaden test nie
nawiazuje prawdziwego polaczenia sieciowego.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from PIL import Image

from finddocs.config import AppConfig, OcrSettings
from finddocs.errors import NetworkPolicyError, OcrRemoteError
from finddocs.ocr.engines.remote_api import ENGINE_NAME, RemoteOcrEngine
from finddocs.ocr.service import AUTO_ENGINE_ORDER, build_engines, build_remote_engine
from finddocs.security.network import EgressCategory, NetworkPolicy, policy_from_config

BASE_URL = "https://ocr.test"


def _policy() -> NetworkPolicy:
    return NetworkPolicy(
        enabled_categories={EgressCategory.OCR_API},
        extra_hosts={EgressCategory.OCR_API: ("ocr.test",)},
    )


def _page(*lines: tuple[str, float, list[list[int]]]) -> dict[str, Any]:
    """Buduje odpowiedz serwera PaddleX dla jednej strony."""
    return {
        "logId": "test",
        "errorCode": 0,
        "errorMsg": "Success",
        "result": {
            "ocrResults": [
                {
                    "prunedResult": {
                        "rec_texts": [text for text, _, _ in lines],
                        "rec_scores": [score for _, score, _ in lines],
                        "dt_polys": [poly for _, _, poly in lines],
                    }
                }
            ],
            "dataInfo": {},
        },
    }


def _box(x: int, y: int, width: int = 100, height: int = 20) -> list[list[int]]:
    return [[x, y], [x + width, y], [x + width, y + height], [x, y + height]]


def _engine(
    handler: Any,
    *,
    enabled: bool = True,
    base_url: str = BASE_URL,
    api_key: str | None = None,
    api_key_header: str = "",
    max_retries: int = 3,
    auto_rotate: bool = True,
    policy: NetworkPolicy | None = None,
) -> RemoteOcrEngine:
    return RemoteOcrEngine(
        base_url,
        enabled=enabled,
        model="PP-OCRv6_medium",
        max_retries=max_retries,
        api_key_provider=(lambda: api_key) if api_key is not None else None,
        api_key_header=api_key_header,
        auto_rotate=auto_rotate,
        policy=policy or _policy(),
        transport=httpx.MockTransport(handler),
    )


def _image(width: int = 120, height: int = 60) -> Image.Image:
    return Image.new("RGB", (width, height), color=(255, 255, 255))


def _alive(response: httpx.Response) -> Any:
    """Handler odpowiadajacy na sonde stanu i na rozpoznawanie."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/health"):
            return httpx.Response(200, json={"status": "ok"})
        return response

    return handler


# --- dostepnosc ------------------------------------------------------------------


def test_wylaczony_silnik_jest_niedostepny() -> None:
    engine = _engine(_alive(httpx.Response(200, json=_page())), enabled=False)
    assert engine.is_available() is False
    assert "wyłączony" in engine.unavailable_reason()


def test_brak_adresu_oznacza_niedostepnosc() -> None:
    engine = _engine(_alive(httpx.Response(200, json=_page())), base_url="")
    assert engine.is_available() is False
    assert "adresu" in engine.unavailable_reason()


def test_polityka_offline_blokuje_silnik() -> None:
    engine = _engine(_alive(httpx.Response(200, json=_page())), policy=NetworkPolicy.offline())
    assert engine.is_available() is False
    assert "ocr_api" in engine.unavailable_reason()


def test_polityka_blokuje_obcy_host() -> None:
    engine = _engine(_alive(httpx.Response(200, json=_page())), base_url="https://inny.host")
    assert engine.is_available() is False


def test_martwy_serwer_oznacza_niedostepnosc() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("brak polaczenia")

    engine = _engine(handler)
    assert engine.is_available() is False
    assert "nie odpowiada" in engine.unavailable_reason()


def test_brak_endpointu_health_nie_wyklucza_serwera() -> None:
    """Nie kazde wdrozenie wystawia /health. Odpowiedz 404 tez dowodzi zycia."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/health"):
            return httpx.Response(404)
        return httpx.Response(200, json=_page(("tekst", 0.9, _box(0, 0))))

    engine = _engine(handler)
    assert engine.is_available() is True


def test_silnik_deklaruje_polski_i_wersje_modelu() -> None:
    engine = _engine(_alive(httpx.Response(200, json=_page())))
    assert engine.has_polish() is True
    assert engine.version() == "PP-OCRv6_medium"


# --- kontrakt zadania ------------------------------------------------------------


def test_zadanie_niesie_obraz_base64_i_wylacza_podglad() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/health"):
            return httpx.Response(200)
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_page(("Umowa", 0.98, _box(0, 0))))

    engine = _engine(handler)
    engine.recognize(_image(), languages=["pol"], page=1)

    assert len(bodies) == 1
    body = bodies[0]
    assert body["fileType"] == 1
    assert body["visualize"] is False
    assert body["useDocOrientationClassify"] is False
    assert body["useDocUnwarping"] is False
    assert body["useTextlineOrientation"] is True
    assert body["file"].startswith("iVBOR")  # naglowek PNG w base64


def test_wylaczona_korekta_obrotu_trafia_do_zadania() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/health"):
            return httpx.Response(200)
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_page())

    engine = _engine(handler, auto_rotate=False)
    engine.recognize(_image(), languages=["pol"], page=1)
    assert bodies[0]["useTextlineOrientation"] is False


def test_klucz_api_idzie_w_naglowku_bearer() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization", ""))
        if request.url.path.endswith("/health"):
            return httpx.Response(200)
        return httpx.Response(200, json=_page())

    engine = _engine(handler, api_key="tajne")
    engine.recognize(_image(), languages=["pol"], page=1)
    assert seen[-1] == "Bearer tajne"


def test_wlasny_naglowek_klucza() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("x-api-key", ""))
        if request.url.path.endswith("/health"):
            return httpx.Response(200)
        return httpx.Response(200, json=_page())

    engine = _engine(handler, api_key="tajne", api_key_header="x-api-key")
    engine.recognize(_image(), languages=["pol"], page=1)
    assert seen[-1] == "tajne"


# --- odpowiedz -------------------------------------------------------------------


def test_wynik_ma_tekst_pewnosc_i_ramki() -> None:
    response = httpx.Response(
        200,
        json=_page(
            ("Faktura VAT", 0.99, _box(10, 10)),
            ("Kwota: 1 234,56 zł", 0.95, _box(10, 40)),
        ),
    )
    engine = _engine(_alive(response))
    result = engine.recognize(_image(), languages=["pol"], page=3)

    assert result.page == 3
    assert result.engine == ENGINE_NAME
    assert result.text == "Faktura VAT\nKwota: 1 234,56 zł"
    assert result.confidence is not None
    assert result.confidence == pytest.approx(0.97)
    assert result.lines[0].box == (10, 10, 100, 20)


def test_linie_sa_porzadkowane_od_gory_i_od_lewej() -> None:
    response = httpx.Response(
        200,
        json=_page(
            ("dolna", 0.9, _box(10, 200)),
            ("gorna prawa", 0.9, _box(300, 10)),
            ("gorna lewa", 0.9, _box(10, 10)),
        ),
    )
    engine = _engine(_alive(response))
    result = engine.recognize(_image(), languages=["pol"], page=1)
    assert result.text.splitlines() == ["gorna lewa", "gorna prawa", "dolna"]


def test_puste_linie_sa_pomijane() -> None:
    response = httpx.Response(
        200,
        json=_page(("   ", 0.4, _box(0, 0)), ("tresc", 0.9, _box(0, 30))),
    )
    engine = _engine(_alive(response))
    result = engine.recognize(_image(), languages=["pol"], page=1)
    assert result.text == "tresc"
    assert result.confidence == pytest.approx(0.9)


def test_strona_bez_tekstu_daje_pusty_wynik() -> None:
    engine = _engine(_alive(httpx.Response(200, json=_page())))
    result = engine.recognize(_image(), languages=["pol"], page=1)
    assert result.text == ""
    assert result.confidence is None


def test_brak_wynikow_w_odpowiedzi_daje_pusty_wynik() -> None:
    payload = {"errorCode": 0, "result": {"ocrResults": [], "dataInfo": {}}}
    engine = _engine(_alive(httpx.Response(200, json=payload)))
    result = engine.recognize(_image(), languages=["pol"], page=1)
    assert result.text == ""


# --- bledy -----------------------------------------------------------------------


def test_kod_bledu_serwera_konczy_sie_wyjatkiem() -> None:
    payload = {"errorCode": 5, "errorMsg": "Nieobslugiwany format", "result": None}
    engine = _engine(_alive(httpx.Response(200, json=payload)))
    with pytest.raises(OcrRemoteError, match="5"):
        engine.recognize(_image(), languages=["pol"], page=1)


def test_odrzucone_uwierzytelnienie_wskazuje_klucz() -> None:
    engine = _engine(_alive(httpx.Response(401, json={"detail": "brak klucza"})))
    with pytest.raises(OcrRemoteError, match="klucz API"):
        engine.recognize(_image(), languages=["pol"], page=1)


def test_odpowiedz_bez_wynikow_konczy_sie_wyjatkiem() -> None:
    engine = _engine(_alive(httpx.Response(200, json={"errorCode": 0, "result": {}})))
    with pytest.raises(OcrRemoteError):
        engine.recognize(_image(), languages=["pol"], page=1)


def test_blad_przejsciowy_jest_ponawiany() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/health"):
            return httpx.Response(200)
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=_page(("po ponowieniu", 0.9, _box(0, 0))))

    engine = _engine(handler, max_retries=3)
    result = engine.recognize(_image(), languages=["pol"], page=1)
    assert result.text == "po ponowieniu"
    assert len(attempts) == 3


def test_wyczerpane_proby_konczy_sie_wyjatkiem() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/health"):
            return httpx.Response(200)
        return httpx.Response(503)

    engine = _engine(handler, max_retries=2)
    with pytest.raises(OcrRemoteError, match="2 prób"):
        engine.recognize(_image(), languages=["pol"], page=1)


def test_anulowanie_przerywa_przed_wysylka() -> None:
    class Cancelled(Exception):
        pass

    class Token:
        def is_cancelled(self) -> bool:
            return True

        def raise_if_cancelled(self) -> None:
            raise Cancelled()

    sent: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(1)
        return httpx.Response(200, json=_page())

    engine = _engine(handler)
    with pytest.raises(Cancelled):
        engine.recognize(_image(), languages=["pol"], page=1, cancel=Token())
    assert sent == []


# --- test polaczenia -------------------------------------------------------------


def test_ping_zwraca_model_i_czas() -> None:
    engine = _engine(_alive(httpx.Response(200, json=_page())))
    result = engine.ping()
    assert result["model"] == "PP-OCRv6_medium"
    assert result["adres"] == BASE_URL
    assert isinstance(result["czas_odpowiedzi_s"], float)


def test_ping_zglasza_martwy_serwer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("limit czasu")

    engine = _engine(handler)
    with pytest.raises(OcrRemoteError):
        engine.ping()


# --- wybor silnika i polityka ----------------------------------------------------


def test_zdalny_silnik_wchodzi_do_listy_tylko_po_wybraniu() -> None:
    settings = OcrSettings(remote_api_enabled=True, remote_api_url=BASE_URL)
    assert ENGINE_NAME not in [engine.name for engine in build_engines(settings)]

    settings.engine = ENGINE_NAME
    names = [engine.name for engine in build_engines(settings)]
    assert names[0] == ENGINE_NAME
    # Silniki lokalne zostaja jako rezerwa na wypadek awarii serwera.
    assert set(AUTO_ENGINE_ORDER).issubset(set(names))


def test_polityka_dopuszcza_dokladnie_jeden_host() -> None:
    config = AppConfig()
    config.ocr.remote_api_enabled = True
    config.ocr.remote_api_url = "https://ocr.firma.local/"
    policy = policy_from_config(config)

    assert policy.is_enabled(EgressCategory.OCR_API)
    assert policy.allowed_hosts(EgressCategory.OCR_API) == ("ocr.firma.local",)
    with pytest.raises(NetworkPolicyError):
        policy.check("https://inny.serwer/ocr", EgressCategory.OCR_API)


def test_wylaczony_zdalny_ocr_zamyka_kategorie() -> None:
    config = AppConfig()
    config.ocr.remote_api_url = "https://ocr.firma.local"
    policy = policy_from_config(config)
    assert not policy.is_enabled(EgressCategory.OCR_API)


def test_fabryka_przenosi_ustawienia_do_silnika() -> None:
    settings = OcrSettings(
        engine=ENGINE_NAME,
        remote_api_enabled=True,
        remote_api_url="https://ocr.firma.local/",
        remote_api_model="PP-OCRv6_small",
        remote_api_max_retries=5,
    )
    engine = build_remote_engine(settings, None, policy=NetworkPolicy.offline())
    assert engine.endpoint == "https://ocr.firma.local/ocr"
    assert engine.version() == "PP-OCRv6_small"
