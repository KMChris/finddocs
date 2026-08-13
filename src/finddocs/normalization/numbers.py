"""Normalizacja numerow rachunkow, kwot, ciagow cyfr i identyfikatorow.

Wszystkie tokeny sa czysto alfanumeryczne, zeby przetrwaly tokenizacje FTS5:

* ``num0123456789``  dowolny ciag cyfr po usunieciu separatorow;
* ``accpl61109010140000071219812874``  numer rachunku w formacie IBAN;
* ``kwo31400``  kwota w groszach (314,00 zl);
* ``idffv201507123``  identyfikator alfanumeryczny bez separatorow;
* ``nip1234563218``, ``pes...``, ``reg...``  rozpoznane numery urzedowe.

Normalizacja nie modyfikuje tekstu zrodlowego. Tokeny trafiaja do osobnej kolumny
indeksu, obok pelnego tekstu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from finddocs.normalization.text import fold_diacritics

NUMBER_TOKEN_PREFIX = "num"
ACCOUNT_TOKEN_PREFIX = "acc"
AMOUNT_TOKEN_PREFIX = "kwo"
IDENTIFIER_TOKEN_PREFIX = "idf"
NIP_TOKEN_PREFIX = "nip"
REGON_TOKEN_PREFIX = "reg"
PESEL_TOKEN_PREFIX = "pes"

MIN_DIGITS_FOR_TOKEN = 4
MAX_DIGITS_FOR_TOKEN = 40
NRB_LENGTH = 26

#: Klasa znakow uzywanych jako separator tysiecy lub grup cyfr.
#: Spacja zwykla, nielamiaca, waska niclamiaca i cienka.
_SPACE_CLASS = r"    "

#: Waluty spotykane w polskich dokumentach finansowych (klucze w postaci zlozonej).
CURRENCY_WORDS: dict[str, str] = {
    "zl": "PLN",
    "zlote": "PLN",
    "zlotych": "PLN",
    "pln": "PLN",
    "eur": "EUR",
    "euro": "EUR",
    "usd": "USD",
    "chf": "CHF",
    "gbp": "GBP",
    "czk": "CZK",
}

_CURRENCY_ALTERNATION = "|".join(
    sorted((re.escape(c) for c in CURRENCY_WORDS), key=len, reverse=True)
)

# Ciag cyfr rozdzielony spacjami albo myslnikami, np. 01 2345 6789 lub 01-2345-6789.
# Separator musi byc spojny i nie moze byc otoczony spacjami, zeby regula nie skleila
# dwoch osobnych liczb rozdzielonych myslnikiem uzytym jako pauza.
_GROUPED_SPACE_RE = re.compile(
    rf"(?<![0-9A-Za-z])(\d{{1,6}}(?:[{_SPACE_CLASS}]\d{{1,6}}){{1,9}})(?![0-9A-Za-z])"
)
_GROUPED_DASH_RE = re.compile(r"(?<![0-9A-Za-z])(\d{1,6}(?:-\d{1,6}){1,9})(?![0-9A-Za-z])")
_PLAIN_DIGITS_RE = re.compile(r"(?<![0-9A-Za-z])(\d{4,})(?![0-9A-Za-z])")

# IBAN: dwie litery kraju, dwie cyfry kontrolne, dalej znaki alfanumeryczne.
_IBAN_RE = re.compile(r"\b([A-Z]{2})\s?(\d{2})[\s\-]?((?:[A-Z0-9][\s\-]?){10,30})\b")

# Kwota: 1 234,56 zl / 1.234,56 PLN / 314 zl / 314.00 EUR
_AMOUNT_RE = re.compile(
    rf"(?<![0-9])(\d{{1,3}}(?:[{_SPACE_CLASS}.]\d{{3}})+|\d+)"
    rf"(?:[,.](\d{{1,2}}))?[{_SPACE_CLASS}]*({_CURRENCY_ALTERNATION})\b",
    re.IGNORECASE,
)

# Identyfikatory: FV/2015/07/123, ABC-123456, 2015/KR/00012.
_LETTER = "A-Za-zÀ-ɏ"
_IDENTIFIER_RE = re.compile(
    rf"(?<![0-9{_LETTER}])"
    rf"(?=[{_LETTER}0-9/\-]*[0-9])"
    rf"(?=[{_LETTER}0-9/\-]*[{_LETTER}])"
    rf"([{_LETTER}0-9]{{1,12}}(?:[/\-][{_LETTER}0-9]{{1,12}}){{1,5}}|[{_LETTER}]{{2,6}}\d{{3,12}})"
    rf"(?![0-9{_LETTER}])"
)

_NIP_RE = re.compile(r"\bNIP[:\s]*((?:\d[\s\-]?){10})", re.IGNORECASE)
_REGON_RE = re.compile(r"\bREGON[:\s]*((?:\d[\s\-]?){9,14})", re.IGNORECASE)
_PESEL_RE = re.compile(r"\bPESEL[:\s]*((?:\d[\s\-]?){11})", re.IGNORECASE)

_SEPARATORS_RE = re.compile(r"[\s\-–—./\\_]")
_THOUSANDS_RE = re.compile(rf"[{_SPACE_CLASS}.]")


def strip_number_separators(text: str) -> str:
    """Usuwa spacje, myslniki, kropki i ukosniki z ciagu numerycznego."""
    return _SEPARATORS_RE.sub("", text)


@dataclass(frozen=True, slots=True)
class NumberMatch:
    """Rozpoznana wartosc numeryczna."""

    kind: str
    raw: str
    normalized: str
    token: str
    span: tuple[int, int]


def digit_variants(digits: str) -> list[str]:
    """Warianty zapisu ciagu cyfr uzywane przy budowie zapytania.

    Zwraca postac ciagla, grupowanie po cztery cyfry ze spacja i z myslnikiem
    oraz, dla numeru o dlugosci NRB, grupowanie typowe dla polskiego zapisu.
    """
    variants = [digits]
    if len(digits) >= 6:
        groups4 = " ".join(digits[i : i + 4] for i in range(0, len(digits), 4))
        variants.append(groups4)
        variants.append(groups4.replace(" ", "-"))
    if len(digits) == NRB_LENGTH:
        nrb = digits[:2] + " " + " ".join(digits[2 + i : 2 + i + 4] for i in range(0, 24, 4))
        variants.append(nrb)
        variants.append(nrb.replace(" ", "-"))
    seen: set[str] = set()
    unique: list[str] = []
    for variant in variants:
        if variant not in seen:
            seen.add(variant)
            unique.append(variant)
    return unique


def normalize_amount(integer_part: str, fraction_part: str | None) -> str | None:
    """Zwraca kwote w groszach jako napis, np. ``31400`` dla 314,00."""
    cleaned = _THOUSANDS_RE.sub("", integer_part)
    if not cleaned.isdigit():
        return None
    fraction = (fraction_part or "0").ljust(2, "0")[:2]
    try:
        value = Decimal(cleaned) * 100 + Decimal(fraction)
    except InvalidOperation:  # pragma: no cover - wejscie jest juz zwalidowane
        return None
    return str(int(value))


def find_amounts(text: str, *, folded: str | None = None) -> list[NumberMatch]:
    """Znajduje kwoty z jawna waluta.

    ``folded`` przyjmuje gotowa postac zlozona TEGO SAMEGO tekstu, zeby potok
    normalizacji nie skladal jednego fragmentu kilka razy.
    """
    results: list[NumberMatch] = []
    folded = fold_diacritics(text) if folded is None else folded
    for match in _AMOUNT_RE.finditer(folded):
        grosze = normalize_amount(match.group(1), match.group(2))
        if grosze is None:
            continue
        currency = CURRENCY_WORDS.get(match.group(3).lower(), match.group(3).upper())
        results.append(
            NumberMatch(
                kind="amount",
                raw=text[match.start() : match.end()],
                normalized=f"{int(grosze) / 100:.2f} {currency}",
                token=f"{AMOUNT_TOKEN_PREFIX}{grosze}",
                span=match.span(),
            )
        )
    return results


def find_ibans(text: str) -> list[NumberMatch]:
    """Znajduje numery IBAN (w tym polskie z prefiksem PL)."""
    results: list[NumberMatch] = []
    for match in _IBAN_RE.finditer(text.upper()):
        body = strip_number_separators(match.group(3))
        full = f"{match.group(1)}{match.group(2)}{body}"
        if not (15 <= len(full) <= 34) or not full[4:].isalnum():
            continue
        results.append(
            NumberMatch(
                kind="iban",
                raw=text[match.start() : match.end()],
                normalized=full,
                token=f"{ACCOUNT_TOKEN_PREFIX}{full.lower()}",
                span=match.span(),
            )
        )
    return results


def find_digit_sequences(text: str) -> list[NumberMatch]:
    """Znajduje ciagi cyfr, takze te rozdzielone spacjami lub myslnikami.

    Kazdy ciag o dlugosci co najmniej ``MIN_DIGITS_FOR_TOKEN`` dostaje token
    ``num<cyfry>``. Ciag o dlugosci NRB jest dodatkowo oznaczany jako rachunek.
    """
    results: list[NumberMatch] = []
    occupied: list[tuple[int, int]] = []

    def _overlaps(span: tuple[int, int]) -> bool:
        return any(span[0] < end and start < span[1] for start, end in occupied)

    for regex in (_GROUPED_SPACE_RE, _GROUPED_DASH_RE, _PLAIN_DIGITS_RE):
        for match in regex.finditer(text):
            span = match.span(1)
            if _overlaps(span):
                continue
            digits = strip_number_separators(match.group(1))
            if not digits.isdigit():
                continue
            if not (MIN_DIGITS_FOR_TOKEN <= len(digits) <= MAX_DIGITS_FOR_TOKEN):
                continue
            occupied.append(span)
            results.append(
                NumberMatch(
                    kind="account" if len(digits) == NRB_LENGTH else "digits",
                    raw=match.group(1),
                    normalized=digits,
                    token=f"{NUMBER_TOKEN_PREFIX}{digits}",
                    span=span,
                )
            )
    results.sort(key=lambda r: r.span[0])
    return results


def find_official_numbers(text: str) -> list[NumberMatch]:
    """Znajduje numery urzedowe poprzedzone etykieta: NIP, REGON, PESEL."""
    results: list[NumberMatch] = []
    for regex, kind, prefix in (
        (_NIP_RE, "nip", NIP_TOKEN_PREFIX),
        (_REGON_RE, "regon", REGON_TOKEN_PREFIX),
        (_PESEL_RE, "pesel", PESEL_TOKEN_PREFIX),
    ):
        for match in regex.finditer(text):
            digits = strip_number_separators(match.group(1))
            if not digits.isdigit():
                continue
            results.append(
                NumberMatch(
                    kind=kind,
                    raw=match.group(0),
                    normalized=digits,
                    token=f"{prefix}{digits}",
                    span=match.span(1),
                )
            )
    return results


def find_identifiers(text: str, *, folded: str | None = None) -> list[NumberMatch]:
    """Znajduje identyfikatory alfanumeryczne, np. FV/2015/07/123 albo ABC-12345.

    ``folded`` przyjmuje gotowa postac zlozona TEGO SAMEGO tekstu.
    """
    results: list[NumberMatch] = []
    folded = fold_diacritics(text) if folded is None else folded
    for match in _IDENTIFIER_RE.finditer(folded):
        raw = match.group(1)
        compact = re.sub(r"[^0-9A-Za-z]", "", raw).lower()
        if len(compact) < 4 or compact.isdigit():
            continue
        results.append(
            NumberMatch(
                kind="identifier",
                raw=text[match.start(1) : match.end(1)],
                normalized=compact,
                token=f"{IDENTIFIER_TOKEN_PREFIX}{compact}",
                span=match.span(1),
            )
        )
    return results


def find_all(text: str, *, folded: str | None = None) -> list[NumberMatch]:
    """Uruchamia wszystkie detektory i zwraca posortowana liste bez duplikatow tokenow.

    ``folded`` przyjmuje gotowa postac zlozona TEGO SAMEGO tekstu i jest
    przekazywana detektorom, ktore jej potrzebuja.
    """
    if not text:
        return []
    matches: list[NumberMatch] = []
    matches.extend(find_official_numbers(text))
    matches.extend(find_ibans(text))
    matches.extend(find_amounts(text, folded=folded))
    matches.extend(find_digit_sequences(text))
    matches.extend(find_identifiers(text, folded=folded))
    seen: set[str] = set()
    unique: list[NumberMatch] = []
    for match in sorted(matches, key=lambda m: (m.span[0], -len(m.token))):
        if match.token in seen:
            continue
        seen.add(match.token)
        unique.append(match)
    return unique


def number_tokens(text: str, *, folded: str | None = None) -> list[str]:
    """Same tokeny, w kolejnosci wystapienia."""
    return [m.token for m in find_all(text, folded=folded)]


def account_token(value: str) -> str | None:
    """Token rachunku dla wartosci wpisanej przez uzytkownika, albo None."""
    compact = strip_number_separators(value).upper()
    if compact.isdigit() and MIN_DIGITS_FOR_TOKEN <= len(compact) <= MAX_DIGITS_FOR_TOKEN:
        return f"{NUMBER_TOKEN_PREFIX}{compact}"
    if len(compact) >= 15 and compact[:2].isalpha() and compact[2:4].isdigit():
        return f"{ACCOUNT_TOKEN_PREFIX}{compact.lower()}"
    return None


__all__ = [
    "ACCOUNT_TOKEN_PREFIX",
    "AMOUNT_TOKEN_PREFIX",
    "CURRENCY_WORDS",
    "IDENTIFIER_TOKEN_PREFIX",
    "MAX_DIGITS_FOR_TOKEN",
    "MIN_DIGITS_FOR_TOKEN",
    "NIP_TOKEN_PREFIX",
    "NRB_LENGTH",
    "NUMBER_TOKEN_PREFIX",
    "PESEL_TOKEN_PREFIX",
    "REGON_TOKEN_PREFIX",
    "NumberMatch",
    "account_token",
    "digit_variants",
    "find_all",
    "find_amounts",
    "find_digit_sequences",
    "find_ibans",
    "find_identifiers",
    "find_official_numbers",
    "normalize_amount",
    "number_tokens",
    "strip_number_separators",
]
