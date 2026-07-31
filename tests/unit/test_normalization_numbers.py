"""Testy normalizacji numerow, kwot i identyfikatorow.

Numer rachunku zapisany na trzy sposoby musi dawac jeden token, a myslnik uzyty
jako pauza nie moze sklejac dwoch osobnych liczb w jedna.
"""

from __future__ import annotations

import pytest

from finddocs.normalization.numbers import (
    ACCOUNT_TOKEN_PREFIX,
    AMOUNT_TOKEN_PREFIX,
    IDENTIFIER_TOKEN_PREFIX,
    NIP_TOKEN_PREFIX,
    NUMBER_TOKEN_PREFIX,
    PESEL_TOKEN_PREFIX,
    REGON_TOKEN_PREFIX,
    account_token,
    digit_variants,
    find_all,
    find_amounts,
    normalize_amount,
    number_tokens,
    strip_number_separators,
)

IBAN_TESTOWY = "PL61109010140000071219812874"


def tokeny(tekst: str) -> set[str]:
    """Zbior tokenow rozpoznanych w tekscie."""
    return set(number_tokens(tekst))


# --- numery rachunkow ----------------------------------------------------------


@pytest.mark.parametrize("zapis", ["0123456789", "01 2345 6789", "01-2345-6789"])
def test_numer_rachunku_w_roznych_zapisach_daje_ten_sam_token(zapis):
    assert f"{NUMBER_TOKEN_PREFIX}0123456789" in tokeny(f"rachunek {zapis} klienta")


def test_wszystkie_zapisy_rachunku_zbiegaja_sie_do_jednego_tokenu():
    warianty = {
        next(m.token for m in find_all(f"rachunek {zapis}") if m.kind in {"digits", "account"})
        for zapis in ("0123456789", "01 2345 6789", "01-2345-6789")
    }
    assert warianty == {f"{NUMBER_TOKEN_PREFIX}0123456789"}


def test_iban_z_i_bez_spacji_daje_ten_sam_token():
    ze_spacjami = "PL 61 1090 1014 0000 0712 1981 2874"
    oczekiwany = f"{ACCOUNT_TOKEN_PREFIX}{IBAN_TESTOWY.lower()}"
    assert oczekiwany in tokeny(f"rachunek {IBAN_TESTOWY}")
    assert oczekiwany in tokeny(f"rachunek {ze_spacjami}")


def test_iban_ma_znormalizowana_postac_bez_separatorow():
    znalezione = find_all("IBAN PL 61 1090 1014 0000 0712 1981 2874")
    dopasowania = [m for m in znalezione if m.kind == "iban"]
    assert len(dopasowania) == 1
    assert dopasowania[0].normalized == IBAN_TESTOWY


# --- kwoty ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("zapis", "grosze", "waluta"),
    [
        ("314 zl", "31400", "PLN"),
        ("1 234,56 zl", "123456", "PLN"),
        ("2.500,00 PLN", "250000", "PLN"),
        ("99,99 EUR", "9999", "EUR"),
        ("1 000 zlotych", "100000", "PLN"),
    ],
)
def test_kwoty_daja_token_w_groszach(zapis, grosze, waluta):
    dopasowania = find_amounts(f"do zaplaty {zapis} razem")
    assert len(dopasowania) == 1
    assert dopasowania[0].token == f"{AMOUNT_TOKEN_PREFIX}{grosze}"
    assert dopasowania[0].normalized.endswith(waluta)


def test_normalize_amount_uzupelnia_grosze():
    assert normalize_amount("314", None) == "31400"
    assert normalize_amount("314", "5") == "31450"
    assert normalize_amount("1 234", "56") == "123456"
    assert normalize_amount("2.500", "00") == "250000"


def test_normalize_amount_odrzuca_smieci():
    assert normalize_amount("abc", None) is None


# --- numery urzedowe -----------------------------------------------------------


def test_nip_po_etykiecie():
    assert f"{NIP_TOKEN_PREFIX}1234563218" in tokeny("NIP: 123-456-32-18")
    assert f"{NIP_TOKEN_PREFIX}1234563218" in tokeny("nip 1234563218")


