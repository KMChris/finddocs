"""Zdalny dostawca embeddingow: wewnetrzne API organizacji albo zgodne z OpenAI.

Provider jest domyslnie nieaktywny. Wlaczenie wymaga swiadomej konfiguracji:

1. ustawienia ``embedding.internal_api_enabled`` na true;
2. podania adresu ``embedding.internal_api_url``;
3. wlaczenia kategorii ruchu ``internal_api`` w polityce sieciowej
   (aplikacja robi to na podstawie punktu 1 i dopuszcza wylacznie host
   z podanego adresu);
4. zapisania klucza API w magazynie poswiadczen, jesli API go wymaga.

Dopoki te warunki nie sa spelnione, konstruktor rzuca wyjatek. Chodzi o to, zeby
zadna tresc dokumentu nie opuscila komputera przez przypadkowa konfiguracje.
Domyslna sciezka wyszukiwania semantycznego dziala w calosci lokalnie przez
``OnnxEmbeddingProvider``.

Obslugiwane kontrakty HTTP:

* ``openai`` (domyslny): ``POST {base_url}/embeddings`` z cialem
  ``{"model": "...", "input": [...], "encoding_format": "float"}``, czyli
  standard OpenAI ``/v1/embeddings``. Obsluguja go tez typowe wdrozenia
  wewnetrzne: vLLM, TEI, bramki API. Ewentualne przedrostki zapytania i tresci
  dokleja aplikacja przed wysylka.
* ``finddocs`` (opcjonalny): jak wyzej, ale cialo zawiera dodatkowo pole
  ``"kind": "query"|"passage"``, dzieki ktoremu serwer sam rozroznia rodzaj
  tekstu i moze zastosowac wlasne przedrostki.

Obie odpowiedzi maja postac ``{"data": [{"embedding": [...]}, ...]}``.

Po wlaczeniu ``send_dimensions`` cialo zadania niesie dodatkowo pole
``dimensions`` rowne zadeklarowanemu wymiarowi. Sluzy modelom trenowanym
z Matryoshka (MRL), ktore potrafia zwrocic skrocony wektor. Serwer musi to
pole obslugiwac: gdy je zignoruje, odpowiedz nie zgodzi sie z wymiarem
i ``_parse_payload`` zglosi blad.

Klucz API nigdy nie trafia do logow ani do pliku konfiguracyjnego. Provider
otrzymuje funkcje zwracajaca klucz i odczytuje go dopiero przy wysylce.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np

from finddocs.errors import ConfigurationError, ProviderError
from finddocs.logging_setup import get_logger
from finddocs.providers.base import EmbeddingProvider, ProviderInfo, l2_normalize
from finddocs.security.network import EgressCategory, NetworkPolicy, get_policy
from finddocs.security.redaction import safe_url
from finddocs.types import CancellationToken

log = get_logger(__name__)

PROVIDER_KEY = "internal_api"
DEFAULT_TIMEOUT_SECONDS = 30.0

#: Obslugiwane kontrakty zdalnego API. Pierwszy jest domyslny.
SUPPORTED_PROTOCOLS: tuple[str, ...] = ("openai", "finddocs")

#: Kody HTTP traktowane jako przejsciowe: warto ponowic probe.
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})

#: Podstawa i gorna granica odczekania miedzy probami (sekundy).
RETRY_BACKOFF_BASE_SECONDS = 0.5
RETRY_BACKOFF_MAX_SECONDS = 8.0


def _sleep_with_cancel(seconds: float, cancel: CancellationToken | None) -> None:
    """Odczekuje miedzy probami, przerywajac natychmiast po anulowaniu."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if cancel is not None:
            cancel.raise_if_cancelled()
        time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
    if cancel is not None:
        cancel.raise_if_cancelled()


