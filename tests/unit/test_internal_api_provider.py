"""Testy zdalnego dostawcy embeddingow: kontrakty, klucz API, ponowienia, polityka.

Wszystkie zadania HTTP ida przez httpx.MockTransport, wiec zaden test nie
nawiazuje prawdziwego polaczenia sieciowego.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import numpy as np
import pytest

from finddocs.errors import ConfigurationError, NetworkPolicyError, ProviderError
from finddocs.providers.internal_api import InternalApiEmbeddingProvider
from finddocs.security.network import EgressCategory, NetworkPolicy

BASE_URL = "https://embeddingi.test"
DIMENSION = 4


def _policy() -> NetworkPolicy:
    return NetworkPolicy(
        enabled_categories={EgressCategory.INTERNAL_API},
        extra_hosts={EgressCategory.INTERNAL_API: ("embeddingi.test",)},
    )


def _vector(seed: int) -> list[float]:
    return [float(seed), 1.0, 0.0, 0.0]


def _ok_response(count: int, *, shuffle: bool = False) -> dict[str, Any]:
    rows = [{"index": i, "embedding": _vector(i + 1)} for i in range(count)]
    if shuffle:
        rows = list(reversed(rows))
    return {"data": rows}


def _provider(
    handler: Any,
    *,
    protocol: str = "finddocs",
    api_key: str | None = None,
    api_key_header: str = "",
    batch_size: int = 64,
    max_retries: int = 3,
    dimension: int = DIMENSION,
    send_dimensions: bool = False,
) -> InternalApiEmbeddingProvider:
    return InternalApiEmbeddingProvider(
        BASE_URL,
        enabled=True,
        model="model-zdalny",
        dimension=dimension,
        protocol=protocol,
        query_prefix="zapytanie: ",
        passage_prefix="",
        batch_size=batch_size,
        max_retries=max_retries,
        api_key_provider=(lambda: api_key) if api_key is not None else None,
        api_key_header=api_key_header,
        send_dimensions=send_dimensions,
        policy=_policy(),
        transport=httpx.MockTransport(handler),
    )


# --- konfiguracja ----------------------------------------------------------------


def test_wylaczony_dostawca_zglasza_blad() -> None:
    with pytest.raises(ConfigurationError):
        InternalApiEmbeddingProvider(
            BASE_URL, enabled=False, model="m", dimension=8, policy=_policy()
        )


def test_brak_adresu_zglasza_blad() -> None:
    with pytest.raises(ConfigurationError):
        InternalApiEmbeddingProvider("", enabled=True, model="m", dimension=8, policy=_policy())


def test_nieznany_kontrakt_zglasza_blad() -> None:
    with pytest.raises(ConfigurationError):
        InternalApiEmbeddingProvider(
            BASE_URL, enabled=True, model="m", dimension=8, protocol="soap", policy=_policy()
        )


def test_zly_wymiar_zglasza_blad() -> None:
    with pytest.raises(ConfigurationError):
        InternalApiEmbeddingProvider(
            BASE_URL, enabled=True, model="m", dimension=0, policy=_policy()
        )


def test_polityka_offline_blokuje_dostawce() -> None:
    with pytest.raises(NetworkPolicyError):
        InternalApiEmbeddingProvider(
            BASE_URL, enabled=True, model="m", dimension=8, policy=NetworkPolicy.offline()
        )


def test_polityka_blokuje_obcy_host() -> None:
    with pytest.raises(NetworkPolicyError):
        InternalApiEmbeddingProvider(
            "https://inny.host", enabled=True, model="m", dimension=8, policy=_policy()
        )


# --- kontrakty -------------------------------------------------------------------


def test_kontrakt_finddocs_wysyla_kind_i_model() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_ok_response(2))

    provider = _provider(handler)
    provider.embed_passages(["pierwszy", "drugi"])
    assert bodies[0]["kind"] == "passage"
    assert bodies[0]["model"] == "model-zdalny"
    assert bodies[0]["input"] == ["pierwszy", "drugi"]


def test_kontrakt_finddocs_zapytanie_ma_prefiks() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_ok_response(1))

    provider = _provider(handler)
    provider.embed_query("umowa najmu")
    assert bodies[0]["kind"] == "query"
    assert bodies[0]["input"] == ["zapytanie: umowa najmu"]


def test_kontrakt_openai_wysyla_model_i_format() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_ok_response(1))

    provider = _provider(handler, protocol="openai")
    provider.embed_passages(["tekst"])
    assert bodies[0] == {
        "input": ["tekst"],
        "encoding_format": "float",
        "model": "model-zdalny",
    }
    assert "kind" not in bodies[0]


def test_domyslnie_nie_wysyla_pola_dimensions() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_ok_response(1))

    _provider(handler, protocol="openai").embed_passages(["tekst"])
    assert "dimensions" not in bodies[0]


def test_wlaczone_zadanie_wymiaru_dokleja_pole_dimensions() -> None:
    """Modele z Matryoshka skracaja wektor po stronie serwera."""
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_ok_response(1))

    provider = _provider(handler, protocol="openai", send_dimensions=True)
    provider.embed_passages(["tekst"])
    provider.embed_query("pytanie")

    assert bodies[0]["dimensions"] == DIMENSION
    assert bodies[1]["dimensions"] == DIMENSION
    assert provider.describe()["zada_wymiaru"] is True


def test_serwer_ignorujacy_dimensions_konczy_sie_bledem_wymiaru() -> None:
    """Cicha zmiana dlugosci wektora byla najgorszym mozliwym wynikiem."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 99}]})

    provider = _provider(handler, protocol="openai", send_dimensions=True)
    with pytest.raises(ProviderError) as blad:
        provider.embed_passages(["tekst"])
    assert "wymiarze" in blad.value.user_message


