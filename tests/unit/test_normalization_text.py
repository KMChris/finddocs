"""Testy modulu finddocs.normalization.text.

Sprawdzamy, ze normalizacja nie niszczy polskich liter, a jednoczesnie ujednolica
interpunkcje i biale znaki oraz poprawnie sklada znaki diakrytyczne.
"""

from __future__ import annotations

import unicodedata

import pytest

from finddocs.normalization.text import (
    alpha_ratio,
    clean_text,
    collapse_repeated_chars,
    fold_diacritics,
    fold_for_search,
    looks_like_garbage,
    normalize_unicode,
    normalize_whitespace,
    search_form,
    strip_separators,
    tokenize_words,
)

#: Komplet polskich liter z ogonkami, kreskami i kropka.
POLSKIE_LITERY = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"


# --- normalize_unicode ---------------------------------------------------------


def test_normalize_unicode_sprowadza_do_nfc():
    rozlozone = unicodedata.normalize("NFD", "Łódź")
    assert rozlozone != "Łódź"
    wynik = normalize_unicode(rozlozone)
    assert wynik == "Łódź"
    assert unicodedata.is_normalized("NFC", wynik)


@pytest.mark.parametrize(
    ("wejscie", "oczekiwane"),
    [
        ("„Cytat”", '"Cytat"'),
        ("“Cytat”", '"Cytat"'),
        ("«Cytat»", '"Cytat"'),
        ("‚jeden’", "'jeden'"),
        ("‘jeden’", "'jeden'"),
    ],
)
def test_normalize_unicode_ujednolica_cudzyslowy(wejscie, oczekiwane):
    assert normalize_unicode(wejscie) == oczekiwane


# Warianty kresek spotykane w dokumentach biurowych. Wystepuja tu jako dane
# testowe, bo wlasnie ich ujednolicenie sprawdzamy.
@pytest.mark.parametrize(
    "myslnik",
    [chr(0x2013), chr(0x2014), chr(0x2015), chr(0x2212), chr(0x2010), chr(0x2011)],
    ids=["en_dash", "em_dash", "horizontal_bar", "minus", "hyphen", "nb_hyphen"],
)
def test_normalize_unicode_ujednolica_myslniki(myslnik):
    assert normalize_unicode(f"od 1{myslnik}2") == "od 1-2"


def test_normalize_unicode_usuwa_znaki_sterujace_ale_zostawia_tabulator():
    wejscie = "a\x00b\x0bc\x1fd\x7fe\tf\ng"
    wynik = normalize_unicode(wejscie)
    assert wynik == "a b c d e\tf\ng"
    assert "\x00" not in wynik


def test_normalize_unicode_zachowuje_polskie_litery():
    assert normalize_unicode(POLSKIE_LITERY) == POLSKIE_LITERY
    assert normalize_unicode("Zażółć gęślą jaźń") == "Zażółć gęślą jaźń"


def test_normalize_unicode_zamienia_spacje_specjalne_i_wielokropek():
    # Spacja nielamiaca (00A0), waska nielamiaca (202F) i cienka (2009)
    # zamieniaja sie w zwykla spacje.
    spacje = f"a{chr(0x00A0)}b{chr(0x202F)}c{chr(0x2009)}d"
    assert normalize_unicode(spacje) == "a b c d"
    # Miekki myslnik (00AD) znika calkowicie.
    assert normalize_unicode(f"mie{chr(0x00AD)}kki") == "miekki"
    assert normalize_unicode("koniec…") == "koniec..."


def test_normalize_unicode_pusty_tekst():
    assert normalize_unicode("") == ""


# --- normalize_whitespace ------------------------------------------------------


def test_normalize_whitespace_skleja_przenoszenie_wyrazu():
    assert normalize_whitespace("Ka-\npital i te-\nmat") == "Kapital i temat"


def test_normalize_whitespace_redukuje_puste_linie():
    assert normalize_whitespace("jeden\n\n\n\n\n\ndwa") == "jeden\n\ndwa"


def test_normalize_whitespace_ujednolica_konce_linii_i_spacje():
    assert normalize_whitespace("a\r\nb\rc") == "a\nb\nc"
    assert normalize_whitespace("dwa    odstepy   \n") == "dwa odstepy"