class InternalApiEmbeddingProvider(EmbeddingProvider):
    """Klient zdalnego API embeddingow z uwierzytelnieniem kluczem API."""

    def __init__(
        self,
        base_url: str,
        *,
        enabled: bool,
        model: str,
        dimension: int,
        protocol: str = "openai",
        query_prefix: str = "",
        passage_prefix: str = "",
        batch_size: int = 64,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = 3,
        api_key_provider: Callable[[], str | None] | None = None,
        api_key_header: str = "",
        send_dimensions: bool = False,
        policy: NetworkPolicy | None = None,
        transport: Any | None = None,
    ) -> None:
        """``transport`` to hak testowy: pozwala podstawic httpx.MockTransport."""
        if not enabled:
            raise ConfigurationError(
                "Dostawca zdalnego API embeddingów jest wyłączony. "
                "Włącz go świadomie w ustawieniach, jeśli organizacja udostępniła API."
            )
        if not base_url:
            raise ConfigurationError("Nie podano adresu zdalnego API embeddingów.")
        if protocol not in SUPPORTED_PROTOCOLS:
            raise ConfigurationError(
                f"Nieznany kontrakt zdalnego API: '{protocol}'. "
                "Dozwolone wartości: openai, finddocs."
            )
        if dimension <= 0:
            raise ConfigurationError(
                f"Wymiar wektora zdalnego API musi być liczbą dodatnią. Podano: {dimension}."
            )

        self._policy = policy or get_policy()
        self._policy.check(base_url, EgressCategory.INTERNAL_API)

        self._base_url = base_url.rstrip("/")
        self._protocol = protocol
        self._model = model
        self._timeout = max(1.0, timeout)
        self._batch_size = max(1, batch_size)
        self._max_retries = max(1, max_retries)
        self._api_key_provider = api_key_provider
        self._api_key_header = api_key_header.strip()
        self._send_dimensions = send_dimensions
        self._transport = transport
        self._client: Any | None = None
        self._info = ProviderInfo(
            provider_key=PROVIDER_KEY,
            model_key=model or "zdalny-model",
            model_version="zdalna",
            dimension=dimension,
            max_sequence_length=512,
            pooling="zdalny",
            normalized=True,
            quantized=False,
            query_prefix=query_prefix,
            passage_prefix=passage_prefix,
            license_name="wewnetrzna",
            source=safe_url(self._base_url),
            runtime=f"zdalne API ({protocol})",
        )
        log.warning(
            "provider.internal_api_enabled",
            url=safe_url(self._base_url),
            protocol=protocol,
            batch_size=self._batch_size,
        )

    @property
    def info(self) -> ProviderInfo:
        return self._info

    # --- polaczenie --------------------------------------------------------

    def _http_client(self) -> Any:
        if self._client is None:
            import httpx

            kwargs: dict[str, Any] = {"timeout": self._timeout}
            if self._transport is not None:
                kwargs["transport"] = self._transport
            self._client = httpx.Client(**kwargs)
        return self._client

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        key = self._api_key_provider() if self._api_key_provider is not None else None
        if key:
            if self._api_key_header:
                headers[self._api_key_header] = key
            else:
                headers["authorization"] = f"Bearer {key}"
        return headers

    def _request_body(self, texts: list[str], kind: str) -> dict[str, Any]:
        if self._protocol == "openai":
            body: dict[str, Any] = {"input": texts, "encoding_format": "float"}
        else:
            body = {"input": texts, "kind": kind}
        if self._model:
            body["model"] = self._model
        if self._send_dimensions:
            # Pole standardu OpenAI. Modele z Matryoshka zwracaja wtedy wektor
            # skrocony do zadanej dlugosci. Wartosc jest ta sama, ktora
            # sprawdza _parse_payload, wiec zignorowanie pola przez serwer
            # skonczy sie czytelnym bledem o niezgodnym wymiarze.
            body["dimensions"] = self._info.dimension
        return body

    def _post_once(self, url: str, body: dict[str, Any]) -> Any:
        import httpx

        client = self._http_client()
        try:
            response = client.post(url, json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise _TransientRemoteError(type(exc).__name__) from exc
        if response.status_code in RETRYABLE_STATUS_CODES:
            raise _TransientRemoteError(f"HTTP {response.status_code}")
        if response.status_code in (401, 403):
            raise ProviderError(
                "Zdalne API embeddingów odrzuciło uwierzytelnienie. "
                "Sprawdź klucz API w ustawieniach modelu."
            )
        try:
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise ProviderError(
                "Zdalne API embeddingów nie odpowiedziało poprawnie.", cause=exc
            ) from exc

    def _post_batch(
        self, texts: list[str], kind: str, cancel: CancellationToken | None
    ) -> np.ndarray:
        url = f"{self._base_url}/embeddings"
        self._policy.check(url, EgressCategory.INTERNAL_API)
        body = self._request_body(texts, kind)

        last_reason = ""
        for attempt in range(1, self._max_retries + 1):
            if cancel is not None:
                cancel.raise_if_cancelled()
            try:
                payload = self._post_once(url, body)
                return self._parse_payload(payload, expected=len(texts))
            except _TransientRemoteError as exc:
                last_reason = exc.reason
                log.warning(
                    "provider.internal_api_retry",
                    attempt=attempt,
                    max_attempts=self._max_retries,
                    reason=exc.reason,
                )
                if attempt < self._max_retries:
                    delay = min(
                        RETRY_BACKOFF_MAX_SECONDS,
                        RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
                    )
                    _sleep_with_cancel(delay, cancel)
        raise ProviderError(
            "Zdalne API embeddingów nie odpowiedziało mimo kilku prób. "
            f"Ostatni powód: {last_reason}."
        )

    def _parse_payload(self, payload: Any, *, expected: int) -> np.ndarray:
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or len(rows) != expected:
            raise ProviderError("Zdalne API zwróciło inną liczbę wektorów niż tekstów.")
        try:
            # Kontrakt openai pozwala zwracac wiersze w dowolnej kolejnosci,
            # z jawnym polem index. Brak pola oznacza kolejnosc wejsciowa.
            indexed = sorted(enumerate(rows), key=lambda pair: int(pair[1].get("index", pair[0])))
            matrix = np.asarray([row["embedding"] for _, row in indexed], dtype="float32")
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ProviderError(
                "Zdalne API zwróciło odpowiedź w nieoczekiwanym formacie.", cause=exc
            ) from exc
        if matrix.ndim != 2 or matrix.shape[1] != self._info.dimension:
            got = matrix.shape[1] if matrix.ndim == 2 else "nieznany"
            raise ProviderError(
                f"Zdalne API zwróciło wektory o wymiarze {got}, oczekiwano {self._info.dimension}."
            )
        if not np.isfinite(matrix).all():
            raise ProviderError("Zdalne API zwróciło wektory z wartościami nieliczbowymi.")
        return l2_normalize(matrix)

    # --- interfejs dostawcy ------------------------------------------------

    def embed_passages(
        self, texts: list[str], *, cancel: CancellationToken | None = None
    ) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype="float32")
        prefix = self._info.passage_prefix
        prepared = [prefix + (t or " ") for t in texts]
        parts: list[np.ndarray] = []
        for start in range(0, len(prepared), self._batch_size):
            if cancel is not None:
                cancel.raise_if_cancelled()
            batch = prepared[start : start + self._batch_size]
            parts.append(self._post_batch(batch, "passage", cancel))
        stacked: np.ndarray = np.vstack(parts)
        return stacked

    def embed_query(self, text: str) -> np.ndarray:
        prepared = self._info.query_prefix + (text or " ")
        vectors = self._post_batch([prepared], "query", None)
        first: np.ndarray = vectors[0]
        return first

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

    def describe(self) -> dict[str, Any]:
        data = super().describe()
        data["adres"] = safe_url(self._base_url)
        data["kontrakt"] = self._protocol
        data["batch"] = self._batch_size
        data["zada_wymiaru"] = self._send_dimensions
        data["klucz_api"] = "skonfigurowany" if self._api_key_provider is not None else "brak"
        return data


class _TransientRemoteError(Exception):
    """Wewnetrzny sygnal bledu przejsciowego, obslugiwany przez ponowienia."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "PROVIDER_KEY",
    "RETRYABLE_STATUS_CODES",
    "SUPPORTED_PROTOCOLS",
    "InternalApiEmbeddingProvider",
]
