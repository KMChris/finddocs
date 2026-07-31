"""Trwaly indeks: metadane, indeks pelnotekstowy FTS5 i indeks wektorowy FAISS."""

from __future__ import annotations

from finddocs.indexing.db import Database
from finddocs.indexing.fts import FtsIndex, build_candidate_query, build_exact_query
from finddocs.indexing.maintenance import ConsistencyReport, check_consistency
from finddocs.indexing.migrations import migrate
from finddocs.indexing.repository import Repository
from finddocs.indexing.service import IndexService, IndexStatus
from finddocs.indexing.vector import VectorStore
from finddocs.indexing.writer import DocumentPayload, IndexWriter

__all__ = [
    "ConsistencyReport",
    "Database",
    "DocumentPayload",
    "FtsIndex",
    "IndexService",
    "IndexStatus",
    "IndexWriter",
    "Repository",
    "VectorStore",
    "build_candidate_query",
    "build_exact_query",
    "check_consistency",
    "migrate",
]
