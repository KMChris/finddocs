"""Normalizacja tekstu, dat, kwot, numerow i identyfikatorow."""

from __future__ import annotations

from finddocs.normalization.dates import DateMatch, date_tokens, find_dates, parse_single_date
from finddocs.normalization.numbers import NumberMatch, find_all, number_tokens
from finddocs.normalization.pipeline import NormalizedText, normalize, normalize_for_query
from finddocs.normalization.text import (
    clean_text,
    fold_diacritics,
    fold_for_search,
    normalize_unicode,
    normalize_whitespace,
    search_form,
)

__all__ = [
    "DateMatch",
    "NormalizedText",
    "NumberMatch",
    "clean_text",
    "date_tokens",
    "find_all",
    "find_dates",
    "fold_diacritics",
    "fold_for_search",
    "normalize",
    "normalize_for_query",
    "normalize_unicode",
    "normalize_whitespace",
    "number_tokens",
    "parse_single_date",
    "search_form",
]
