"""Wyszukiwanie pelnotekstowe na indeksie SQLite FTS5.

Kluczowe wymaganie: wyszukiwanie dokladne musi udostepniac wszystkie pasujace
dokumenty. Dlatego zapytania licza pelna liczbe trafien osobnym ``COUNT``,
a strona wynikow jest pobierana przez ``LIMIT/OFFSET`` po deterministycznym
sortowaniu. Nigdzie nie ma ukrytego limitu w rodzaju "pierwsze 10".
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any

from finddocs.errors import QuerySyntaxError
from finddocs.indexing.db import Database
from finddocs.logging_setup import get_logger
from finddocs.normalization.text import fold_for_search
from finddocs.types import (
    DocumentStatus,
    QueryAnalysis,
    SearchFilters,
    TermKind,
)

log = get_logger(__name__)

#: Statusy dokumentow, ktore sa wyszukiwalne.
SEARCHABLE_STATUSES: tuple[str, ...] = (
    DocumentStatus.INDEXED.value,
    DocumentStatus.PARTIAL.value,
)

#: Wagi kolumn w funkcji bm25: tekst wazniejszy niz tokeny znormalizowane.
BM25_WEIGHT_FOLDED = 1.0
BM25_WEIGHT_NORM = 0.6

_FTS_SPECIAL = re.compile(r'["]')
_TOKEN_SAFE = re.compile(r"^[0-9a-z]+$")


def quote_fts(value: str) -> str:
    """Zamyka wartosc w cudzyslowie FTS5, podwajajac cudzyslowy w srodku."""
    return '"' + _FTS_SPECIAL.sub('""', value) + '"'


@dataclass(slots=True)
class FtsQuery:
    """Zapytanie do indeksu pelnotekstowego."""

    expression: str
    required_tokens: list[str] = field(default_factory=list)
    optional_words: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    is_strict: bool = True

    def is_empty(self) -> bool:
        return not self.expression.strip()


def _phrase_expression(phrase: str, column: str = "folded") -> str:
    folded = fold_for_search(phrase).strip()
    if not folded:
        return ""
    return f"{column} : {quote_fts(folded)}"


def _token_expression(token: str) -> str:
    safe = token.strip().casefold()
    if not _TOKEN_SAFE.match(safe):
        safe = re.sub(r"[^0-9a-z]", "", safe)
    if not safe:
        return ""
    return f"norm : {quote_fts(safe)}"


def _word_expression(word: str) -> str:
    folded = fold_for_search(word).strip()
    if not folded:
        return ""
    return f"folded : {quote_fts(folded)}"


def build_exact_query(analysis: QueryAnalysis) -> FtsQuery:
    """Zapytanie dla trybu dokladnego: wszystkie elementy musza wystapic."""
    clauses: list[str] = []
    required: list[str] = []
    phrases: list[str] = []
    words: list[str] = []

    for term in analysis.terms:
        if term.kind is TermKind.PHRASE:
            expr = _phrase_expression(term.raw)
            if expr:
                clauses.append(expr)
                phrases.append(term.raw)
            continue
        if term.kind is TermKind.FILENAME:
            expr = _phrase_expression(term.raw)
            if expr:
                clauses.append(f"({expr})")
                phrases.append(term.raw)
            continue
        if term.is_exact_required and term.kind in {
            TermKind.ACCOUNT,
            TermKind.AMOUNT,
            TermKind.DATE,
            TermKind.DIGITS,
            TermKind.IDENTIFIER,
        }:
            alternatives = [_token_expression(term.normalized)]
            # Wariant zapisany doslownie w tekscie, np. numer bez separatorow.
            # Dla dat pomijamy warianty: sa to tokeny miesiaca i roku, ktore
            # rozszerzylyby zapytanie o dokladna date na caly miesiac.
            if term.kind is not TermKind.DATE:
                for variant in term.variants:
                    if variant and variant.isalnum():
                        alternatives.append(_word_expression(variant))
            alternatives = [a for a in alternatives if a]
            if alternatives:
                clauses.append("(" + " OR ".join(alternatives) + ")")
                required.append(term.normalized)
            continue
        if term.kind is TermKind.WORD:
            expr = _word_expression(term.raw)
            if expr:
                clauses.append(expr)
                words.append(term.raw)

    return FtsQuery(
        expression=" AND ".join(clauses),
        required_tokens=required,
        optional_words=words,
        phrases=phrases,
        is_strict=True,
    )


def build_candidate_query(analysis: QueryAnalysis) -> FtsQuery:
    """Zapytanie dla trybu hybrydowego: elementy doslowne obowiazkowe, slowa opcjonalne.

    Frazy w cudzyslowie pozostaja obowiazkowe, bo uzytkownik wskazal je jawnie.
    """
    required_clauses: list[str] = []
    optional_clauses: list[str] = []
    required: list[str] = []
    phrases: list[str] = []
    words: list[str] = []

    for term in analysis.terms:
        if term.kind in {TermKind.PHRASE, TermKind.FILENAME}:
            expr = _phrase_expression(term.raw)
            if expr:
                required_clauses.append(expr)
                phrases.append(term.raw)
            continue
        if term.is_exact_required and term.kind in {
            TermKind.ACCOUNT,
            TermKind.AMOUNT,
            TermKind.DATE,
            TermKind.DIGITS,
            TermKind.IDENTIFIER,
        }:
            alternatives = [_token_expression(term.normalized)]
            if term.kind is not TermKind.DATE:
                for variant in term.variants:
                    if variant and variant.isalnum():
                        alternatives.append(_word_expression(variant))
            alternatives = [a for a in alternatives if a]
            if alternatives:
                required_clauses.append("(" + " OR ".join(alternatives) + ")")
                required.append(term.normalized)
            continue
        if term.kind is TermKind.WORD:
            expr = _word_expression(term.raw)
            if expr:
                optional_clauses.append(expr)
                words.append(term.raw)

    parts: list[str] = list(required_clauses)
    if optional_clauses:
        parts.append("(" + " OR ".join(optional_clauses) + ")")
    return FtsQuery(
        expression=" AND ".join(parts),
        required_tokens=required,
        optional_words=words,
        phrases=phrases,
        is_strict=False,
    )


@dataclass(slots=True)
class FilterSql:
    """Warunek SQL zbudowany z filtrow metadanych."""

    sql: str
    params: list[Any]


def build_filter_sql(filters: SearchFilters, *, alias: str = "d") -> FilterSql:
    """Buduje fragment WHERE dla filtrow metadanych."""
    clauses: list[str] = [
        f"{alias}.status IN ({','.join('?' * len(SEARCHABLE_STATUSES))})",
    ]
    params: list[Any] = list(SEARCHABLE_STATUSES)

    if filters.sources:
        clauses.append(f"{alias}.source_id IN ({','.join('?' * len(filters.sources))})")
        params.extend(filters.sources)
    if filters.libraries:
        clauses.append(f"{alias}.library IN ({','.join('?' * len(filters.libraries))})")
        params.extend(filters.libraries)
    if filters.extensions:
        normalized = [e if e.startswith(".") else f".{e}" for e in filters.extensions]
        clauses.append(f"{alias}.extension IN ({','.join('?' * len(normalized))})")
        params.extend([e.lower() for e in normalized])
    if filters.authors:
        clauses.append(f"{alias}.author IN ({','.join('?' * len(filters.authors))})")
        params.extend(filters.authors)
    if filters.path_prefix:
        clauses.append(f"{alias}.path_folded LIKE ?")
        params.append(fold_for_search(filters.path_prefix) + "%")
    if filters.modified.start is not None:
        clauses.append(f"{alias}.modified_at >= ?")
        params.append(_start_of_day(filters.modified.start))
    if filters.modified.end is not None:
        clauses.append(f"{alias}.modified_at <= ?")
        params.append(_end_of_day(filters.modified.end))
    if filters.ocr_only is True:
        clauses.append(f"{alias}.used_ocr = 1")
    elif filters.ocr_only is False:
        clauses.append(f"{alias}.used_ocr = 0")

    return FilterSql(sql=" AND ".join(clauses), params=params)


def _start_of_day(day: _dt.date) -> str:
    return _dt.datetime.combine(day, _dt.time.min).astimezone().isoformat()


def _end_of_day(day: _dt.date) -> str:
    return _dt.datetime.combine(day, _dt.time.max).astimezone().isoformat()


@dataclass(slots=True)
class DocumentMatch:
    """Dokument dopasowany przez indeks pelnotekstowy."""

    doc_id: int
    score: float
    matching_chunks: int


class FtsIndex:
    """Operacje wyszukiwania na indeksie pelnotekstowym."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # --- liczenie ---------------------------------------------------------

    def count_documents(self, query: FtsQuery, filters: SearchFilters) -> int:
        """Dokladna liczba dokumentow spelniajacych zapytanie."""
        if query.is_empty():
            return 0
        condition = build_filter_sql(filters)
        sql = (
            "SELECT COUNT(*) FROM ("
            "  SELECT c.doc_id FROM chunks_fts"
            "  JOIN chunks c ON c.chunk_id = chunks_fts.rowid"
            "  JOIN documents d ON d.doc_id = c.doc_id"
            "  WHERE chunks_fts MATCH ? AND " + condition.sql + "  GROUP BY c.doc_id"
            ")"
        )
        params: list[Any] = [query.expression, *condition.params]
        return int(self._scalar(sql, params, query.expression))

    def count_chunks(self, query: FtsQuery, filters: SearchFilters) -> int:
        if query.is_empty():
            return 0
        condition = build_filter_sql(filters)
        sql = (
            "SELECT COUNT(*) FROM chunks_fts"
            " JOIN chunks c ON c.chunk_id = chunks_fts.rowid"
            " JOIN documents d ON d.doc_id = c.doc_id"
            " WHERE chunks_fts MATCH ? AND " + condition.sql
        )
        params: list[Any] = [query.expression, *condition.params]
        return int(self._scalar(sql, params, query.expression))

    # --- wyszukiwanie -----------------------------------------------------

    def search_documents(
        self,
        query: FtsQuery,
        filters: SearchFilters,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[DocumentMatch]:
        """Strona wynikow na poziomie dokumentu, posortowana wedlug bm25."""
        if query.is_empty() or limit <= 0:
            return []
        condition = build_filter_sql(filters)
        # SQLite nie pozwala uzyc bm25 w zapytaniu z GROUP BY. Ranking liczymy wiec
        # w wyrazeniu CTE oznaczonym jako MATERIALIZED, zeby planer go nie splaszczyl,
        # a agregacje na poziomie dokumentu robimy warstwe wyzej.
        sql = (
            "WITH matched AS MATERIALIZED ("
            "  SELECT c.doc_id AS doc_id, bm25(chunks_fts, ?, ?) AS score"
            "  FROM chunks_fts"
            "  JOIN chunks c ON c.chunk_id = chunks_fts.rowid"
            "  JOIN documents d ON d.doc_id = c.doc_id"
            "  WHERE chunks_fts MATCH ? AND " + condition.sql + ")"
            " SELECT doc_id, MIN(score) AS score, COUNT(*) AS matching_chunks"
            " FROM matched GROUP BY doc_id"
            " ORDER BY score ASC, doc_id ASC"
            " LIMIT ? OFFSET ?"
        )
        params: list[Any] = [
            BM25_WEIGHT_FOLDED,
            BM25_WEIGHT_NORM,
            query.expression,
            *condition.params,
            limit,
            offset,
        ]
        rows = self._query(sql, params, query.expression)
        return [
            DocumentMatch(
                doc_id=int(r["doc_id"]),
                score=float(r["score"]),
                matching_chunks=int(r["matching_chunks"]),
            )
            for r in rows
        ]

    def all_document_ids(self, query: FtsQuery, filters: SearchFilters) -> list[int]:
        """Identyfikatory wszystkich pasujacych dokumentow, bez limitu.

        Uzywane przez eksport wynikow i testy kompletnosci.
        """
        if query.is_empty():
            return []
        condition = build_filter_sql(filters)
        sql = (
            "SELECT c.doc_id AS doc_id FROM chunks_fts"
            " JOIN chunks c ON c.chunk_id = chunks_fts.rowid"
            " JOIN documents d ON d.doc_id = c.doc_id"
            " WHERE chunks_fts MATCH ? AND " + condition.sql + " GROUP BY c.doc_id"
            " ORDER BY c.doc_id"
        )
        params: list[Any] = [query.expression, *condition.params]
        return [int(r["doc_id"]) for r in self._query(sql, params, query.expression)]

    def search_chunks(
        self,
        query: FtsQuery,
        filters: SearchFilters,
        *,
        limit: int,
    ) -> list[tuple[int, int, float]]:
        """Najlepsze fragmenty globalnie. Zwraca (chunk_id, doc_id, score)."""
        if query.is_empty() or limit <= 0:
            return []
        condition = build_filter_sql(filters)
        sql = (
            "SELECT chunks_fts.rowid AS chunk_id, c.doc_id AS doc_id,"
            "       bm25(chunks_fts, ?, ?) AS score"
            " FROM chunks_fts"
            " JOIN chunks c ON c.chunk_id = chunks_fts.rowid"
            " JOIN documents d ON d.doc_id = c.doc_id"
            " WHERE chunks_fts MATCH ? AND " + condition.sql + " ORDER BY score ASC LIMIT ?"
        )
        params: list[Any] = [
            BM25_WEIGHT_FOLDED,
            BM25_WEIGHT_NORM,
            query.expression,
            *condition.params,
            limit,
        ]
        rows = self._query(sql, params, query.expression)
        return [(int(r["chunk_id"]), int(r["doc_id"]), float(r["score"])) for r in rows]

    def top_chunks_for_documents(
        self,
        query: FtsQuery,
        doc_ids: list[int],
        *,
        per_document: int,
    ) -> dict[int, list[tuple[int, float]]]:
        """Najlepsze fragmenty w obrebie wskazanych dokumentow."""
        if query.is_empty() or not doc_ids:
            return {}
        placeholders = ",".join("?" * len(doc_ids))
        # Funkcja bm25 musi zostac policzona w najglebszym zapytaniu, bo SQLite nie
        # pozwala uzywac jej razem z funkcjami okna ani z GROUP BY.
        sql = (
            "WITH matched AS MATERIALIZED ("
            "  SELECT chunks_fts.rowid AS chunk_id, c.doc_id AS doc_id,"
            "         bm25(chunks_fts, ?, ?) AS score"
            "  FROM chunks_fts"
            "  JOIN chunks c ON c.chunk_id = chunks_fts.rowid"
            f"  WHERE chunks_fts MATCH ? AND c.doc_id IN ({placeholders})"
            ")"
            " SELECT chunk_id, doc_id, score FROM ("
            "  SELECT chunk_id, doc_id, score,"
            "         ROW_NUMBER() OVER (PARTITION BY doc_id ORDER BY score ASC) AS rn"
            "  FROM matched"
            ") WHERE rn <= ? ORDER BY doc_id, score ASC"
        )
        params: list[Any] = [
            BM25_WEIGHT_FOLDED,
            BM25_WEIGHT_NORM,
            query.expression,
            *doc_ids,
            per_document,
        ]
        result: dict[int, list[tuple[int, float]]] = {}
        for row in self._query(sql, params, query.expression):
            result.setdefault(int(row["doc_id"]), []).append(
                (int(row["chunk_id"]), float(row["score"]))
            )
        return result

    def matching_chunk_counts(self, query: FtsQuery, doc_ids: list[int]) -> dict[int, int]:
        """Liczba pasujacych fragmentow w kazdym dokumencie."""
        if query.is_empty() or not doc_ids:
            return {}
        placeholders = ",".join("?" * len(doc_ids))
        sql = (
            "SELECT c.doc_id AS doc_id, COUNT(*) AS n FROM chunks_fts"
            " JOIN chunks c ON c.chunk_id = chunks_fts.rowid"
            f" WHERE chunks_fts MATCH ? AND c.doc_id IN ({placeholders})"
            " GROUP BY c.doc_id"
        )
        params: list[Any] = [query.expression, *doc_ids]
        return {int(r["doc_id"]): int(r["n"]) for r in self._query(sql, params, query.expression)}

    def documents_containing_tokens(
        self, tokens: list[str], doc_ids: list[int]
    ) -> dict[int, list[str]]:
        """Sprawdza, ktore z wymaganych tokenow wystepuja w kazdym dokumencie."""
        if not tokens or not doc_ids:
            return {}
        placeholders = ",".join("?" * len(doc_ids))
        result: dict[int, list[str]] = {doc_id: [] for doc_id in doc_ids}
        for token in tokens:
            expression = _token_expression(token)
            if not expression:
                continue
            sql = (
                "SELECT DISTINCT c.doc_id AS doc_id FROM chunks_fts"
                " JOIN chunks c ON c.chunk_id = chunks_fts.rowid"
                f" WHERE chunks_fts MATCH ? AND c.doc_id IN ({placeholders})"
            )
            for row in self._query(sql, [expression, *doc_ids], expression):
                result[int(row["doc_id"])].append(token)
        return result

    # --- pomocnicze -------------------------------------------------------

    def _query(self, sql: str, params: list[Any], expression: str) -> list[Any]:
        import sqlite3

        try:
            return self.db.query_all(sql, params)
        except sqlite3.OperationalError as exc:
            raise QuerySyntaxError(
                "Nie udalo sie wykonac zapytania pelnotekstowego. "
                "Sprawdz, czy cudzyslowy w zapytaniu sa domkniete.",
                details={"expression": expression[:200]},
                cause=exc,
            ) from exc

    def _scalar(self, sql: str, params: list[Any], expression: str) -> Any:
        rows = self._query(sql, params, expression)
        return rows[0][0] if rows else 0


__all__ = [
    "BM25_WEIGHT_FOLDED",
    "BM25_WEIGHT_NORM",
    "SEARCHABLE_STATUSES",
    "DocumentMatch",
    "FilterSql",
    "FtsIndex",
    "FtsQuery",
    "build_candidate_query",
    "build_exact_query",
    "build_filter_sql",
    "quote_fts",
]
