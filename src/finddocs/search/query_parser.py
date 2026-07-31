"""Analiza zapytania uzytkownika.

Zapytanie w naturalnym jezyku czesto miesza dwie rzeczy: opis znaczeniowy
("procedura dotyczaca przelewow") i wartosc doslowna ("24.07.2015"). Analizator
rozdziela te warstwy. Wartosci doslowne trafiaja do wyszukiwania dokladnego jako
tokeny znormalizowane, a caly tekst zapytania idzie do embeddingu.

Element rozpoznany jako doslowny nigdy nie jest zastepowany samym embeddingiem.
"""

from __future__ import annotations

import itertools
import re

from finddocs.normalization.dates import (
    DATE_TOKEN_PREFIX,
    MONTH_TOKEN_PREFIX,
    YEAR_TOKEN_PREFIX,
    find_dates,
)
from finddocs.normalization.numbers import (
    NUMBER_TOKEN_PREFIX,
    find_amounts,
    find_ibans,
    find_identifiers,
    find_official_numbers,
    strip_number_separators,
)
from finddocs.normalization.text import clean_text, fold_for_search
from finddocs.types import DateRange, QueryAnalysis, QueryTerm, TermKind

_QUOTED_RE = re.compile(r'"([^"]{1,300})"|„([^”]{1,300})”')
_FILENAME_RE = re.compile(
    r"\b([\w\-. ]{1,80}\.(?:pdf|docx?|xlsx?|xlsm|csv|tsv|txt|eml|msg|png|jpe?g|tiff?|rtf|html?))\b",
    re.IGNORECASE,
)
_DIGIT_RUN_RE = re.compile(r"(?<![0-9A-Za-z])(\d[\d\s \-]{2,}\d|\d{4,})(?![0-9A-Za-z])")
_RANGE_SEPARATORS = ("-", "do", "od", "..", "–")

#: Slowa, ktore wskazuja na pytanie w jezyku naturalnym.
_QUESTION_WORDS = frozenset(
    {
        "co",
        "czy",
        "jak",
        "jaka",
        "jakie",
        "jaki",
        "jakich",
        "kto",
        "kiedy",
        "gdzie",
        "dlaczego",
        "ile",
        "podaj",
        "wyszukaj",
        "znajdz",
        "pokaz",
        "wymien",
        "opisz",
    }
)

#: Slowa nieniosace tresci, usuwane z czesci semantycznej gdy zapytanie jest dlugie.
_STOPWORDS = frozenset(
    {
        "i",
        "oraz",
        "w",
        "na",
        "z",
        "ze",
        "do",
        "od",
        "o",
        "a",
        "the",
        "dla",
        "przez",
        "po",
        "za",
        "przy",
        "jest",
        "byl",
        "byla",
        "sie",
    }
)

MIN_WORD_LENGTH = 2


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _extract_quoted(query: str) -> tuple[list[tuple[str, tuple[int, int]]], str]:
    """Wyciaga frazy w cudzyslowie. Zwraca liste fraz i zapytanie bez cudzyslowow."""
    phrases: list[tuple[str, tuple[int, int]]] = []
    pieces: list[str] = []
    last = 0
    for match in _QUOTED_RE.finditer(query):
        body = (match.group(1) or match.group(2) or "").strip()
        if body:
            phrases.append((body, match.span()))
        pieces.append(query[last : match.start()])
        pieces.append(" " + body + " ")
        last = match.end()
    pieces.append(query[last:])
    return phrases, "".join(pieces)


def _detect_date_ranges(query: str) -> list[DateRange]:
    """Rozpoznaje zakresy dat w rodzaju 'od 01.01.2015 do 31.12.2015'."""
    dates = find_dates(query)
    if len(dates) < 2:
        return []
    ranges: list[DateRange] = []
    lowered = fold_for_search(query)
    for first, second in itertools.pairwise(dates):
        between = lowered[first.span[1] : second.span[0]].strip()
        if len(between) > 12:
            continue
        if between and not any(sep in between for sep in _RANGE_SEPARATORS):
            continue
        start, end = sorted((first.value, second.value))
        ranges.append(DateRange(start=start, end=end))
    return ranges


