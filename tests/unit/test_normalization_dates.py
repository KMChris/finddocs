"""Testy rozpoznawania dat w tekstach polskich.

Najwazniejsza wlasnosc: rozne zapisy tej samej daty musza dawac ten sam token,
inaczej zapytanie ``24 lipca 2015`` nie znajdzie dokumentu z zapisem ``24.07.2015``.
"""

from __future__ import annotations

import datetime as dt

import pytest

from finddocs.normalization.dates import (
    DATE_TOKEN_PREFIX,
    MONTH_TOKEN_PREFIX,
    YEAR_TOKEN_PREFIX,
    date_tokens,
    find_dates,
    format_variants,
    parse_single_date,
)

DWUDZIESTY_CZWARTY_LIPCA = dt.date(2015, 7, 24)


@pytest.mark.parametrize(
    "zapis",
    [
        "24.07.2015",
        "2015-07-24",
        "24 lipca 2015",
        "24-07-2015",
        "24/07/2015",
        "24.07.15",
    ],
)
def test_find_dates_rozpoznaje_warianty_zapisu(zapis):
    znalezione = find_dates(f"Dokument z dnia {zapis} podpisany.")
    assert len(znalezione) == 1
    assert znalezione[0].value == DWUDZIESTY_CZWARTY_LIPCA
    assert znalezione[0].precision == "day"
    assert znalezione[0].token == f"{DATE_TOKEN_PREFIX}20150724"


def test_find_dates_zwraca_surowy_zapis_i_pozycje():
    tekst = "Dokument z dnia 24.07.2015 podpisany."
    znaleziona = find_dates(tekst)[0]
    assert znaleziona.raw == "24.07.2015"
    poczatek, koniec = znaleziona.span
    assert tekst[poczatek:koniec] == "24.07.2015"


def test_find_dates_miesiac_i_rok_ma_precyzje_miesiaca():
    znalezione = find_dates("Sprawozdanie za lipiec 2015 roku.")
    assert len(znalezione) == 1
    znaleziona = znalezione[0]
    assert znaleziona.precision == "month"
    assert znaleziona.value == dt.date(2015, 7, 1)
    assert znaleziona.token == f"{MONTH_TOKEN_PREFIX}201507"


def test_find_dates_dziala_na_nazwach_miesiecy_z_polskimi_znakami():
    znalezione = find_dates("Umowa z dnia 24 października 2015 r.")
    assert [d.value for d in znalezione] == [dt.date(2015, 10, 24)]


@pytest.mark.parametrize(
    "zapis",
    ["32.13.2015", "2015-02-30", "31.02.2015", "00.07.2015", "24.07.1850"],
)
def test_find_dates_odrzuca_daty_niepoprawne(zapis):
    assert find_dates(f"data {zapis} koniec") == []


def test_find_dates_pusty_tekst():
    assert find_dates("") == []


def test_find_dates_sortuje_po_pozycji():
    znalezione = find_dates("Od 01.01.2015 do 31.12.2015 oraz aneks z 2016-03-05.")
    assert [d.value for d in znalezione] == [
        dt.date(2015, 1, 1),
        dt.date(2015, 12, 31),
        dt.date(2016, 3, 5),
    ]


# --- tokeny --------------------------------------------------------------------


def test_date_tokens_zawiera_dzien_miesiac_i_rok():
    tokeny = date_tokens("Notatka z 24.07.2015.")
    assert tokeny == [
        f"{DATE_TOKEN_PREFIX}20150724",
        f"{MONTH_TOKEN_PREFIX}201507",
        f"{YEAR_TOKEN_PREFIX}2015",
    ]


def test_date_tokens_dla_precyzji_miesiaca_nie_ma_tokenu_dnia():
    tokeny = date_tokens("Raport za lipiec 2015.")
    assert tokeny == [f"{MONTH_TOKEN_PREFIX}201507", f"{YEAR_TOKEN_PREFIX}2015"]
    assert not any(t.startswith(DATE_TOKEN_PREFIX) for t in tokeny)


def test_date_tokens_bez_duplikatow():
    tokeny = date_tokens("24.07.2015, czyli 24 lipca 2015, zapis 2015-07-24.")
    assert tokeny == sorted(set(tokeny), key=tokeny.index)
    assert len(tokeny) == 3


def test_date_tokens_sa_alfanumeryczne():
    # Token z myslnikiem albo dwukropkiem rozpadlby sie w tokenizatorze FTS5.
    for token in date_tokens("Data 24.07.2015 oraz lipiec 2016."):
        assert token.isalnum()


def test_trzy_zapisy_tej_samej_daty_daja_ten_sam_token_dnia():
    tokeny = {
        find_dates(zapis)[0].token
        for zapis in ("24.07.2015", "24 lipca 2015", "2015-07-24", "24/07/2015")
    }
    assert tokeny == {f"{DATE_TOKEN_PREFIX}20150724"}


# --- warianty zapisu i parsowanie pojedynczej daty -----------------------------


def test_format_variants_zawiera_typowe_zapisy():
    warianty = format_variants(DWUDZIESTY_CZWARTY_LIPCA)
    assert "24.07.2015" in warianty
    assert "2015-07-24" in warianty
    assert "24-07-2015" in warianty
    assert "24/07/2015" in warianty
    assert "24 lipca 2015" in warianty


def test_format_variants_kazdy_wariant_jest_rozpoznawalny():
    for wariant in format_variants(DWUDZIESTY_CZWARTY_LIPCA):
        assert parse_single_date(wariant) == DWUDZIESTY_CZWARTY_LIPCA


def test_parse_single_date_przycina_biale_znaki():
    assert parse_single_date("  24.07.2015  ") == DWUDZIESTY_CZWARTY_LIPCA


def test_parse_single_date_zwraca_none_gdy_brak_daty():
    assert parse_single_date("brak daty") is None
    assert parse_single_date("") is None


def test_parse_single_date_bierze_pierwsza_date():
    assert parse_single_date("01.01.2015 oraz 31.12.2015") == dt.date(2015, 1, 1)
