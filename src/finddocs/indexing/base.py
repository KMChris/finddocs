"""Protokoly warstwy indeksowania.

Magazyn wektorow ma dwie implementacje: lokalny plik FAISS (``indexing.vector``)
oraz zewnetrzna baze PostgreSQL z rozszerzeniem pgvector (``indexing.pgvector``).
Warstwy wyzsze (writer, service, maintenance, search) widza wylacznie ten
protokol i nie moga zalezec od konkretnej implementacji.
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np


class VectorIndex(Protocol):
    """Wspolny interfejs magazynow wektorow fragmentow.

    Semantyka metod odpowiada implementacji FAISS. Magazyny bez nagrobkow
    (np. pgvector, gdzie usuniecie jest natychmiastowe) zwracaja zero
    z ``deleted_count`` i ``False`` z ``needs_compaction``.
    """

    def open(
        self,
        *,
        dimension: int,
        model_key: str,
        model_version: str,
        vector_compat_hash: str,
        create: bool = True,
    ) -> None: ...

    def close(self) -> None: ...

    def save(self) -> None: ...

    @property
    def is_open(self) -> bool: ...

    @property
    def dimension(self) -> int: ...

    def count(self) -> int: ...

    def raw_count(self) -> int: ...

    def deleted_count(self) -> int: ...

    def needs_compaction(self) -> bool: ...

    def add(self, ids: list[int], vectors: np.ndarray) -> None: ...

    def remove(self, ids: list[int]) -> None: ...

    def search(
        self, query: np.ndarray, k: int, *, overfetch: float = 2.0
    ) -> list[tuple[int, float]]: ...

    def compact(self, active_ids: list[int], vectors: np.ndarray) -> None: ...

    def reconstruct(self, chunk_id: int) -> np.ndarray | None: ...

    def reset(self) -> None: ...

    def size_bytes(self) -> int: ...

    def describe(self) -> dict[str, Any]: ...


__all__ = ["VectorIndex"]
