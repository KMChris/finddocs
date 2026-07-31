"""Wyroznianie trafien i budowa fragmentow prezentowanych uzytkownikowi.

Tekst pokazywany uzytkownikowi zachowuje oryginalna pisownie, wraz z polskimi
znakami. Dopasowanie odbywa sie na wersji zlozonej, wiec ``Łódź`` zostanie
podswietlone takze przy zapytaniu ``lodz``. Mapa pozycji pozwala przeniesc
zakresy z wersji zlozonej z powrotem na tekst oryginalny.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from finddocs.normalization.numbers import strip_number_separators
from finddocs.normalization.text import SPECIAL_FOLD

HIGHLIGHT_OPEN = "[[hl]]"
HIGHLIGHT_CLOSE = "[[/hl]]"

DEFAULT_SNIPPET_CHARS = 320
CONTEXT_BEFORE = 90


@dataclass(slots=True)
class FoldedText:
    """Tekst zlozony wraz z mapa pozycji na tekst oryginalny."""

    text: str
    positions: list[int]

    def origin_span(self, start: int, end: int) -> tuple[int, int]:
        if not self.positions:
            return (0, 0)
        start = max(0, min(start, len(self.positions) - 1))
        end = max(start + 1, min(end, len(self.positions)))
        origin_start = self.positions[start]
        origin_end = self.positions[end - 1] + 1
        return (origin_start, origin_end)


def fold_with_positions(text: str) -> FoldedText:
    """Sklada znaki diakrytyczne, zapamietujac pozycje w tekscie zrodlowym."""
    folded_chars: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(text):
        replacement = SPECIAL_FOLD.get(char)
        if replacement is None:
            decomposed = unicodedata.normalize("NFKD", char)
            replacement = "".join(c for c in decomposed if not unicodedata.combining(c))
        if not replacement:
            replacement = char
        lowered = replacement.casefold()
        for piece in lowered:
            folded_chars.append(piece)
            positions.append(index)
    return FoldedText(text="".join(folded_chars), positions=positions)


def _term_patterns(terms: list[str]) -> list[re.Pattern[str]]:
    """Buduje wzorce dopasowania dla wyrazen wyszukiwania."""
    patterns: list[re.Pattern[str]] = []
    seen: set[str] = set()
    for term in terms:
        folded = fold_with_positions(term).text.strip()
        if not folded or folded in seen:
            continue
        seen.add(folded)
        words = [w for w in re.split(r"[^0-9a-z]+", folded) if w]
        if not words:
            continue
        if len(words) == 1:
            word = words[0]
            body = re.escape(word)
            # numer moze byc zapisany z separatorami, dopuszczamy je miedzy cyframi
            if word.isdigit() and len(word) >= 6:
                body = r"[\s\-]?".join(re.escape(d) for d in word)
            patterns.append(re.compile(rf"(?<![0-9a-z]){body}(?![0-9a-z])"))
        else:
            body = r"[^0-9a-z]{1,4}".join(re.escape(w) for w in words)
            patterns.append(re.compile(rf"(?<![0-9a-z]){body}(?![0-9a-z])"))
    return patterns


def find_matches(text: str, terms: list[str]) -> list[tuple[int, int]]:
    """Zwraca zakresy w tekscie oryginalnym, ktore odpowiadaja wyrazeniom."""
    if not text or not terms:
        return []
    folded = fold_with_positions(text)
    spans: list[tuple[int, int]] = []
    for pattern in _term_patterns(terms):
        for match in pattern.finditer(folded.text):
            spans.append(folded.origin_span(match.start(), match.end()))
    return _merge_spans(spans)


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not spans:
        return []
    ordered = sorted(spans)
    merged: list[tuple[int, int]] = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def apply_highlight(text: str, spans: list[tuple[int, int]]) -> str:
    """Wstawia znaczniki wyroznienia w podane zakresy."""
    if not spans:
        return text
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        if start < cursor:
            continue
        pieces.append(text[cursor:start])
        pieces.append(HIGHLIGHT_OPEN)
        pieces.append(text[start:end])
        pieces.append(HIGHLIGHT_CLOSE)
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def build_snippet(
    text: str,
    terms: list[str],
    *,
    max_chars: int = DEFAULT_SNIPPET_CHARS,
    context_before: int = CONTEXT_BEFORE,
) -> tuple[str, bool]:
    """Buduje fragment wokol pierwszego trafienia i wyroznia dopasowania.

    Zwraca (tekst_z_wyroznieniem, czy_znaleziono_trafienie).
    """
    cleaned = text.strip()
    if not cleaned:
        return "", False

    spans = find_matches(cleaned, terms)
    if not spans:
        body = cleaned[:max_chars]
        suffix = "..." if len(cleaned) > max_chars else ""
        return body + suffix, False

    first_start, _first_end = spans[0]
    start = max(0, first_start - context_before)
    end = min(len(cleaned), start + max_chars)
    if end - start < max_chars:
        start = max(0, end - max_chars)

    start = _word_boundary(cleaned, start, forward=True)
    end = _word_boundary(cleaned, end, forward=False)

    window = cleaned[start:end]
    local_spans = [
        (s - start, e - start) for s, e in spans if s >= start and e <= end
    ]
    highlighted = apply_highlight(window, local_spans)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(cleaned) else ""
    return f"{prefix}{highlighted}{suffix}", True


def _word_boundary(text: str, index: int, *, forward: bool) -> int:
    """Przesuwa indeks do najblizszej granicy slowa, zeby nie ucinac wyrazu."""
    if index <= 0:
        return 0
    if index >= len(text):
        return len(text)
    limit = 25
    step = 1 if forward else -1
    position = index
    for _ in range(limit):
        if position <= 0 or position >= len(text):
            break
        if text[position].isspace():
            return position + (1 if forward else 0)
        position += step
    return index


def contains_all_terms(text: str, terms: list[str]) -> bool:
    """Czy tekst zawiera wszystkie podane wyrazenia (po zlozeniu znakow)."""
    if not terms:
        return True
    folded = fold_with_positions(text).text
    compact = strip_number_separators(folded)
    for term in terms:
        term_folded = fold_with_positions(term).text.strip()
        if not term_folded:
            continue
        if term_folded in folded:
            continue
        if strip_number_separators(term_folded) in compact:
            continue
        return False
    return True


def strip_highlight(text: str) -> str:
    """Usuwa znaczniki wyroznienia, np. przed skopiowaniem tekstu."""
    return text.replace(HIGHLIGHT_OPEN, "").replace(HIGHLIGHT_CLOSE, "")


def highlight_to_html(text: str) -> str:
    """Zamienia znaczniki na proste tagi HTML uzywane w widoku wynikow."""
    import html as _html

    escaped = _html.escape(text, quote=False)
    escaped = escaped.replace(_html.escape(HIGHLIGHT_OPEN), "<mark>")
    escaped = escaped.replace(_html.escape(HIGHLIGHT_CLOSE), "</mark>")
    return escaped


__all__ = [
    "CONTEXT_BEFORE",
    "DEFAULT_SNIPPET_CHARS",
    "HIGHLIGHT_CLOSE",
    "HIGHLIGHT_OPEN",
    "FoldedText",
    "apply_highlight",
    "build_snippet",
    "contains_all_terms",
    "find_matches",
    "fold_with_positions",
    "highlight_to_html",
    "strip_highlight",
]
