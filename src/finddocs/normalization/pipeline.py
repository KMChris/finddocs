"""Potok normalizacji: z tekstu zrodlowego robi komplet pol wyszukiwawczych.

Wynik zawiera cztery reprezentacje tego samego fragmentu:

* ``display``  tekst dla uzytkownika, po delikatnym czyszczeniu Unicode;
* ``search``   tekst dla indeksu pelnotekstowego, z polskimi znakami;
* ``folded``   tekst po zlozeniu znakow diakrytycznych;
* ``tokens``   tokeny dat, kwot, numerow i identyfikatorow.

Tekst zrodlowy nigdy nie jest nadpisywany. Potok tylko dodaje reprezentacje.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from finddocs.normalization.dates import date_tokens
from finddocs.normalization.numbers import number_tokens
from finddocs.normalization.text import (
    clean_text,
    fold_diacritics,
    search_form,
)
from finddocs.version import NORMALIZATION_VERSION

MAX_TOKENS_PER_CHUNK = 400


@dataclass(slots=True)
class NormalizedText:
    """Komplet reprezentacji jednego fragmentu tekstu."""

    display: str
    search: str
    folded: str
    tokens: list[str] = field(default_factory=list)
    version: int = NORMALIZATION_VERSION

    @property
    def token_text(self) -> str:
        return " ".join(self.tokens)


def normalize(text: str, *, extract_tokens: bool = True) -> NormalizedText:
    """Przetwarza tekst przez pelny potok normalizacji.

    Skladanie znakow diakrytycznych dzieje sie raz, a wynik dostaja wszyscy,
    ktorzy go potrzebuja: pole ``folded`` i detektory tokenow. Wczesniej kazdy
    z nich skladal ten sam fragment od nowa.
    """
    display = clean_text(text)
    if not display:
        return NormalizedText(display="", search="", folded="", tokens=[])

    search = search_form(display)
    base = fold_diacritics(display)
    folded = base.casefold()

    tokens: list[str] = []
    if extract_tokens:
        seen: set[str] = set()
        for token in (
            *date_tokens(display, folded=base),
            *number_tokens(display, folded=base),
        ):
            if token in seen:
                continue
            seen.add(token)
            tokens.append(token)
            if len(tokens) >= MAX_TOKENS_PER_CHUNK:
                break

    return NormalizedText(display=display, search=search, folded=folded, tokens=tokens)


def normalize_for_query(text: str) -> NormalizedText:
    """Normalizacja zapytania uzytkownika. Zawsze wyciaga tokeny."""
    return normalize(text, extract_tokens=True)


__all__ = [
    "MAX_TOKENS_PER_CHUNK",
    "NORMALIZATION_VERSION",
    "NormalizedText",
    "normalize",
    "normalize_for_query",
]
