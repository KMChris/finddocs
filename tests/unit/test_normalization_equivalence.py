"""Dowod, ze przyspieszona normalizacja daje dokladnie te same napisy.

Normalizacja wchodzi do ``NORMALIZATION_VERSION`` i do skrotu zgodnosci indeksu.
Zmiana jej wyniku o jeden znak unieważnia caly zbudowany indeks, a rozjazd
zobaczylby dopiero uzytkownik, ktoremu wyszukiwanie przestaloby zwracac trafienia.
Dlatego optymalizacja jest tu porownywana z implementacja sprzed zmiany,
przepisana nizej jako wzorzec.

Wzorzec ma zostac nietkniety. Gdy ktos swiadomie zmienia zasady skladania
znakow, podnosi ``NORMALIZATION_VERSION`` i dopiero wtedy poprawia wzorzec.
"""

from __future__ import annotations

import random
import re
import unicodedata

import pytest

from finddocs.chunking.base import build_chunk
from finddocs.normalization.dates import date_tokens, find_dates
from finddocs.normalization.numbers import find_all, number_tokens
from finddocs.normalization.pipeline import normalize
from finddocs.normalization.text import (
    SPECIAL_FOLD,
    clean_text,
    fold_diacritics,
    fold_for_search,
    normalize_unicode,
    normalize_whitespace,
    search_form,
)

# --- implementacje wzorcowe (stan sprzed optymalizacji) --------------------------

