"""Scalanie kandydatow i agregacja wynikow na poziomie dokumentu.

Metoda scalania: Reciprocal Rank Fusion. Dla kazdego kandydata liczymy sume
``waga / (k + pozycja)`` po wszystkich listach, w ktorych wystapil. RRF nie wymaga
kalibracji skal (bm25 i podobienstwo cosinusowe maja rozne zakresy), jest odporna
na wartosci odstajace i jest opisana w literaturze, wiec wynik da sie wytlumaczyc.

Po scaleniu fragmenty sa grupowane w dokumenty. Dla jednego dokumentu pokazujemy
kilka najlepszych, roznych fragmentow, zeby uzytkownik nie dostal kilkunastu
prawie identycznych trafien z tego samego pliku.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from finddocs.normalization.text import fold_for_search

#: Stala wygladzajaca RRF. Wartosc 60 jest przyjeta w literaturze jako rozsadny domyslny wybor.
DEFAULT_RRF_K = 60

#: Powyzej tego podobienstwa tekstowego dwa fragmenty uznajemy za powtorzenie.
DUPLICATE_SIMILARITY = 0.82


@dataclass(slots=True)
class RankedCandidate:
    """Kandydat po scaleniu list."""

    chunk_id: int
    doc_id: int
    score: float
    fts_rank: int | None = None
    vector_rank: int | None = None
    fts_score: float | None = None
    vector_score: float | None = None

    @property
    def from_fts(self) -> bool:
        return self.fts_rank is not None

    @property
    def from_vector(self) -> bool:
        return self.vector_rank is not None


def reciprocal_rank_fusion(
    lists: Sequence[tuple[str, Sequence[tuple[int, int, float]], float]],
    *,
    k: int = DEFAULT_RRF_K,
) -> list[RankedCandidate]:
    """Scala listy kandydatow metoda RRF.

    Kazdy element listy to krotka (nazwa_listy, pozycje, waga), gdzie pozycje to
    sekwencja (chunk_id, doc_id, wynik_wlasny) juz posortowana od najlepszego.
    """
    merged: dict[int, RankedCandidate] = {}
    for name, entries, weight in lists:
        for rank, (chunk_id, doc_id, own_score) in enumerate(entries, start=1):
            candidate = merged.get(chunk_id)
            if candidate is None:
                candidate = RankedCandidate(chunk_id=chunk_id, doc_id=doc_id, score=0.0)
                merged[chunk_id] = candidate
            candidate.score += weight / (k + rank)
            if name == "fts":
                candidate.fts_rank = rank
                candidate.fts_score = own_score
            elif name == "vector":
                candidate.vector_rank = rank
                candidate.vector_score = own_score
    ordered = sorted(merged.values(), key=lambda c: (-c.score, c.chunk_id))
    return ordered


@dataclass(slots=True)
class DocumentGroup:
    """Fragmenty jednego dokumentu wraz z laczna ocena."""

    doc_id: int
    score: float
    candidates: list[RankedCandidate] = field(default_factory=list)
    from_fts: bool = False
    from_vector: bool = False


def group_by_document(
    candidates: Iterable[RankedCandidate],
    *,
    max_chunks: int = 3,
    combine: str = "max_plus_tail",
) -> list[DocumentGroup]:
    """Grupuje kandydatow w dokumenty i porzadkuje dokumenty wedlug oceny.

    ``combine`` okresla sposob liczenia oceny dokumentu:

    * ``max`` bierze najlepszy fragment;
    * ``sum`` sumuje wszystkie fragmenty (faworyzuje dlugie dokumenty);
    * ``max_plus_tail`` bierze najlepszy fragment i dolicza malejacy udzial
      kolejnych, dzieki czemu dokument z wieloma trafieniami wygrywa z dokumentem
      z jednym, ale bez premii rosnacej bez ograniczen.
    """
    groups: dict[int, DocumentGroup] = {}
    for candidate in candidates:
        group = groups.get(candidate.doc_id)
        if group is None:
            group = DocumentGroup(doc_id=candidate.doc_id, score=0.0)
            groups[candidate.doc_id] = group
        group.candidates.append(candidate)
        group.from_fts = group.from_fts or candidate.from_fts
        group.from_vector = group.from_vector or candidate.from_vector

    for group in groups.values():
        group.candidates.sort(key=lambda c: (-c.score, c.chunk_id))
        scores = [c.score for c in group.candidates]
        if combine == "sum":
            group.score = sum(scores)
        elif combine == "max":
            group.score = max(scores)
        else:
            head = scores[0]
            tail = sum(s / (index + 2) for index, s in enumerate(scores[1:max_chunks]))
            group.score = head + tail

    ordered = sorted(groups.values(), key=lambda g: (-g.score, g.doc_id))
    for group in ordered:
        group.candidates = group.candidates[: max(1, max_chunks * 3)]
    return ordered


def _shingles(text: str, size: int = 5) -> set[str]:
    words = fold_for_search(text).split()
    if len(words) <= size:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + size]) for i in range(len(words) - size + 1)}


def similarity(left: str, right: str) -> float:
    """Podobienstwo dwoch fragmentow liczone na pieciowyrazowych oknach."""
    a = _shingles(left)
    b = _shingles(right)
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    return intersection / min(len(a), len(b))


def deduplicate_texts(
    items: Sequence[tuple[int, str]], *, threshold: float = DUPLICATE_SIMILARITY
) -> list[int]:
    """Zwraca identyfikatory fragmentow bez powtorzen tresci.

    Kolejnosc wejsciowa jest zachowana, wiec pierwszy (najlepszy) fragment zostaje.
    """
    kept: list[int] = []
    kept_texts: list[str] = []
    for identifier, text in items:
        if any(similarity(text, existing) >= threshold for existing in kept_texts):
            continue
        kept.append(identifier)
        kept_texts.append(text)
    return kept


def normalize_scores(groups: Sequence[DocumentGroup]) -> dict[int, float]:
    """Przelicza oceny na zakres 0..1 wzgledem najlepszego wyniku na stronie.

    Wartosc sluzy wylacznie do prezentacji jako sila dopasowania. Nie jest to
    prawdopodobienstwo ani miara bezwzgledna, co GUI komunikuje wprost.
    """
    if not groups:
        return {}
    best = max(g.score for g in groups)
    if best <= 0:
        return {g.doc_id: 0.0 for g in groups}
    return {g.doc_id: min(1.0, g.score / best) for g in groups}


__all__ = [
    "DEFAULT_RRF_K",
    "DUPLICATE_SIMILARITY",
    "DocumentGroup",
    "RankedCandidate",
    "deduplicate_texts",
    "group_by_document",
    "normalize_scores",
    "reciprocal_rank_fusion",
    "similarity",
]
