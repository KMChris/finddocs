"""Miejsce na przyszly provider wewnetrznego API embeddingow.

Provider jest przygotowany, ale domyslnie nieaktywny. Wlaczenie wymaga:

1. ustawienia ``embedding.internal_api_enabled`` na true w konfiguracji;
2. podania adresu ``embedding.internal_api_url``;
3. wlaczenia kategorii ruchu ``internal_api`` w polityce sieciowej;
4. dopisania hosta do listy dozwolonych adresow.

Dopoki te warunki nie sa spelnione, konstruktor rzuca wyjatek. Chodzi o to, zeby
zadna tresc dokumentu nie opuscila komputera przez przypadkowa konfiguracje.

Klasa nie jest atrapa kluczowej funkcji aplikacji: domyslna sciezka wyszukiwania
semantycznego dziala w calosci lokalnie przez ``OnnxEmbeddingProvider``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from finddocs.errors import ConfigurationError, ProviderError
from finddocs.logging_setup import get_logger
from finddocs.providers.base import EmbeddingProvider, ProviderInfo, l2_normalize
from finddocs.security.network import EgressCategory, NetworkPolicy, get_policy
from finddocs.types import CancellationToken

log = get_logger(__name__)

PROVIDER_KEY = "internal_api"
DEFAULT_TIMEOUT_SECONDS = 30.0


class InternalApiEmbeddingProvider(EmbeddingProvider):
    """Klient wewnetrznego API embeddingow organizacji.

    Oczekiwany kontrakt HTTP (do potwierdzenia z zespolem klastra GPU):

    * ``POST {base_url}/embeddings`` z cialem ``{"input": [...], "kind": "passage"}``;
    * odpowiedz ``{"model": "...", "dimension": 768, "data": [{"embedding": [...]}, ...]}``.
    """

    def __init__(
        self,
        base_url: str,
        *,
        enabled: bool,
        model_key: str,
        dimension: int,
        query_prefix: str = "",
        passage_prefix: str = "",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        policy: NetworkPolicy | None = None,
        token_provider: Any | None = None,
    ) -> None:
        if not enabled:
            raise ConfigurationError(
                "Dostawca wewnetrznego API embeddingow jest wylaczony. "
                "Wlacz go swiadomie w ustawieniach, jesli organizacja udostepnila API."
            )
        if not base_url:
            raise ConfigurationError("Nie podano adresu wewnetrznego API embeddingow.")

        self._policy = policy or get_policy()
        self._policy.check(base_url, EgressCategory.INTERNAL_API)

        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._token_provider = token_provider
        self._info = ProviderInfo(
            provider_key=PROVIDER_KEY,
            model_key=model_key,
            model_version="zdalna",
            dimension=dimension,
            max_sequence_length=512,
            pooling="zdalny",
            normalized=True,
            quantized=False,
            query_prefix=query_prefix,
            passage_prefix=passage_prefix,
            license_name="wewnetrzna",
            source=self._base_url,
            runtime="wewnetrzne API organizacji",
        )
        log.warning("provider.internal_api_enabled", url=self._base_url)

    @property
    def info(self) -> ProviderInfo:
        return self._info

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self._token_provider is not None:
            token = self._token_provider()
            if token:
                headers["authorization"] = f"Bearer {token}"
        return headers

    def _post(self, texts: list[str], kind: str) -> np.ndarray:
        import httpx

        url = f"{self._base_url}/embeddings"
        self._policy.check(url, EgressCategory.INTERNAL_API)
        try:
            response = httpx.post(
                url,
                json={"input": texts, "kind": kind},
                headers=self._headers(),
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - httpx zglasza rozne typy
            raise ProviderError(
                "Wewnetrzne API embeddingow nie odpowiedzialo poprawnie.", cause=exc
            ) from exc

        rows = payload.get("data") or []
        if len(rows) != len(texts):
            raise ProviderError("Wewnetrzne API zwrocilo inna liczbe wektorow niz zapytan.")
        matrix = np.asarray([r["embedding"] for r in rows], dtype="float32")
        if matrix.shape[1] != self._info.dimension:
            raise ProviderError(
                f"Wewnetrzne API zwrocilo wektory o wymiarze {matrix.shape[1]}, "
                f"oczekiwano {self._info.dimension}."
            )
        return l2_normalize(matrix)

    def embed_passages(
        self, texts: list[str], *, cancel: CancellationToken | None = None
    ) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype="float32")
        if cancel is not None:
            cancel.raise_if_cancelled()
        prefixed = [self._info.passage_prefix + t for t in texts]
        return self._post(prefixed, "passage")

    def embed_query(self, text: str) -> np.ndarray:
        return self._post([self._info.query_prefix + text], "query")[0]


__all__ = ["DEFAULT_TIMEOUT_SECONDS", "PROVIDER_KEY", "InternalApiEmbeddingProvider"]