_PUNCTUATION_WZORZEC: dict[str, str] = {
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

_CONTROL_WZORZEC = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def wzorzec_normalize_unicode(text: str) -> str:
    """Postac NFC z ujednolicona interpunkcja, implementacja sprzed zmiany."""
    if not text:
        return ""
    out = unicodedata.normalize("NFC", text)
    if any(ch in out for ch in _PUNCTUATION_WZORZEC):
        out = out.translate(str.maketrans(_PUNCTUATION_WZORZEC))
    return _CONTROL_WZORZEC.sub(" ", out)


def wzorzec_fold(text: str) -> str:
    """Skladanie znakow diakrytycznych, implementacja sprzed zmiany."""
    if not text:
        return ""
    if any(ch in SPECIAL_FOLD for ch in text):
        text = text.translate(str.maketrans(SPECIAL_FOLD))
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


# --- material do porownania ------------------------------------------------------

POLSKI = (
    "Załącznik numer 3 do umowy ramowej z dnia 24.07.2015 r. Rachunek "
    "00 1234 5678 9012 3456 7890 1234 prowadzony w oddziale w Świnoujściu. "
    "Kwota 1 234,56 PLN płatna do 31 grudnia 2019 roku, NIP 123-456-32-18. "
    "Numer księgi wieczystej WA1M/00123456/7, sygnatura III CZP 45/19."
)

PRZYPADKI: tuple[str, ...] = (
    "",
    " ",
    "zwykly tekst ascii bez niczego",
    POLSKI,
    POLSKI.upper(),
    "".join(SPECIAL_FOLD),
    "".join(SPECIAL_FOLD).upper(),
    "ĄĆĘŁŃÓŚŹŻ ąćęłńóśźż",
    # znaki zlozone zapisane na dwa sposoby: gotowy i jako litera plus znak laczacy
    "é é å å ȫ ñ",
    "ﬁligran ﬂota ǆungla Ⅻ ㍿ ½ ²³",
    "Ελληνικά Кириллица 日本語 한국어 العربية עברית",
    "emoji 🙂 flaga 🇵🇱 rodzina 👨‍👩‍👧 modyfikator 👍🏽",
    "kontrolne \x00\x07\x1f\x7f i biale   ​  znaki",
    "myslniki – — ― − ‐ ‑ oraz cudzyslowy „test” «test» ‚test’",
    "podzial wy-\nrazu i wiele    spacji\t\tz tabulatorami\r\n\r\n\r\nakapit",
    "̧́̈ same znaki laczace na poczatku",
    "mieszanka: łódź ŁÓDŹ Straße Æneas ﬀ Ǳ ǅ",
)

#: Alfabet losowanych napisow: ASCII, polskie znaki, znaki laczace, egzotyka.
ALFABET = (
    "abcXYZ019 .,-/\n\t"
    "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"
    "̧̱̀́̈⃗"
    "éÉåÅøØæÆßœŒþÞðÐħı"
    "«»–—… ​﻿ "
    "ΑΒΓαβγДЖИ漢字한글"
    "\U0001f600\U0001f1f5\U0001f1f1༹᪰"
)


def losowe_napisy(ile: int = 400, dlugosc: int = 60) -> list[str]:
    """Deterministyczny zbior napisow z trudnymi znakami."""
    losowy = random.Random(20260813)
    return [
        "".join(losowy.choice(ALFABET) for _ in range(losowy.randint(0, dlugosc)))
        for _ in range(ile)
    ]


MATERIAL: tuple[str, ...] = (*PRZYPADKI, *losowe_napisy())


# --- rownowaznosc funkcji tekstowych ---------------------------------------------


@pytest.mark.parametrize("tekst", MATERIAL)
def test_skladanie_znakow_jest_identyczne(tekst: str) -> None:
    assert fold_diacritics(tekst) == wzorzec_fold(tekst)


@pytest.mark.parametrize("tekst", MATERIAL)
def test_normalizacja_unicode_jest_identyczna(tekst: str) -> None:
    assert normalize_unicode(tekst) == wzorzec_normalize_unicode(tekst)


def test_skladanie_obejmuje_wszystkie_znaki_laczace_z_bmp() -> None:
    """Tablica tlumaczen ma usuwac dokladnie to, co ``unicodedata.combining``.

    Przeglad calego BMP wychodzi poza material losowany: gdyby tablica
    kiedykolwiek zaczela zgadywac, ten test to pokaze.
    """
    laczace = [chr(code) for code in range(0x10000) if unicodedata.combining(chr(code))]
    assert len(laczace) > 400
    probka = "".join(laczace)
    assert fold_diacritics(f"a{probka}b") == wzorzec_fold(f"a{probka}b")


def test_ascii_wraca_bez_zmian() -> None:
    """Skrot dla ASCII nie moze niczego ruszac ani gubic."""
    tekst = "Faktura FV/2015/07/123, kwota 1234.56 PLN.\n\tDruga linia."
    assert fold_diacritics(tekst) == tekst == wzorzec_fold(tekst)


@pytest.mark.parametrize("tekst", MATERIAL)
def test_postacie_pochodne_sa_identyczne(tekst: str) -> None:
    """Postacie zlozone z czesci tez musza zgadzac sie ze wzorcem.

    ``normalize_whitespace`` nie byl zmieniany, wiec wzorzec czyszczenia sklada
    sie z niego i z wzorcowej normalizacji Unicode.
    """
    wzorzec_clean = normalize_whitespace(wzorzec_normalize_unicode(tekst))
    assert clean_text(tekst) == wzorzec_clean
    assert fold_for_search(tekst) == wzorzec_fold(tekst).casefold()
    assert search_form(tekst) == wzorzec_clean.casefold()


# --- rownowaznosc potoku ---------------------------------------------------------


@pytest.mark.parametrize("tekst", MATERIAL)
def test_detektory_z_gotowym_skladaniem_daja_ten_sam_wynik(tekst: str) -> None:
    """Podanie gotowej postaci zlozonej nie moze zmienic wyniku detektorow."""
    display = clean_text(tekst)
    base = fold_diacritics(display)

    assert date_tokens(display, folded=base) == date_tokens(display)
    assert number_tokens(display, folded=base) == number_tokens(display)
    assert [m.raw for m in find_dates(display, folded=base)] == [m.raw for m in find_dates(display)]
    assert [m.token for m in find_all(display, folded=base)] == [m.token for m in find_all(display)]


@pytest.mark.parametrize("tekst", MATERIAL)
def test_potok_zwraca_te_same_pola(tekst: str) -> None:
    """Cztery reprezentacje fragmentu licza sie tak samo jak przed zmiana."""
    wynik = normalize(tekst)
    display = clean_text(tekst)

    assert wynik.display == display
    if not display:
        assert (wynik.search, wynik.folded, wynik.tokens) == ("", "", [])
        return
    assert wynik.search == search_form(display)
    assert wynik.folded == wzorzec_fold(display).casefold()


@pytest.mark.parametrize(
    "naglowek",
    [None, "Rozdział 1. Postanowienia ogólne"],
)
def test_fragment_ma_ten_sam_tekst_co_przed_zmiana(naglowek: str | None) -> None:
    """``build_chunk`` liczy potok raz, ale pola musza wygladac tak samo.

    Wzorcem jest dawna formula: pola wyszukiwawcze z tekstu z naglowkiem,
    tekst pokazywany z samego fragmentu.
    """
    tekst = f"{POLSKI}\n\nDrugi akapit z data 1 marca 2020 r."

    chunk = build_chunk(0, tekst, heading=naglowek)

    prefiks = f"{naglowek}\n" if naglowek else ""
    wzorzec = normalize(prefiks + tekst)
    assert chunk.text == normalize(tekst).display
    assert chunk.search_text == wzorzec.search
    assert chunk.folded_text == wzorzec.folded
    assert chunk.normalized_tokens == wzorzec.token_text
