"""Serwis wyszukiwania: tryb dokladny, semantyczny i hybrydowy.

Gwarancje:

* tryb dokladny zwraca dokladna liczbe pasujacych dokumentow i pozwala przejsc
  przez wszystkie, bez ukrytego limitu;
* tryb semantyczny jest jawnie oznaczony jako ranking przyblizony;
* tryb hybrydowy laczy obie listy metoda RRF, a elementy doslowne z zapytania
  pozostaja warunkiem obowiazkowym po stronie pelnotekstowej.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from finddocs.config import SearchSettings
from finddocs.errors import SearchCancelledError
from finddocs.indexing.fts import (
    FtsQuery,
    build_candidate_query,
    build_exact_query,
    build_filter_sql,
)
from finddocs.indexing.service import IndexService
from finddocs.logging_setup import get_logger
from finddocs.search.aggregate import (
    DocumentGroup,
    RankedCandidate,
    deduplicate_texts,
    group_by_document,
    normalize_scores,
    reciprocal_rank_fusion,
)
from finddocs.search.highlight import build_snippet
from finddocs.search.query_parser import analyze_query, exact_tokens, highlight_terms
from finddocs.types import (
    CancellationToken,
    ChunkHit,
    DocumentHit,
    DocumentStatus,
    MatchKind,
    QueryAnalysis,
    SearchFilters,
    SearchMode,
    SearchRequest,
    SearchResponse,
    SourceKind,
    TextOrigin,
)

log = get_logger(__name__)

#: Ponizej tej liczby dokumentow tryb hybrydowy wylicza pelna, dokladna liste.
HYBRID_FULL_ENUMERATION_LIMIT = 5000

#: Maksymalna liczba dokumentow w liscie hybrydowej, gdy trafien jest bardzo duzo.
HYBRID_MAX_DOCUMENTS = 1000

SEMANTIC_NOTE = (
    "Wyniki semantyczne to ranking przybliżony. Lista nie jest kompletnym zbiorem "
    "dokumentów powiązanych znaczeniowo z zapytaniem."
)
HYBRID_NOTE = (
    "Tryb hybrydowy łączy dopasowania dosłowne z podobieństwem znaczeniowym. "
    "Aby mieć pewność, że widzisz wszystkie dopasowania dosłowne, użyj trybu Dokładne."
)
TRUNCATED_NOTE = (
    "Zapytanie pasuje do bardzo wielu dokumentów. Lista została ograniczona. "
    "Zawęź zapytanie albo użyj filtrów."
)
NO_SEMANTIC_NOTE = "Indeks semantyczny jest niedostępny. Użyto wyłącznie wyszukiwania dokładnego."


@dataclass(slots=True)
class _DocRow:
    """Skrocone metadane dokumentu potrzebne do zbudowania wyniku."""

    row: sqlite3.Row


class SearchService:
    """Wykonuje zapytania uzytkownika na indeksie."""

    def __init__(self, index: IndexService, settings: SearchSettings | None = None) -> None:
        self.index = index
        self.settings = settings or index.config.search

    # --- wejscie ----------------------------------------------------------

    def search(
        self, request: SearchRequest, *, cancel: CancellationToken | None = None
    ) -> SearchResponse:
        started = time.perf_counter()
        analysis = analyze_query(request.query)
        if not analysis.raw_query:
            return SearchResponse(
                hits=[],
                total_documents=0,
                total_is_exact=True,
                mode=request.mode,
                took_ms=0,
                query_analysis=analysis,
            )

        filters = self._merge_date_filters(request.filters, analysis)
        mode = request.mode
        if mode is SearchMode.SEMANTIC and not self.index.semantic_available:
            mode = SearchMode.EXACT
        if mode is SearchMode.HYBRID and not self.index.semantic_available:
            mode = SearchMode.EXACT

        if mode is SearchMode.EXACT:
            response = self._search_exact(request, analysis, filters, cancel)
        elif mode is SearchMode.SEMANTIC:
            response = self._search_semantic(request, analysis, filters, cancel)
        else:
            response = self._search_hybrid(request, analysis, filters, cancel)

        if request.mode is not mode:
            response.notes.append(NO_SEMANTIC_NOTE)
        response.took_ms = int((time.perf_counter() - started) * 1000)
        return response

    # --- tryby ------------------------------------------------------------

    def _search_exact(
        self,
        request: SearchRequest,
        analysis: QueryAnalysis,
        filters: SearchFilters,
        cancel: CancellationToken | None,
    ) -> SearchResponse:
        query = build_exact_query(analysis)
        if query.is_empty():
            return self._empty(analysis, SearchMode.EXACT)

        total = self.index.fts.count_documents(query, filters)
        _raise_if_cancelled(cancel)
        matches = self.index.fts.search_documents(
            query,
            filters,
            limit=request.limit,
            offset=request.offset,
            order_by=request.order_by,
        )
        doc_ids = [m.doc_id for m in matches]
        chunk_map = self.index.fts.top_chunks_for_documents(
            query, doc_ids, per_document=max(1, request.max_chunks_per_document) * 3
        )
        counts = {m.doc_id: m.matching_chunks for m in matches}
        scores = {m.doc_id: -m.score for m in matches}

        hits = self._build_hits(
            doc_ids=doc_ids,
            chunk_map={d: [(c, -s) for c, s in v] for d, v in chunk_map.items()},
            analysis=analysis,
            match_kind=MatchKind.EXACT,
            max_chunks=request.max_chunks_per_document,
            matching_counts=counts,
            raw_scores=scores,
        )
        return SearchResponse(
            hits=hits,
            total_documents=total,
            total_is_exact=True,
            mode=SearchMode.EXACT,
            took_ms=0,
            query_analysis=analysis,
        )

    def _search_semantic(
        self,
        request: SearchRequest,
        analysis: QueryAnalysis,
        filters: SearchFilters,
        cancel: CancellationToken | None,
    ) -> SearchResponse:
        candidates = self._vector_candidates(analysis, filters, cancel)
        if not candidates:
            return self._empty(analysis, SearchMode.SEMANTIC, notes=[SEMANTIC_NOTE])

        ranked = [
            RankedCandidate(
                chunk_id=chunk_id,
                doc_id=doc_id,
                score=score,
                vector_rank=rank,
                vector_score=score,
            )
            for rank, (chunk_id, doc_id, score) in enumerate(candidates, start=1)
        ]
        groups = group_by_document(ranked, max_chunks=request.max_chunks_per_document)
        page = groups[request.offset : request.offset + request.limit]
        chunk_map = {g.doc_id: [(c.chunk_id, c.score) for c in g.candidates] for g in page}
        hits = self._build_hits(
            doc_ids=[g.doc_id for g in page],
            chunk_map=chunk_map,
            analysis=analysis,
            match_kind=MatchKind.SEMANTIC,
            max_chunks=request.max_chunks_per_document,
            matching_counts={g.doc_id: len(g.candidates) for g in page},
            raw_scores=normalize_scores(page),
        )
        return SearchResponse(
            hits=hits,
            total_documents=len(groups),
            total_is_exact=False,
            mode=SearchMode.SEMANTIC,
            took_ms=0,
            query_analysis=analysis,
            notes=[SEMANTIC_NOTE],
        )

    def _search_hybrid(
        self,
        request: SearchRequest,
        analysis: QueryAnalysis,
        filters: SearchFilters,
        cancel: CancellationToken | None,
    ) -> SearchResponse:
        notes = [HYBRID_NOTE]
        fts_query = build_candidate_query(analysis)
        fts_entries: list[tuple[int, int, float]] = []
        total_fts = 0
        if not fts_query.is_empty():
            total_fts = self.index.fts.count_documents(fts_query, filters)
            fts_entries = [
                (chunk_id, doc_id, -score)
                for chunk_id, doc_id, score in self.index.fts.search_chunks(
                    fts_query, filters, limit=self.settings.fts_candidates
                )
            ]
        _raise_if_cancelled(cancel)

        vector_entries = self._vector_candidates(analysis, filters, cancel)
        if not fts_entries and not vector_entries:
            return self._empty(analysis, SearchMode.HYBRID, notes=notes)

        fused = reciprocal_rank_fusion(
            [
                ("fts", fts_entries, self.settings.fts_weight),
                ("vector", vector_entries, self.settings.vector_weight),
            ],
            k=self.settings.rrf_k,
        )
        groups = group_by_document(fused, max_chunks=request.max_chunks_per_document)

        required = exact_tokens(analysis)
        if required:
            groups = self._boost_exact(groups, required)

        ordered_ids = [g.doc_id for g in groups]
        truncated = False
        if total_fts > len(ordered_ids):
            extra_limit = min(HYBRID_MAX_DOCUMENTS, HYBRID_FULL_ENUMERATION_LIMIT)
            spill = self.index.fts.search_documents(fts_query, filters, limit=extra_limit, offset=0)
            known = set(ordered_ids)
            for match in spill:
                if match.doc_id not in known:
                    ordered_ids.append(match.doc_id)
                    known.add(match.doc_id)
            truncated = total_fts > len(ordered_ids)
            if truncated:
                notes.append(TRUNCATED_NOTE)

        group_by_id = {g.doc_id: g for g in groups}
        page_ids = ordered_ids[request.offset : request.offset + request.limit]
        chunk_map: dict[int, list[tuple[int, float]]] = {}
        for doc_id in page_ids:
            group = group_by_id.get(doc_id)
            if group is not None:
                chunk_map[doc_id] = [(c.chunk_id, c.score) for c in group.candidates]
        missing = [d for d in page_ids if d not in chunk_map]
        if missing and not fts_query.is_empty():
            extra = self.index.fts.top_chunks_for_documents(
                fts_query, missing, per_document=request.max_chunks_per_document * 3
            )
            for doc_id, entries in extra.items():
                chunk_map[doc_id] = [(chunk_id, -score) for chunk_id, score in entries]

        page_groups = [group_by_id[d] for d in page_ids if d in group_by_id]
        scores = normalize_scores(page_groups)
        hits = self._build_hits(
            doc_ids=page_ids,
            chunk_map=chunk_map,
            analysis=analysis,
            match_kind=MatchKind.HYBRID,
            max_chunks=request.max_chunks_per_document,
            matching_counts={d: len(chunk_map.get(d, [])) for d in page_ids},
            raw_scores=scores,
        )
        return SearchResponse(
            hits=hits,
            total_documents=max(total_fts, len(ordered_ids)),
            total_is_exact=bool(required) and not truncated,
            mode=SearchMode.HYBRID,
            took_ms=0,
            query_analysis=analysis,
            truncated=truncated,
            notes=notes,
        )

    # --- czesc wektorowa --------------------------------------------------

    def _vector_candidates(
        self,
        analysis: QueryAnalysis,
        filters: SearchFilters,
        cancel: CancellationToken | None,
    ) -> list[tuple[int, int, float]]:
        if not self.index.semantic_available:
            return []
        provider = self.index.provider
        store = self.index.vector_store
        if provider is None or store is None:
            return []
        _raise_if_cancelled(cancel)
        vector = provider.embed_query(analysis.semantic_text)
        wanted = max(self.settings.semantic_candidates, 50)
        raw = store.search(vector, wanted, overfetch=2.5)
        if not raw:
            return []
        chunk_ids = [chunk_id for chunk_id, _ in raw]
        allowed = self._filter_chunks(chunk_ids, filters)
        result: list[tuple[int, int, float]] = []
        for chunk_id, score in raw:
            doc_id = allowed.get(chunk_id)
            if doc_id is None:
                continue
            result.append((chunk_id, doc_id, score))
        return result

    def _filter_chunks(self, chunk_ids: list[int], filters: SearchFilters) -> dict[int, int]:
        """Mapuje fragmenty na dokumenty, odrzucajac te odfiltrowane albo usuniete."""
        if not chunk_ids:
            return {}
        condition = build_filter_sql(filters)
        result: dict[int, int] = {}
        batch = 400
        for start in range(0, len(chunk_ids), batch):
            part = chunk_ids[start : start + batch]
            placeholders = ",".join("?" * len(part))
            sql = (
                "SELECT c.chunk_id AS chunk_id, c.doc_id AS doc_id FROM chunks c"
                " JOIN documents d ON d.doc_id = c.doc_id"
                f" WHERE c.chunk_id IN ({placeholders}) AND " + condition.sql
            )
            rows = self.index.db.query_all(sql, [*part, *condition.params])
            for row in rows:
                result[int(row["chunk_id"])] = int(row["doc_id"])
        return result

    def _boost_exact(self, groups: list[DocumentGroup], required: list[str]) -> list[DocumentGroup]:
        """Podnosi dokumenty zawierajace wszystkie elementy doslowne z zapytania."""
        doc_ids = [g.doc_id for g in groups]
        found = self.index.fts.documents_containing_tokens(required, doc_ids)
        boost = self.settings.exact_boost
        best = max((g.score for g in groups), default=1.0) or 1.0
        for group in groups:
            hits = len(found.get(group.doc_id, []))
            if hits:
                group.score += best * boost * (hits / len(required))
        groups.sort(key=lambda g: (-g.score, g.doc_id))
        return groups

    # --- budowa wynikow ---------------------------------------------------

    def _build_hits(
        self,
        *,
        doc_ids: list[int],
        chunk_map: dict[int, list[tuple[int, float]]],
        analysis: QueryAnalysis,
        match_kind: MatchKind,
        max_chunks: int,
        matching_counts: dict[int, int],
        raw_scores: dict[int, float],
    ) -> list[DocumentHit]:
        if not doc_ids:
            return []
        documents = self.index.repository.get_documents(doc_ids)
        all_chunk_ids = [cid for entries in chunk_map.values() for cid, _ in entries]
        chunk_rows = self.index.repository.chunk_texts(all_chunk_ids)
        terms = highlight_terms(analysis)
        source_kinds = self._source_kinds()

        hits: list[DocumentHit] = []
        for doc_id in doc_ids:
            record = documents.get(doc_id)
            if record is None:
                continue
            entries = chunk_map.get(doc_id, [])
            ordered = [(cid, score) for cid, score in entries if cid in chunk_rows]
            texts = [(cid, str(chunk_rows[cid]["text"])) for cid, _ in ordered]
            kept = set(deduplicate_texts(texts))
            selected = [(cid, score) for cid, score in ordered if cid in kept][:max_chunks]

            chunk_hits: list[ChunkHit] = []
            for cid, score in selected:
                row = chunk_rows[cid]
                text = str(row["text"])
                snippet, _matched = build_snippet(
                    text, terms, max_chars=self.settings.snippet_chars
                )
                chunk_hits.append(
                    ChunkHit(
                        chunk_id=cid,
                        doc_id=doc_id,
                        ordinal=int(row["ordinal"]),
                        text=text,
                        highlighted=snippet,
                        score=float(score),
                        match_kind=match_kind,
                        origin=TextOrigin(row["origin"] or "native"),
                        ocr_confidence=row["ocr_confidence"],
                        page=row["page"],
                        sheet=row["sheet"],
                        row_start=row["row_start"],
                        heading=row["heading"],
                    )
                )

            if not chunk_hits and record.status is DocumentStatus.INDEXED:
                chunk_hits = []

            hits.append(
                DocumentHit(
                    doc_id=doc_id,
                    name=record.name,
                    logical_path=record.logical_path,
                    library=record.library,
                    source_id=record.source_id,
                    source_kind=source_kinds.get(record.source_id, SourceKind.LOCAL_DIR),
                    extension=record.extension,
                    mime_type=record.mime_type,
                    modified_at=record.modified_at,
                    indexed_at=record.indexed_at,
                    author=record.author,
                    web_url=record.web_url,
                    parent_url=record.parent_url,
                    local_path=record.local_path,
                    used_ocr=record.used_ocr,
                    ocr_confidence=record.ocr_confidence,
                    score=float(raw_scores.get(doc_id, 0.0)),
                    match_kind=match_kind,
                    chunks=chunk_hits,
                    total_matching_chunks=matching_counts.get(doc_id, len(chunk_hits)),
                )
            )
        return hits

    def _source_kinds(self) -> dict[str, SourceKind]:
        rows = self.index.db.query_all("SELECT source_id, kind FROM sources")
        result: dict[str, SourceKind] = {}
        for row in rows:
            try:
                result[str(row["source_id"])] = SourceKind(row["kind"])
            except ValueError:
                continue
        return result

    # --- pomocnicze -------------------------------------------------------

    def _merge_date_filters(self, filters: SearchFilters, analysis: QueryAnalysis) -> SearchFilters:
        """Dokleja zakresy dat rozpoznane w zapytaniu do filtrow uzytkownika."""
        if not analysis.date_filters or not filters.modified.is_empty():
            return filters
        merged = analysis.date_filters[0]
        return SearchFilters(
            sources=filters.sources,
            libraries=filters.libraries,
            path_prefix=filters.path_prefix,
            extensions=filters.extensions,
            authors=filters.authors,
            modified=merged,
            ocr_only=filters.ocr_only,
        )

    def _empty(
        self, analysis: QueryAnalysis, mode: SearchMode, notes: list[str] | None = None
    ) -> SearchResponse:
        return SearchResponse(
            hits=[],
            total_documents=0,
            total_is_exact=mode is SearchMode.EXACT,
            mode=mode,
            took_ms=0,
            query_analysis=analysis,
            notes=notes or [],
        )

    # --- eksport pelnej listy --------------------------------------------

    def all_matching_documents(self, query: str, filters: SearchFilters | None = None) -> list[int]:
        """Wszystkie dokumenty pasujace doslownie, bez paginacji.

        Uzywane przez eksport listy wynikow i testy kompletnosci.
        """
        analysis = analyze_query(query)
        fts_query: FtsQuery = build_exact_query(analysis)
        return self.index.fts.all_document_ids(fts_query, filters or SearchFilters())


def _raise_if_cancelled(cancel: CancellationToken | None) -> None:
    if cancel is not None and cancel.is_cancelled():
        raise SearchCancelledError()


__all__ = [
    "HYBRID_FULL_ENUMERATION_LIMIT",
    "HYBRID_MAX_DOCUMENTS",
    "HYBRID_NOTE",
    "NO_SEMANTIC_NOTE",
    "SEMANTIC_NOTE",
    "TRUNCATED_NOTE",
    "SearchService",
]
