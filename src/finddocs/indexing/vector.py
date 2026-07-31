"""Trwaly indeks wektorowy oparty o FAISS.

Wybor konstrukcji: ``IndexIDMap2`` nad ``IndexHNSWFlat`` z metryka iloczynu skalarnego.
Wektory sa normalizowane L2, wiec iloczyn skalarny odpowiada podobienstwu cosinusowemu.

FAISS HNSW nie obsluguje usuwania pojedynczych wektorow. Usuniecia sa zapisywane
jako nagrobki w pliku metadanych, a zapytania pobieraja nadmiarowa liczbe kandydatow
i odfiltrowuja nieaktualne identyfikatory. Gdy udzial nagrobkow przekroczy prog,
indeks jest kompaktowany: budowany od nowa z aktualnych wektorow.

Zapis jest atomowy: plik tymczasowy, ``fsync``, podmiana. Dzieki temu przerwanie
aplikacji nie niszczy dzialajacego indeksu.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from finddocs.errors import IndexCorruptedError, IndexIncompatibleError
from finddocs.logging_setup import get_logger
from finddocs.version import VECTOR_STORE_VERSION

log = get_logger(__name__)

#: Parametry HNSW. M kontroluje liczbe polaczen, ef sterowanie jakoscia zapytania.
HNSW_M = 32
HNSW_EF_CONSTRUCTION = 80
HNSW_EF_SEARCH = 128

#: Powyzej tego udzialu nagrobkow warto skompaktowac indeks.
COMPACTION_THRESHOLD = 0.25

#: Ponizej tej liczby wektorow uzywamy indeksu plaskiego (dokladnego).
FLAT_INDEX_LIMIT = 2000


@dataclass(slots=True)
class VectorIndexMeta:
    """Metadane indeksu wektorowego zapisywane obok pliku FAISS."""

    store_version: int = VECTOR_STORE_VERSION
    dimension: int = 0
    model_key: str = ""
    model_version: str = ""
    vector_compat_hash: str = ""
    metric: str = "inner_product"
    index_type: str = "hnsw"
    total_added: int = 0
    deleted_ids: list[int] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> VectorIndexMeta:
        data: dict[str, Any] = json.loads(raw)
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


class VectorStore:
    """Trwaly magazyn wektorow fragmentow."""

    def __init__(self, index_path: Path, meta_path: Path) -> None:
        self.index_path = index_path
        self.meta_path = meta_path
        self._lock = threading.RLock()
        self._index: Any | None = None
        self._deleted: set[int] = set()
        self.meta = VectorIndexMeta()
        self._faiss: Any | None = None

    # --- zaleznosc na faiss ------------------------------------------------

    @property
    def faiss(self) -> Any:
        if self._faiss is None:
            import faiss

            self._faiss = faiss
        return self._faiss

    # --- cykl zycia --------------------------------------------------------

    def exists(self) -> bool:
        return self.index_path.exists() and self.meta_path.exists()

    def open(
        self,
        *,
        dimension: int,
        model_key: str,
        model_version: str,
        vector_compat_hash: str,
        create: bool = True,
    ) -> None:
        """Otwiera istniejacy indeks albo tworzy nowy.

        Rzuca ``IndexIncompatibleError``, gdy zapisane metadane nie zgadzaja sie
        z biezacym modelem. Indeks nie jest wtedy modyfikowany ani kasowany.
        """
        with self._lock:
            if self.exists():
                self._load()
                if self.meta.store_version != VECTOR_STORE_VERSION:
                    raise IndexIncompatibleError(
                        "Format indeksu wektorowego pochodzi z innej wersji aplikacji. "
                        "Wymagana jest przebudowa czesci semantycznej."
                    )
                if self.meta.dimension != dimension:
                    raise IndexIncompatibleError(
                        f"Indeks wektorowy ma wymiar {self.meta.dimension}, "
                        f"a wybrany model tworzy wektory o wymiarze {dimension}."
                    )
                if self.meta.vector_compat_hash != vector_compat_hash:
                    raise IndexIncompatibleError(
                        "Konfiguracja modelu albo fragmentacji zmienila sie od czasu "
                        "zbudowania indeksu wektorowego. Wymagana jest przebudowa."
                    )
                return

            if not create:
                raise IndexCorruptedError("Indeks wektorowy nie istnieje.")

            self._index = self._new_index(dimension)
            self._deleted = set()
            self.meta = VectorIndexMeta(
                dimension=dimension,
                model_key=model_key,
                model_version=model_version,
                vector_compat_hash=vector_compat_hash,
            )
            self.save()

    def _new_index(self, dimension: int) -> Any:
        faiss = self.faiss
        base = faiss.IndexHNSWFlat(dimension, HNSW_M, faiss.METRIC_INNER_PRODUCT)
        base.hnsw.efConstruction = HNSW_EF_CONSTRUCTION
        base.hnsw.efSearch = HNSW_EF_SEARCH
        return faiss.IndexIDMap2(base)

    def _load(self) -> None:
        try:
            self.meta = VectorIndexMeta.from_json(self.meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise IndexCorruptedError(
                "Nie udalo sie odczytac metadanych indeksu wektorowego.", cause=exc
            ) from exc
        try:
            self._index = self.faiss.read_index(str(self.index_path))
        except Exception as exc:
            raise IndexCorruptedError(
                "Plik indeksu wektorowego jest uszkodzony.", cause=exc
            ) from exc
        self._deleted = set(self.meta.deleted_ids)

    def close(self) -> None:
        with self._lock:
            self._index = None

    # --- zapis -------------------------------------------------------------

    def save(self) -> None:
        """Zapisuje indeks i metadane atomowo."""
        with self._lock:
            if self._index is None:
                return
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            self.meta.deleted_ids = sorted(self._deleted)
            self.meta.updated_at = _timestamp()
            if not self.meta.created_at:
                self.meta.created_at = self.meta.updated_at

            tmp_index = self.index_path.with_suffix(self.index_path.suffix + ".tmp")
            tmp_meta = self.meta_path.with_suffix(self.meta_path.suffix + ".tmp")
            self.faiss.write_index(self._index, str(tmp_index))
            tmp_meta.write_text(self.meta.to_json(), encoding="utf-8")
            _fsync(tmp_index)
            _fsync(tmp_meta)
            tmp_index.replace(self.index_path)
            tmp_meta.replace(self.meta_path)

    # --- operacje ----------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._index is not None

    @property
    def dimension(self) -> int:
        return self.meta.dimension

    def count(self) -> int:
        """Liczba aktywnych wektorow (bez nagrobkow)."""
        with self._lock:
            if self._index is None:
                return 0
            return max(0, int(self._index.ntotal) - len(self._deleted))

    def raw_count(self) -> int:
        with self._lock:
            return 0 if self._index is None else int(self._index.ntotal)

    def deleted_count(self) -> int:
        return len(self._deleted)

    def needs_compaction(self) -> bool:
        total = self.raw_count()
        if total == 0:
            return False
        return len(self._deleted) / total >= COMPACTION_THRESHOLD

    def add(self, ids: list[int], vectors: np.ndarray) -> None:
        """Dodaje wektory. ``vectors`` musi byc tablica float32 o ksztalcie (n, dim)."""
        if not ids:
            return
        with self._lock:
            if self._index is None:
                raise IndexCorruptedError("Indeks wektorowy nie jest otwarty.")
            array = np.ascontiguousarray(vectors, dtype="float32")
            if array.ndim != 2 or array.shape[1] != self.meta.dimension:
                raise IndexCorruptedError(
                    f"Oczekiwano wektorow o wymiarze {self.meta.dimension}, "
                    f"otrzymano ksztalt {array.shape}."
                )
            if array.shape[0] != len(ids):
                raise IndexCorruptedError(
                    "Liczba identyfikatorow nie zgadza sie z liczba wektorow."
                )
            id_array = np.asarray(ids, dtype="int64")
            # ponowne dodanie tego samego identyfikatora oznacza aktualizacje fragmentu
            for chunk_id in ids:
                self._deleted.discard(int(chunk_id))
            self._index.add_with_ids(array, id_array)
            self.meta.total_added += len(ids)

    def remove(self, ids: list[int]) -> None:
        """Oznacza wektory jako usuniete."""
        if not ids:
            return
        with self._lock:
            self._deleted.update(int(i) for i in ids)

    def search(
        self, query: np.ndarray, k: int, *, overfetch: float = 2.0
    ) -> list[tuple[int, float]]:
        """Zwraca liste par (chunk_id, podobienstwo), pomijajac nagrobki."""
        with self._lock:
            if self._index is None or self._index.ntotal == 0:
                return []
            wanted = max(1, k)
            fetch = min(
                int(self._index.ntotal), int(wanted * max(1.0, overfetch)) + len(self._deleted)
            )
            fetch = max(fetch, wanted)
            vector = np.ascontiguousarray(query.reshape(1, -1), dtype="float32")
            distances, indices = self._index.search(vector, fetch)

        results: list[tuple[int, float]] = []
        for score, chunk_id in zip(distances[0], indices[0], strict=False):
            cid = int(chunk_id)
            if cid < 0 or cid in self._deleted:
                continue
            results.append((cid, float(score)))
            if len(results) >= wanted:
                break
        return results

    def compact(self, active_ids: list[int], vectors: np.ndarray) -> None:
        """Buduje indeks od nowa z podanych aktywnych wektorow."""
        with self._lock:
            new_index = self._new_index(self.meta.dimension)
            if active_ids:
                array = np.ascontiguousarray(vectors, dtype="float32")
                new_index.add_with_ids(array, np.asarray(active_ids, dtype="int64"))
            self._index = new_index
            self._deleted = set()
            self.meta.total_added = len(active_ids)
            self.save()
        log.info("vector.compacted", vectors=len(active_ids))

    def reconstruct(self, chunk_id: int) -> np.ndarray | None:
        """Odtwarza wektor o podanym identyfikatorze, jesli istnieje."""
        with self._lock:
            if self._index is None or chunk_id in self._deleted:
                return None
            try:
                return np.asarray(self._index.reconstruct(int(chunk_id)), dtype="float32")
            except Exception:
                return None

    def reset(self) -> None:
        """Czysci indeks, zachowujac metadane modelu."""
        with self._lock:
            self._index = self._new_index(self.meta.dimension)
            self._deleted = set()
            self.meta.total_added = 0
            self.save()

    def size_bytes(self) -> int:
        total = 0
        for path in (self.index_path, self.meta_path):
            if path.exists():
                total += path.stat().st_size
        return total

    def describe(self) -> dict[str, Any]:
        return {
            "model": self.meta.model_key,
            "wersja_modelu": self.meta.model_version,
            "wymiar": self.meta.dimension,
            "typ_indeksu": self.meta.index_type,
            "metryka": self.meta.metric,
            "wektory_aktywne": self.count(),
            "wektory_wszystkie": self.raw_count(),
            "nagrobki": self.deleted_count(),
            "rozmiar_bajty": self.size_bytes(),
        }


def _timestamp() -> str:
    import datetime as dt

    return dt.datetime.now().astimezone().isoformat()


def _fsync(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:  # pragma: no cover - Windows moze odmowic otwarcia
        return
    try:
        os.fsync(fd)
    except OSError:  # pragma: no cover
        pass
    finally:
        os.close(fd)


__all__ = [
    "COMPACTION_THRESHOLD",
    "FLAT_INDEX_LIMIT",
    "HNSW_EF_CONSTRUCTION",
    "HNSW_EF_SEARCH",
    "HNSW_M",
    "VectorIndexMeta",
    "VectorStore",
]
