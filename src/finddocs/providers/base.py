"""Interfejs dostawcy embeddingow.

Warstwa indeksowania i wyszukiwania nie wie, skad biora sie wektory. Dzieki temu
mozna podmienic model lokalny na wewnetrzne API organizacji bez zmian w reszcie kodu.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np

from finddocs.types import CancellationToken


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """Opis dostawcy zapisywany w metadanych indeksu."""

    provider_key: str
    model_key: str
    model_version: str
    dimension: int
    max_sequence_length: int
    pooling: str
    normalized: bool
    quantized: bool
    query_prefix: str
    passage_prefix: str
    license_name: str
    source: str
    runtime: str

    def identity(self) -> str:
        """Napis jednoznacznie identyfikujacy konfiguracje wektorow."""
        return (
            f"{self.provider_key}/{self.model_key}@{self.model_version}"
            f"/d{self.dimension}/{self.pooling}/{'q' if self.quantized else 'f'}"
        )


class EmbeddingProvider(ABC):
    """Dostawca embeddingow tekstu."""

    @property
    @abstractmethod
    def info(self) -> ProviderInfo: ...

    @property
    def dimension(self) -> int:
        return self.info.dimension

    @abstractmethod
    def embed_passages(
        self, texts: list[str], *, cancel: CancellationToken | None = None
    ) -> np.ndarray:
        """Zwraca macierz (n, dim) float32 dla fragmentow dokumentow."""

    @abstractmethod
    def embed_query(self, text: str) -> np.ndarray:
        """Zwraca pojedynczy wektor (dim,) float32 dla zapytania uzytkownika."""

    def warmup(self) -> None:
        """Wstepne zaladowanie modelu, zeby pierwsze zapytanie nie bylo wolne."""
        self.embed_query("test")

    def close(self) -> None:
        """Zwalnia zasoby."""

    def describe(self) -> dict[str, Any]:
        info = self.info
        return {
            "dostawca": info.provider_key,
            "model": info.model_key,
            "wersja_modelu": info.model_version,
            "wymiar": info.dimension,
            "max_dlugosc": info.max_sequence_length,
            "pooling": info.pooling,
            "kwantyzacja": info.quantized,
            "licencja": info.license_name,
            "zrodlo": info.source,
            "srodowisko": info.runtime,
        }


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """Normalizuje wiersze macierzy do dlugosci 1."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    np.maximum(norms, 1e-12, out=norms)
    normalized: np.ndarray = (matrix / norms).astype("float32", copy=False)
    return normalized


__all__ = ["EmbeddingProvider", "ProviderInfo", "l2_normalize"]
