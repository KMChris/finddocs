"""Normalizacja Unicode, bialych znakow i skladanie polskich znakow diakrytycznych.

Zasada nadrzedna: oryginalny tekst nigdy nie jest niszczony. Funkcje z tego modulu
tworza dodatkowe reprezentacje uzywane przez indeks, a tekst prezentowany
uzytkownikowi zachowuje pisownie ze zrodla.
"""

from __future__ import annotations

import re
import unicodedata

#: Znaki, ktore Unicode NFKD rozklada na litere i znak diakrytyczny, sa obslugiwane
#: automatycznie. Ponizsze litery to osobne znaki alfabetu i wymagaja mapy.
SPECIAL_FOLD: dict[str, str | int | None] = {
    "ł": "l",
    "Ł": "L",
    "đ": "d",
    "Đ": "D",
    "ø": "o",
    "Ø": "O",
    "æ": "ae",
    "Æ": "AE",
    "ß": "ss",
    "œ": "oe",
    "Œ": "OE",
    "þ": "th",
    "Þ": "TH",
    "ð": "d",
    "Ð": "D",
    "ħ": "h",
    "ı": "i",
}

#: Znaki interpunkcyjne, ktore w dokumentach biurowych wystepuja w wielu wariantach.
_PUNCTUATION_MAP: dict[str, str | int | None] = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "«": '"',
    "»": '"',
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    "‐": "-",
    "‑": "-",
    "­": "",
    "…": "...",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    "﻿": "",
    "​": "",
    "‌": "",
    "‍": "",
    " ": "\n",
    " ": "\n",
}

#: Tablice dla ``str.translate`` skladane raz przy imporcie. Wczesniej kazde
#: wywolanie budowalo tablice od nowa, choc mapy sa stale.
_SPECIAL_FOLD_TABLE = str.maketrans(SPECIAL_FOLD)
_PUNCTUATION_TABLE = str.maketrans(_PUNCTUATION_MAP)


class _CombiningTable(dict[int, int | None]):
    """Tablica dla ``str.translate``: usuwa znaki laczace, reszte zostawia.

    Skladanie znakow po rozkladzie NFKD to filtrowanie znak po znaku. Wykonane
    w Pythonie kosztowalo jedno wywolanie ``unicodedata.combining`` na znak
    tekstu. Tutaj decyzja zapada raz na punkt kodowy i zostaje zapamietana,
    a samo przejscie po tekscie robi ``str.translate`` w C.

    Slownik rosnie tylko o punkty kodowe faktycznie spotkane w dokumentach,
    wiec zajmuje setki wpisow, nie caly repertuar Unicode. Wartosc jest
    wyliczana z samego punktu kodowego, wiec rownolegle wejscie dwoch watkow
    daje ten sam wynik.
    """

    def __missing__(self, code: int) -> int | None:
        value = None if unicodedata.combining(chr(code)) else code
        self[code] = value
        return value