def test_normalize_whitespace_bez_akapitow_daje_jedna_linie():
    wejscie = "Pierwszy akapit.\n\nDrugi akapit.\n\n\nTrzeci."
    assert normalize_whitespace(wejscie, keep_paragraphs=False) == (
        "Pierwszy akapit. Drugi akapit. Trzeci."
    )


def test_normalize_whitespace_pusty_tekst():
    assert normalize_whitespace("") == ""


def test_clean_text_laczy_oba_etapy():
    wejscie = "  „Tekst”  z  nbsp – i\n\n\n\n pauza  "
    assert clean_text(wejscie) == '"Tekst" z nbsp - i\n\n pauza'


# --- fold_diacritics -----------------------------------------------------------


def test_fold_diacritics_pangram():
    assert fold_diacritics("Zażółć gęślą jaźń") == "Zazolc gesla jazn"


def test_fold_diacritics_wielkie_litery():
    assert fold_diacritics("ŁÓDŹ") == "LODZ"


def test_fold_diacritics_wszystkie_polskie_litery():
    # l z kreska nie jest znakiem laczonym, wiec NFKD samo go nie usuwa.
    assert fold_diacritics(POLSKIE_LITERY) == "acelnoszzACELNOSZZ"
    assert fold_diacritics("ł") == "l"
    assert fold_diacritics("Ł") == "L"


def test_fold_diacritics_nie_rusza_ascii_i_pustego():
    assert fold_diacritics("Faktura 2015/07") == "Faktura 2015/07"
    assert fold_diacritics("") == ""


# --- fold_for_search i search_form ---------------------------------------------


def test_fold_for_search_sklada_i_obniza_wielkosc():
    assert fold_for_search("ŁÓDŹ") == "lodz"
    assert fold_for_search("Zażółć GĘŚLĄ") == "zazolc gesla"


def test_search_form_zachowuje_polskie_znaki():
    assert search_form("  ŁÓDŹ  ") == "łódź"
    assert search_form("Umowa  nr\n\n\n\n1") == "umowa nr\n\n1"


# --- heurystyki jakosci tekstu -------------------------------------------------


def test_looks_like_garbage_dla_poprawnego_tekstu():
    tekst = "Procedura dotyczaca przelewow obowiazuje od dnia 24.07.2015 roku."
    assert looks_like_garbage(tekst) is False
    assert alpha_ratio(tekst) > 0.8


def test_looks_like_garbage_dla_smieci():
    assert looks_like_garbage("#$%^&*()_+{}|:<>?~`=[]" * 3) is True
    assert looks_like_garbage("�" * 20) is True
    assert looks_like_garbage("") is True


def test_looks_like_garbage_reaguje_na_znaki_zastepcze():
    tekst = "Tekst poprawny w wiekszosci" + "�" * 3
    assert looks_like_garbage(tekst) is True


def test_alpha_ratio_zakres():
    assert alpha_ratio("") == 0.0
    assert alpha_ratio("abc123") == 1.0
    assert alpha_ratio("ab..") == pytest.approx(0.5)


def test_alpha_ratio_pomija_biale_znaki():
    assert alpha_ratio("ab cd\n") == 1.0


# --- funkcje pomocnicze --------------------------------------------------------


def test_collapse_repeated_chars():
    assert collapse_repeated_chars("aaaaaabbbb") == "aaabbb"
    assert collapse_repeated_chars("aaaaa", max_run=1) == "a"
    assert collapse_repeated_chars("") == ""
    assert collapse_repeated_chars("abc") == "abc"


def test_strip_separators():
    assert strip_separators("01 2345-6789") == "0123456789"
    assert strip_separators("FV/2015/07/123") == "FV201507123"
    assert strip_separators("a_b.c\\d–e") == "abcde"


def test_tokenize_words():
    assert tokenize_words("Faktura nr FV/2015/07/123, kwota 314 zl.") == [
        "Faktura",
        "nr",
        "FV",
        "2015",
        "07",
        "123",
        "kwota",
        "314",
        "zl",
    ]
    assert tokenize_words("Łódź i Gdańsk") == ["Łódź", "i", "Gdańsk"]
    assert tokenize_words("") == []
