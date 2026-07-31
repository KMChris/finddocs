"""Warstwa wyszukiwania: analiza zapytania, tryby, scalanie i prezentacja."""

from __future__ import annotations

from finddocs.search.aggregate import (
    DocumentGroup,
    RankedCandidate,
    group_by_document,
    reciprocal_rank_fusion,
)
from finddocs.search.highlight import build_snippet, highlight_to_html, strip_highlight
from finddocs.search.query_parser import analyze_query, exact_tokens, highlight_terms
from finddocs.search.service import SearchService

__all__ = [
    "DocumentGroup",
    "RankedCandidate",
    "SearchService",
    "analyze_query",
    "build_snippet",
    "exact_tokens",
    "group_by_document",
    "highlight_terms",
    "highlight_to_html",
    "reciprocal_rank_fusion",
    "strip_highlight",
]
