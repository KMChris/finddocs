"""Rozpoznawanie i normalizacja dat w tekstach polskich.

Kazda rozpoznana data trafia do indeksu jako token ``datRRRRMMDD``. Dzieki temu
zapytanie ``24.07.2015`` i zapytanie ``24 lipca 2015`` znajduja te same dokumenty,
niezaleznie od zapisu w zrodle.

Tokeny sa celowo czysto alfanumeryczne. Tokenizator FTS5 dzieli tekst na granicach
znakow interpunkcyjnych, wiec token z dwukropkiem albo myslnikiem rozpadlby sie
na kawalki i przestal pelnic swoja role.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass

from finddocs.normalization.text import fold_diacritics

DATE_TOKEN_PREFIX = "dat"
MONTH_TOKEN_PREFIX = "mon"
YEAR_TOKEN_PREFIX = "yea"

#: Nazwy miesiecy w mianowniku i dopelniaczu, w postaci zlozonej (bez diakrytykow).
MONTH_NAMES: dict[str, int] = {
    "styczen": 1,
    "stycznia": 1,
    "styczniu": 1,
    "sty": 1,
    "luty": 2,
    "lutego": 2,
    "lutym": 2,
    "lut": 2,
    "marzec": 3,
    "marca": 3,
    "marcu": 3,
    "mar": 3,
    "kwiecien": 4,
    "kwietnia": 4,
    "kwietniu": 4,
    "kwi": 4,
    "maj": 5,
    "maja": 5,
    "maju": 5,
    "czerwiec": 6,
    "czerwca": 6,
    "czerwcu": 6,
    "cze": 6,
    "lipiec": 7,
    "lipca": 7,
    "lipcu": 7,
    "lip": 7,
    "sierpien": 8,
    "sierpnia": 8,
    "sierpniu": 8,
    "sie": 8,
    "wrzesien": 9,
    "wrzesnia": 9,
    "wrzesniu": 9,
    "wrz": 9,
    "pazdziernik": 10,
    "pazdziernika": 10,
    "pazdzierniku": 10,
    "paz": 10,
    "listopad": 11,
    "listopada": 11,
    "listopadzie": 11,
    "lis": 11,
    "grudzien": 12,
    "grudnia": 12,
    "grudniu": 12,
    "gru": 12,
}

MONTH_LABELS_PL: tuple[str, ...] = (
    "stycznia",
    "lutego",
    "marca",
    "kwietnia",
    "maja",
    "czerwca",
    "lipca",
    "sierpnia",
    "wrzesnia",
    "pazdziernika",
    "listopada",
    "grudnia",
)

_MONTH_ALTERNATION = "|".join(sorted(MONTH_NAMES, key=len, reverse=True))

# 24.07.2015, 24-07-2015, 24/07/2015
_DMY_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
# 2015-07-24, 2015.07.24, 2015/07/24
_YMD_RE = re.compile(r"\b(\d{4})[./-](\d{1,2})[./-](\d{1,2})\b")
# 24.07.15 (dwucyfrowy rok)
_DMY_SHORT_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2})\b")
# 24 lipca 2015 / 24 lipca 2015 r.
_TEXTUAL_RE = re.compile(
    rf"\b(\d{{1,2}})\s+({_MONTH_ALTERNATION})\s+(\d{{4}})\b",
    re.IGNORECASE,
)
# lipiec 2015 (bez dnia)
_MONTH_YEAR_RE = re.compile(
    rf"\b({_MONTH_ALTERNATION})\s+(\d{{4}})\b",
    re.IGNORECASE,
)

#: Rok dwucyfrowy ponizej tego progu traktujemy jako 20xx, powyzej jako 19xx.
TWO_DIGIT_PIVOT = 40

MIN_YEAR = 1900
MAX_YEAR = 2099


@dataclass(frozen=True, slots=True)
class DateMatch:
    """Data rozpoznana w tekscie."""

    value: _dt.date
    raw: str
    span: tuple[int, int]
    precision: str = "day"
    """day albo month."""

    @property
    def token(self) -> str:
        if self.precision == "month":
            return f"{MONTH_TOKEN_PREFIX}{self.value.year:04d}{self.value.month:02d}"
        return f"{DATE_TOKEN_PREFIX}{self.value.year:04d}{self.value.month:02d}{self.value.day:02d}"


def _safe_date(year: int, month: int, day: int) -> _dt.date | None:
    if not (MIN_YEAR <= year <= MAX_YEAR):
        return None
    try:
        return _dt.date(year, month, day)
    except ValueError:
        return None


def _expand_two_digit_year(value: int) -> int:
    return 2000 + value if value < TWO_DIGIT_PIVOT else 1900 + value


def find_dates(text: str, *, folded: str | None = None) -> list[DateMatch]:
    """Znajduje wszystkie daty w tekscie. Zwraca liste posortowana po pozycji.

    ``folded`` przyjmuje gotowa postac zlozona TEGO SAMEGO tekstu. Potok
    normalizacji sklada fragment raz i podaje wynik wszystkim detektorom;
    bez tego ten sam fragment byl skladany cztery razy przy kazdym zapisie.
    """
    if not text:
        return []
    folded = (fold_diacritics(text) if folded is None else folded).lower()
    found: list[DateMatch] = []
    occupied: list[tuple[int, int]] = []

    def _overlaps(span: tuple[int, int]) -> bool:
        return any(span[0] < end and start < span[1] for start, end in occupied)

    def _add(match_span: tuple[int, int], date: _dt.date | None, precision: str = "day") -> None:
        if date is None or _overlaps(match_span):
            return
        occupied.append(match_span)
        found.append(
            DateMatch(
                value=date,
                raw=text[match_span[0] : match_span[1]],
                span=match_span,
                precision=precision,
            )
        )

    for m in _YMD_RE.finditer(folded):
        _add(m.span(), _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in _DMY_RE.finditer(folded):
        _add(m.span(), _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1))))
    for m in _TEXTUAL_RE.finditer(folded):
        month = MONTH_NAMES.get(m.group(2))
        if month is not None:
            _add(m.span(), _safe_date(int(m.group(3)), month, int(m.group(1))))
    for m in _DMY_SHORT_RE.finditer(folded):
        year = _expand_two_digit_year(int(m.group(3)))
        _add(m.span(), _safe_date(year, int(m.group(2)), int(m.group(1))))
    for m in _MONTH_YEAR_RE.finditer(folded):
        month = MONTH_NAMES.get(m.group(1))
        if month is not None:
            _add(m.span(), _safe_date(int(m.group(2)), month, 1), "month")

    found.sort(key=lambda d: d.span[0])
    return found


def date_tokens(text: str, *, folded: str | None = None) -> list[str]:
    """Tokeny dat do zapisania w polu wyszukiwawczym."""
    tokens: list[str] = []
    for match in find_dates(text, folded=folded):
        tokens.append(match.token)
        if match.precision == "day":
            tokens.append(f"{MONTH_TOKEN_PREFIX}{match.value.year:04d}{match.value.month:02d}")
        tokens.append(f"{YEAR_TOKEN_PREFIX}{match.value.year:04d}")
    # zachowujemy kolejnosc pierwszego wystapienia
    seen: set[str] = set()
    unique: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            unique.append(token)
    return unique


def format_variants(date: _dt.date) -> list[str]:
    """Warianty zapisu daty spotykane w polskich dokumentach."""
    day = date.day
    month = date.month
    year = date.year
    month_label = MONTH_LABELS_PL[month - 1]
    return [
        f"{day:02d}.{month:02d}.{year}",
        f"{day}.{month}.{year}",
        f"{year}-{month:02d}-{day:02d}",
        f"{day:02d}-{month:02d}-{year}",
        f"{day:02d}/{month:02d}/{year}",
        f"{day} {month_label} {year}",
    ]


def parse_single_date(text: str) -> _dt.date | None:
    """Probuje odczytac pojedyncza date z krotkiego napisu (np. z pola filtra)."""
    matches = find_dates(text.strip())
    return matches[0].value if matches else None


__all__ = [
    "DATE_TOKEN_PREFIX",
    "MONTH_LABELS_PL",
    "MONTH_NAMES",
    "MONTH_TOKEN_PREFIX",
    "YEAR_TOKEN_PREFIX",
    "DateMatch",
    "date_tokens",
    "find_dates",
    "format_variants",
    "parse_single_date",
]