def analyze_query(query: str) -> QueryAnalysis:
    """Rozklada zapytanie na czesc doslowna i czesc semantyczna."""
    raw = query.strip()
    if not raw:
        return QueryAnalysis(raw_query="", normalized_query="", semantic_text="")

    cleaned = clean_text(raw)
    phrase_spans, without_quotes = _extract_quoted(cleaned)
    terms: list[QueryTerm] = []
    consumed: list[tuple[int, int]] = []

    def occupied(span: tuple[int, int]) -> bool:
        return any(span[0] < end and start < span[1] for start, end in consumed)

    # 1. frazy w cudzyslowie
    for body, span in phrase_spans:
        consumed.append(span)
        terms.append(
            QueryTerm(
                kind=TermKind.PHRASE,
                raw=body,
                normalized=fold_for_search(body),
                is_exact_required=True,
                span=span,
            )
        )

    # 2. nazwy plikow
    for match in _FILENAME_RE.finditer(without_quotes):
        if occupied(match.span()):
            continue
        consumed.append(match.span())
        value = match.group(1).strip()
        terms.append(
            QueryTerm(
                kind=TermKind.FILENAME,
                raw=value,
                normalized=fold_for_search(value),
                is_exact_required=True,
                span=match.span(),
            )
        )

    # 3. numery urzedowe i IBAN
    for found in (*find_official_numbers(without_quotes), *find_ibans(without_quotes)):
        if occupied(found.span):
            continue
        consumed.append(found.span)
        terms.append(
            QueryTerm(
                kind=TermKind.ACCOUNT,
                raw=found.raw,
                normalized=found.token,
                variants=(found.normalized,),
                is_exact_required=True,
                span=found.span,
            )
        )

    # 4. kwoty
    for found in find_amounts(without_quotes):
        if occupied(found.span):
            continue
        consumed.append(found.span)
        terms.append(
            QueryTerm(
                kind=TermKind.AMOUNT,
                raw=found.raw,
                normalized=found.token,
                variants=(found.normalized,),
                is_exact_required=True,
                span=found.span,
            )
        )

    # 5. daty. Data bedaca koncem rozpoznanego zakresu staje sie filtrem, nie
    #    warunkiem doslownym: inaczej zapytanie "od 01.01.2015 do 31.12.2015"
    #    wymagaloby, zeby obie daty wystapily w tym samym dokumencie.
    date_ranges = _detect_date_ranges(without_quotes)
    range_endpoints = {r.start for r in date_ranges if r.start} | {
        r.end for r in date_ranges if r.end
    }
    for date_match in find_dates(without_quotes):
        if occupied(date_match.span):
            continue
        consumed.append(date_match.span)
        is_endpoint = date_match.value in range_endpoints
        normalized = (
            date_match.token
            if date_match.precision == "day"
            else f"{MONTH_TOKEN_PREFIX}{date_match.value.year:04d}{date_match.value.month:02d}"
        )
        terms.append(
            QueryTerm(
                kind=TermKind.DATE_RANGE if is_endpoint else TermKind.DATE,
                raw=date_match.raw,
                normalized=normalized,
                variants=(
                    f"{MONTH_TOKEN_PREFIX}{date_match.value.year:04d}{date_match.value.month:02d}",
                    f"{YEAR_TOKEN_PREFIX}{date_match.value.year:04d}",
                ),
                is_exact_required=not is_endpoint,
                span=date_match.span,
            )
        )

    # 6. identyfikatory alfanumeryczne. Musza isc przed samymi ciagami cyfr,
    #    inaczej "FV/2015/07/123" rozpadloby sie na luzne liczby.
    for found in find_identifiers(without_quotes):
        if occupied(found.span):
            continue
        consumed.append(found.span)
        terms.append(
            QueryTerm(
                kind=TermKind.IDENTIFIER,
                raw=found.raw,
                normalized=found.token,
                variants=(fold_for_search(found.raw),),
                is_exact_required=True,
                span=found.span,
            )
        )

    # 7. ciagi cyfr, takze rozdzielone spacjami i myslnikami
    for match in _DIGIT_RUN_RE.finditer(without_quotes):
        if occupied(match.span(1)):
            continue
        digits = strip_number_separators(match.group(1))
        if not digits.isdigit() or len(digits) < 4:
            continue
        consumed.append(match.span(1))
        kind = TermKind.ACCOUNT if len(digits) >= 10 else TermKind.DIGITS
        terms.append(
            QueryTerm(
                kind=kind,
                raw=match.group(1),
                normalized=f"{NUMBER_TOKEN_PREFIX}{digits}",
                variants=(digits,),
                is_exact_required=True,
                span=match.span(1),
            )
        )

    # 8. pozostale slowa
    remainder = _mask(without_quotes, consumed)
    words = [w for w in re.findall(r"[0-9A-Za-zÀ-ɏ]+", remainder) if len(w) >= MIN_WORD_LENGTH]
    folded_words = _dedupe([fold_for_search(w) for w in words])
    for word in folded_words:
        terms.append(
            QueryTerm(kind=TermKind.WORD, raw=word, normalized=word, is_exact_required=False)
        )

    lowered_words = {w.casefold() for w in words}
    is_question = bool(lowered_words & _QUESTION_WORDS) or raw.rstrip().endswith("?")
    content_words = [w for w in folded_words if w not in _STOPWORDS]

    analysis = QueryAnalysis(
        raw_query=raw,
        normalized_query=fold_for_search(cleaned),
        semantic_text=cleaned,
        terms=terms,
        phrases=[p for p, _ in phrase_spans],
        date_filters=date_ranges,
        has_exact_elements=any(t.is_exact_required for t in terms),
        is_natural_language=is_question or len(content_words) >= 4,
    )
    return analysis


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    """Zastepuje wskazane zakresy spacjami, zeby nie analizowac ich ponownie."""
    if not spans:
        return text
    chars = list(text)
    for start, end in spans:
        for index in range(max(0, start), min(len(chars), end)):
            chars[index] = " "
    return "".join(chars)


def exact_tokens(analysis: QueryAnalysis) -> list[str]:
    """Tokeny znormalizowane, ktore musza wystapic w dokumencie."""
    tokens: list[str] = []
    for term in analysis.terms:
        if not term.is_exact_required:
            continue
        if term.kind in {
            TermKind.ACCOUNT,
            TermKind.AMOUNT,
            TermKind.DATE,
            TermKind.DIGITS,
            TermKind.IDENTIFIER,
        }:
            tokens.append(term.normalized)
    return _dedupe(tokens)


def highlight_terms(analysis: QueryAnalysis) -> list[str]:
    """Napisy, ktore nalezy wyroznic w prezentowanych fragmentach."""
    values: list[str] = []
    for term in analysis.terms:
        values.append(term.raw)
        values.extend(term.variants)
    values.extend(analysis.phrases)
    return _dedupe([v for v in values if v and len(v) >= MIN_WORD_LENGTH])


__all__ = [
    "DATE_TOKEN_PREFIX",
    "MIN_WORD_LENGTH",
    "analyze_query",
    "exact_tokens",
    "highlight_terms",
]