_COMBINING_TABLE = _CombiningTable()

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_SPACE_RE = re.compile(r"[ \t\f\r]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_TRAILING_SPACE_RE = re.compile(r"[ \t]+\n")
_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n(\w)")

#: Typowe pomylki OCR miedzy cyframi a literami, uzywane przy budowie wariantow.
OCR_CONFUSIONS: dict[str, tuple[str, ...]] = {
    "0": ("O", "o", "Q", "D"),
    "1": ("l", "I", "|", "i"),
    "2": ("Z", "z"),
    "5": ("S", "s"),
    "6": ("G", "b"),
    "8": ("B",),
    "9": ("g", "q"),
    "O": ("0",),
    "o": ("0",),
    "l": ("1",),
    "I": ("1",),
    "S": ("5",),
    "B": ("8",),
    "Z": ("2",),
}


def normalize_unicode(text: str) -> str:
    """Sprowadza tekst do postaci NFC i ujednolica interpunkcje.

    Nie zmienia liter ani cyfr. Wynik nadaje sie do pokazania uzytkownikowi.
    """
    if not text:
        return ""
    out = unicodedata.normalize("NFC", text)
    # Sprawdzenie idzie po mapie, nie po tekscie: kilkanascie szukan podnapisu
    # w C jest tansze niz przepisanie calego tekstu znak po znaku przez
    # ``translate`` (zmierzone: 0,009 ms wobec 0,072 ms na 3 kB).
    if any(ch in out for ch in _PUNCTUATION_MAP):
        out = out.translate(_PUNCTUATION_TABLE)
    return _CONTROL_RE.sub(" ", out)


def normalize_whitespace(text: str, *, keep_paragraphs: bool = True) -> str:
    """Ujednolica biale znaki.

    Przy ``keep_paragraphs`` zachowuje podzial na akapity (maksymalnie jedna pusta linia).
    """
    if not text:
        return ""
    out = text.replace("\r\n", "\n").replace("\r", "\n")
    out = _HYPHEN_BREAK_RE.sub(r"\1\2", out)
    out = _MULTI_SPACE_RE.sub(" ", out)
    out = _TRAILING_SPACE_RE.sub("\n", out)
    if keep_paragraphs:
        out = _MULTI_NEWLINE_RE.sub("\n\n", out)
    else:
        out = out.replace("\n", " ")
        out = _MULTI_SPACE_RE.sub(" ", out)
    return out.strip()


def clean_text(text: str) -> str:
    """Pelne czyszczenie tekstu zachowujace tresc: Unicode plus biale znaki."""
    return normalize_whitespace(normalize_unicode(text))


def fold_diacritics(text: str) -> str:
    """Sklada znaki diakrytyczne do postaci bazowej ASCII.

    Obsluguje polskie ``ł``, ktorego rozklad NFKD nie usuwa, bo nie jest to
    znak laczony tylko osobna litera alfabetu.

    Tekst czysto ASCII wraca bez zmian od razu: nie ma w nim ani znakow z mapy
    (wszystkie sa spoza ASCII), ani znakow laczacych, a NFKD go nie rusza.
    Wiekszosc fragmentow tabel i zestawien to wlasnie taki tekst.
    """
    if not text or text.isascii():
        return text
    # Petla idzie po mapie, nie po tekscie: kilkanascie szukan podnapisu w C
    # zamiast wywolania na kazdy znak fragmentu.
    if any(ch in text for ch in SPECIAL_FOLD):
        text = text.translate(_SPECIAL_FOLD_TABLE)
    decomposed = unicodedata.normalize("NFKD", text)
    return decomposed.translate(_COMBINING_TABLE)


def fold_for_search(text: str) -> str:
    """Postac uzywana w kolumnie odpornej na brak polskich znakow i bledy OCR."""
    return fold_diacritics(text).casefold()


def search_form(text: str) -> str:
    """Postac zapisywana w indeksie pelnotekstowym: czysta, ale z polskimi znakami."""
    return clean_text(text).casefold()


def looks_like_garbage(text: str, *, min_alpha_ratio: float = 0.45) -> bool:
    """Heurystyka wykrywajaca tekst uszkodzony albo zle zdekodowany.

    Zwraca True, gdy udzial liter i cyfr wsrod znakow niebialych jest zbyt niski
    albo gdy tekst zawiera duzo znakow zastepczych.
    """
    stripped = "".join(text.split())
    if not stripped:
        return True
    if stripped.count("�") / len(stripped) > 0.02:
        return True
    useful = sum(1 for ch in stripped if ch.isalnum())
    return (useful / len(stripped)) < min_alpha_ratio


def alpha_ratio(text: str) -> float:
    """Udzial znakow alfanumerycznych wsrod znakow niebialych."""
    stripped = "".join(text.split())
    if not stripped:
        return 0.0
    return sum(1 for ch in stripped if ch.isalnum()) / len(stripped)


def collapse_repeated_chars(text: str, max_run: int = 3) -> str:
    """Skraca dlugie serie tego samego znaku, typowe dla artefaktow OCR."""
    if not text:
        return ""
    out: list[str] = []
    run_char = ""
    run_len = 0
    for ch in text:
        if ch == run_char:
            run_len += 1
            if run_len > max_run:
                continue
        else:
            run_char = ch
            run_len = 1
        out.append(ch)
    return "".join(out)


def strip_separators(text: str) -> str:
    """Usuwa spacje, myslniki, kropki i ukosniki. Uzywane dla numerow i identyfikatorow."""
    return re.sub(r"[\s\-–—./\\_]", "", text)


def tokenize_words(text: str) -> list[str]:
    """Prosty podzial na tokeny alfanumeryczne. Uzywany do podswietlania trafien."""
    return re.findall(r"[0-9A-Za-zÀ-ɏ]+", text)


__all__ = [
    "OCR_CONFUSIONS",
    "SPECIAL_FOLD",
    "alpha_ratio",
    "clean_text",
    "collapse_repeated_chars",
    "fold_diacritics",
    "fold_for_search",
    "looks_like_garbage",
    "normalize_unicode",
    "normalize_whitespace",
    "search_form",
    "strip_separators",
    "tokenize_words",
]