def test_kontrakt_openai_porzadkuje_wiersze_po_polu_index() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_response(3, shuffle=True))

    provider = _provider(handler, protocol="openai")
    matrix = provider.embed_passages(["a", "b", "c"])
    # Wiersz o index=0 ma najwieksza pierwsza skladowa po normalizacji L2
    # dopiero po odtworzeniu kolejnosci wejsciowej.
    expected_first = 1.0 / np.sqrt(2.0)
    assert matrix[0][0] == pytest.approx(expected_first)


# --- klucz API -------------------------------------------------------------------


def test_klucz_api_trafia_do_naglowka_bearer() -> None:
    headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        headers.append(request.headers)
        return httpx.Response(200, json=_ok_response(1))

    provider = _provider(handler, api_key="sekret-123")
    provider.embed_passages(["tekst"])
    assert headers[0]["authorization"] == "Bearer sekret-123"


def test_klucz_api_w_niestandardowym_naglowku() -> None:
    headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        headers.append(request.headers)
        return httpx.Response(200, json=_ok_response(1))

    provider = _provider(handler, api_key="sekret-456", api_key_header="api-key")
    provider.embed_passages(["tekst"])
    assert headers[0]["api-key"] == "sekret-456"
    assert "authorization" not in headers[0]


def test_brak_klucza_nie_dodaje_naglowka() -> None:
    headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        headers.append(request.headers)
        return httpx.Response(200, json=_ok_response(1))

    provider = _provider(handler)
    provider.embed_passages(["tekst"])
    assert "authorization" not in headers[0]


# --- ponowienia i bledy ----------------------------------------------------------


def test_blad_przejsciowy_jest_ponawiany(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("finddocs.providers.internal_api._sleep_with_cancel", lambda *args: None)
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=_ok_response(1))

    provider = _provider(handler)
    matrix = provider.embed_passages(["tekst"])
    assert len(calls) == 3
    assert matrix.shape == (1, DIMENSION)


def test_wyczerpanie_prob_zglasza_blad(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("finddocs.providers.internal_api._sleep_with_cancel", lambda *args: None)
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429)

    provider = _provider(handler, max_retries=2)
    with pytest.raises(ProviderError):
        provider.embed_passages(["tekst"])
    assert len(calls) == 2


def test_odmowa_uwierzytelnienia_nie_jest_ponawiana() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401)

    provider = _provider(handler)
    with pytest.raises(ProviderError, match="uwierzytelnienie"):
        provider.embed_passages(["tekst"])
    assert len(calls) == 1


def test_zla_liczba_wektorow_zglasza_blad() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_response(1))

    provider = _provider(handler)
    with pytest.raises(ProviderError, match="liczbę wektorów"):
        provider.embed_passages(["a", "b"])


def test_zly_wymiar_wektorow_zglasza_blad() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [1.0, 2.0]}]})

    provider = _provider(handler)
    with pytest.raises(ProviderError, match="wymiarze"):
        provider.embed_passages(["tekst"])


def test_wartosci_nieliczbowe_zglaszaja_blad() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # json.dumps w httpx odrzuca NaN, wiec odpowiedz jest budowana recznie.
        return httpx.Response(
            200,
            content=b'{"data": [{"embedding": [NaN, 0.0, 0.0, 0.0]}]}',
            headers={"content-type": "application/json"},
        )

    provider = _provider(handler)
    with pytest.raises(ProviderError, match="nieliczbowymi"):
        provider.embed_passages(["tekst"])


# --- batchowanie i normalizacja --------------------------------------------------


def test_teksty_sa_dzielone_na_paczki() -> None:
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sizes.append(len(body["input"]))
        return httpx.Response(200, json=_ok_response(len(body["input"])))

    provider = _provider(handler, batch_size=2)
    matrix = provider.embed_passages(["a", "b", "c", "d", "e"])
    assert sizes == [2, 2, 1]
    assert matrix.shape == (5, DIMENSION)


def test_wektory_sa_znormalizowane_l2() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [3.0, 4.0, 0.0, 0.0]}]})

    provider = _provider(handler)
    matrix = provider.embed_passages(["tekst"])
    assert float(np.linalg.norm(matrix[0])) == pytest.approx(1.0)


def test_pusta_lista_nie_wysyla_zadania() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("zadanie HTTP nie powinno zostac wyslane")

    provider = _provider(handler)
    matrix = provider.embed_passages([])
    assert matrix.shape == (0, DIMENSION)


def test_describe_nie_zawiera_klucza() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_response(1))

    provider = _provider(handler, api_key="sekret-789")
    opis = json.dumps(provider.describe(), ensure_ascii=False)
    assert "sekret-789" not in opis
    assert "skonfigurowany" in opis
