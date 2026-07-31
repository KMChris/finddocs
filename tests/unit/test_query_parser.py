"""Testy analizy zapytania uzytkownika.

Zestaw zapytan pochodzi z rozdzialu 14 specyfikacji. Analizator ma rozdzielic
warstwe doslowna (data, numer rachunku) od warstwy znaczeniowej, ktora trafia
do embeddingu.
"""

from __future__ import annotations

import datetime as dt

import pytest

from finddocs.search.query_parser import analyze_query, exact_tokens, highlight_terms
from finddocs.types import DateRange, TermKind

#: Piec zapytan przykladowych ze specyfikacji, rozdzial 14.
ZAPYTANIA_ZE_SPECYFIKACJI = [
    "Podaj, w jakich dokumentach klient X zawieral transakcje z klientem Y.",
    "Jaka byla procedura dotyczaca przelewow w dniu 24.07.2015?",
    "Wyszukaj wszystkie transakcje z rachunku 0123456789.",
    "Co sie dzialo w dniu 05.05.2007?",
    "Czy klient X mial jakiekolwiek powiazania z klientem Y?",
]


def rodzaje(zapytanie: str) -> set[TermKind]:
    """Zbior rodzajow elementow rozpoznanych w zapytaniu."""
    return {term.kind for term in analyze_query(zapytanie).terms}


# --- zapytania ze specyfikacji -------------------------------------------------


@pytest.mark.parametrize("zapytanie", ZAPYTANIA_ZE_SPECYFIKACJI)
def test_zapytania_ze_specyfikacji_daja_niepusta_analize(zapytanie):
    analiza = analyze_query(zapytanie)
    assert analiza.raw_query == zapytanie
    assert analiza.semantic_text
    assert analiza.terms
    assert analiza.is_natural_language is True


def test_zapytanie_pierwsze_jest_czysto_znaczeniowe():
    analiza = analyze_query(ZAPYTANIA_ZE_SPECYFIKACJI[0])
    assert analiza.has_exact_elements is False
    assert exact_tokens(analiza) == []
    assert rodzaje(ZAPYTANIA_ZE_SPECYFIKACJI[0]) == {TermKind.WORD}


def test_zapytanie_drugie_wydziela_date():
    analiza = analyze_query(ZAPYTANIA_ZE_SPECYFIKACJI[1])
    assert analiza.has_exact_elements is True
    assert exact_tokens(analiza) == ["dat20150724"]
    data = next(t for t in analiza.terms if t.kind is TermKind.DATE)
    assert data.raw == "24.07.2015"
    assert data.is_exact_required is True
    assert "yea2015" in data.variants


def test_zapytanie_trzecie_wydziela_numer_rachunku():
    analiza = analyze_query(ZAPYTANIA_ZE_SPECYFIKACJI[2])
    assert exact_tokens(analiza) == ["num0123456789"]
    rachunek = next(t for t in analiza.terms if t.kind is TermKind.ACCOUNT)
    assert rachunek.raw == "0123456789"
    assert rachunek.is_exact_required is True


def test_zapytanie_czwarte_wydziela_date():
    analiza = analyze_query(ZAPYTANIA_ZE_SPECYFIKACJI[3])
    assert exact_tokens(analiza) == ["dat20070505"]


def test_zapytanie_piate_jest_czysto_znaczeniowe():
    analiza = analyze_query(ZAPYTANIA_ZE_SPECYFIKACJI[4])
    assert analiza.has_exact_elements is False
    assert analiza.date_filters == []


# --- frazy w cudzyslowie -------------------------------------------------------


@pytest.mark.parametrize(
    "zapytanie",
    ['"umowa ramowa" przelewy', "„umowa ramowa” przelewy"],
)
def test_fraza_w_cudzyslowie_prostym_i_drukarskim(zapytanie):
    analiza = analyze_query(zapytanie)
    assert analiza.phrases == ["umowa ramowa"]
    fraza = next(t for t in analiza.terms if t.kind is TermKind.PHRASE)
    assert fraza.raw == "umowa ramowa"
    assert fraza.is_exact_required is True
    assert analiza.has_exact_elements is True
    assert "przelewy" in [t.normalized for t in analiza.terms if t.kind is TermKind.WORD]


def test_fraza_zachowuje_kolejnosc_slow_w_postaci_zlozonej():
    analiza = analyze_query('"Umowa RAMOWA z Łodzi"')
    fraza = next(t for t in analiza.terms if t.kind is TermKind.PHRASE)
    assert fraza.normalized == "umowa ramowa z lodzi"