def test_regon_po_etykiecie():
    assert f"{REGON_TOKEN_PREFIX}123456785" in tokeny("REGON: 123456785")


def test_pesel_po_etykiecie():
    assert f"{PESEL_TOKEN_PREFIX}44051401359" in tokeny("PESEL: 44051401359")


def test_numer_bez_etykiety_nie_jest_numerem_urzedowym():
    znalezione = tokeny("w dokumencie widnieje 1234563218")
    assert f"{NIP_TOKEN_PREFIX}1234563218" not in znalezione
    assert f"{NUMBER_TOKEN_PREFIX}1234563218" in znalezione


# --- identyfikatory ------------------------------------------------------------


def test_identyfikator_faktury():
    assert f"{IDENTIFIER_TOKEN_PREFIX}fv201507123" in tokeny("faktura FV/2015/07/123 z lipca")


def test_identyfikator_z_myslnikiem():
    assert f"{IDENTIFIER_TOKEN_PREFIX}abc123456" in tokeny("sprawa ABC-123456 zamknieta")


def test_identyfikator_nie_moze_byc_samymi_cyframi():
    for token in number_tokens("numer 123456789"):
        assert not token.startswith(IDENTIFIER_TOKEN_PREFIX)


# --- regresja: myslnik jako pauza ----------------------------------------------


def test_myslnik_jako_pauza_nie_skleja_liczb():
    # Zapis ze specyfikacji: "platnosc karta ...384675 - 314 zl".
    # Sklejenie dalo by token num384675314, czyli numer, ktorego nie ma w dokumencie.
    znalezione = tokeny("platnosc karta ...384675 - 314 zl")
    assert f"{NUMBER_TOKEN_PREFIX}384675314" not in znalezione
    assert f"{NUMBER_TOKEN_PREFIX}384675" in znalezione
    assert f"{AMOUNT_TOKEN_PREFIX}31400" in znalezione


def test_myslnik_bez_spacji_nadal_grupuje_cyfry():
    assert f"{NUMBER_TOKEN_PREFIX}384675314" in tokeny("numer 384675-314 w systemie")


# --- funkcje pomocnicze --------------------------------------------------------


def test_digit_variants_dla_dziesieciu_cyfr():
    warianty = digit_variants("0123456789")
    assert warianty[0] == "0123456789"
    assert "0123 4567 89" in warianty
    assert "0123-4567-89" in warianty


def test_digit_variants_dla_dlugosci_nrb():
    cyfry = IBAN_TESTOWY[2:]
    warianty = digit_variants(cyfry)
    assert cyfry in warianty
    assert "61 1090 1014 0000 0712 1981 2874" in warianty
    assert "61-1090-1014-0000-0712-1981-2874" in warianty


def test_digit_variants_bez_duplikatow_dla_krotkiego_ciagu():
    assert digit_variants("1234") == ["1234"]


def test_account_token_dla_wpisu_uzytkownika():
    assert account_token("01 2345 6789") == f"{NUMBER_TOKEN_PREFIX}0123456789"
    assert account_token("01-2345-6789") == f"{NUMBER_TOKEN_PREFIX}0123456789"
    assert account_token(IBAN_TESTOWY) == f"{ACCOUNT_TOKEN_PREFIX}{IBAN_TESTOWY.lower()}"


def test_account_token_odrzuca_wartosci_bez_sensu():
    assert account_token("12") is None
    assert account_token("umowa") is None
    assert account_token("") is None


def test_strip_number_separators():
    assert strip_number_separators("01 2345-6789") == "0123456789"
    assert strip_number_separators("PL 61 1090") == "PL611090"


def test_number_tokens_sa_alfanumeryczne_i_bez_duplikatow():
    tekst = "Faktura FV/2015/07/123 na 1 234,56 zl z rachunku 01 2345 6789, NIP: 1234563218."
    lista = number_tokens(tekst)
    assert lista == sorted(set(lista), key=lista.index)
    for token in lista:
        assert token.isalnum()


def test_find_all_pusty_tekst():
    assert find_all("") == []
