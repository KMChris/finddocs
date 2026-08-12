"""Trwaly indeks: metadane, indeks pelnotekstowy FTS5 i wymienny indeks wektorowy.

Magazyn wektorow ma dwie implementacje o wspolnym protokole ``VectorIndex``:
lokalny plik FAISS oraz zewnetrzna baze PostgreSQL z rozszerzeniem pgvector.
"""

from __future__ import annotations

from finddocs.indexing.base import VectorIndex
from finddocs.indexing.db import Database
from finddocs.indexing.fts import FtsIndex, build_candidate_query, build_exact_query
from finddocs.indexing.maintenance import ConsistencyReport, check_consistency
from finddocs.indexing.migrations import migrate
from finddocs.indexing.pgvector import PgVectorStore
from finddocs.indexing.repository import Repository
from finddocs.indexing.service import IndexService, IndexStatus
from finddocs.indexing.vector import VectorStore
from finddocs.indexing.vector_factory import create_vector_store
from finddocs.indexing.writer import DocumentPayload, IndexWriter

__all__ = [
    "ConsistencyReport",
    "Database",
    "DocumentPayload",
    "FtsIndex",
    "IndexService",
    "IndexStatus",
    "IndexWriter",
    "PgVectorStore",
    "Repository",
    "VectorIndex",
    "VectorStore",
    "build_candidate_query",
    "build_exact_query",
    "check_consistency",
    "create_vector_store",
    "migrate",
]