def test_pusty_cudzyslow_nie_tworzy_frazy():
    analiza = analyze_query('"" przelewy')
    assert analiza.phrases == []


# --- zakresy dat ---------------------------------------------------------------


def test_zakres_dat_daje_filtr_a_nie_wymog_obu_dat():
    analiza = analyze_query("od 01.01.2015 do 31.12.2015")
    assert analiza.date_filters == [DateRange(start=dt.date(2015, 1, 1), end=dt.date(2015, 12, 31))]
    krance = [t for t in analiza.terms if t.kind is TermKind.DATE_RANGE]
    assert len(krance) == 2
    assert all(t.is_exact_required is False for t in krance)
    # Zaden token daty nie moze byc wymagany, inaczej dokument musialby zawierac
    # obie daty jednoczesnie.
    assert exact_tokens(analiza) == []


def test_dwie_odlegle_daty_nie_tworza_zakresu():
    analiza = analyze_query(
        "protokol z 01.01.2015 dotyczacy ustalen poczynionych wczesniej, aneks 31.12.2015"
    )
    assert analiza.date_filters == []
    assert set(exact_tokens(analiza)) == {"dat20150101", "dat20151231"}


def test_pojedyncza_data_nie_tworzy_zakresu():
    analiza = analyze_query("procedura z 24.07.2015")
    assert analiza.date_filters == []
    assert exact_tokens(analiza) == ["dat20150724"]


# --- nazwy plikow --------------------------------------------------------------


@pytest.mark.parametrize(
    "nazwa",
    ["sprawozdanie.docx", "raport-2015.pdf", "transakcje.csv", "skan.jpeg"],
)
def test_rozpoznanie_nazwy_pliku(nazwa):
    analiza = analyze_query(f"znajdz plik {nazwa}")
    plik = next(t for t in analiza.terms if t.kind is TermKind.FILENAME)
    assert plik.raw.endswith(nazwa)
    assert plik.is_exact_required is True


def test_slowo_bez_rozszerzenia_nie_jest_nazwa_pliku():
    assert TermKind.FILENAME not in rodzaje("sprawozdanie roczne")


# --- tokeny i podswietlanie ----------------------------------------------------


def test_exact_tokens_laczy_kwote_i_identyfikator():
    analiza = analyze_query("faktura FV/2015/07/123 na 1 234,56 zl")
    assert set(exact_tokens(analiza)) == {"kwo123456", "idffv201507123"}


def test_exact_tokens_pomija_slowa_i_frazy():
    analiza = analyze_query('"umowa ramowa" przelewy 24.07.2015')
    assert exact_tokens(analiza) == ["dat20150724"]


def test_exact_tokens_bez_duplikatow():
    analiza = analyze_query("rachunek 0123456789 oraz rachunek 01 2345 6789")
    assert exact_tokens(analiza) == ["num0123456789"]


def test_highlight_terms_zawiera_postac_wpisana_i_warianty():
    analiza = analyze_query('"umowa ramowa" z 24.07.2015 na 314 zl')
    wyrazenia = highlight_terms(analiza)
    assert "umowa ramowa" in wyrazenia
    assert "24.07.2015" in wyrazenia
    assert "314 zl" in wyrazenia
    assert len(wyrazenia) == len(set(wyrazenia))


def test_highlight_terms_pomija_zbyt_krotkie_wyrazenia():
    for wyrazenie in highlight_terms(analyze_query("a b umowa")):
        assert len(wyrazenie) >= 2


# --- rozpoznanie jezyka naturalnego --------------------------------------------


@pytest.mark.parametrize(
    "zapytanie",
    [
        "Co sie dzialo w dniu 05.05.2007?",
        "Jaka byla procedura dotyczaca przelewow?",
        "znajdz umowy zawarte z kontrahentem",
        "opis procedury reklamacyjnej dla klientow detalicznych",
    ],
)
def test_is_natural_language_dla_pytania(zapytanie):
    assert analyze_query(zapytanie).is_natural_language is True


@pytest.mark.parametrize("zapytanie", ["0123456789", "24.07.2015", "FV/2015/07/123"])
def test_is_natural_language_dla_samego_numeru(zapytanie):
    analiza = analyze_query(zapytanie)
    assert analiza.is_natural_language is False
    assert analiza.has_exact_elements is True


def test_puste_zapytanie():
    analiza = analyze_query("   ")
    assert analiza.raw_query == ""
    assert analiza.terms == []
    assert analiza.has_exact_elements is False
    assert exact_tokens(analiza) == []
    assert highlight_terms(analiza) == []
