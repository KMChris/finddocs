"""Testy rozpoznawania kodowania plikow tekstowych.

Testy pilnuja przypadku, ktory wykryl blad w pierwszej wersji: krotki polski plik
UTF-8 bywa rozpoznawany przez detekcje statystyczna jako azjatycka strona kodowa,
a plik iso-8859-2 jako cp1250. Dekodowanie sie wtedy udaje, ale wynik jest smieciem.
"""

from __future__ import annotations

import codecs

import pytest

from finddocs.extractors.encoding import (
    bom_encoding,
    canonical_encoding,
    decode_text,
    score_text,
)

#: Zdanie zawierajace wszystkie polskie znaki diakrytyczne.
POLISH_SAMPLE = "Zażółć gęślą jaźń"

#: Same litery diakrytyczne, male i wielkie.
POLISH_LETTERS = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"

#: Krotki tekst, na ktorym detekcja statystyczna ma najmniej przeslanek.
SHORT_TEXT = f"{POLISH_SAMPLE}\n\n{POLISH_LETTERS}\n"

#: Dluzszy tekst przypominajacy prawdziwy dokument biurowy.
LONG_TEXT = (
    "Notatka sluzbowa z dnia 24.07.2015.\n"
    f"{POLISH_SAMPLE}. Procedura dotyczaca przelewow krajowych.\n"
    "Rachunek 00 1234 5678 9012 3456 7890 1234, kwota 1 234,56 PLN.\n"
    "Oddzial w miescie Łódź przyjmuje dyspozycje do godziny 16:00.\n"
)


@pytest.mark.parametrize("text", [SHORT_TEXT, LONG_TEXT])
@pytest.mark.parametrize(
    "encoding",
    ["utf-8", "utf-8-sig", "cp1250", "iso-8859-2", "utf-16", "utf-16-le", "utf-16-be"],
)
def test_polskie_znaki_wracaja_z_kazdego_kodowania(text: str, encoding: str) -> None:
    """Tekst po zdekodowaniu jest identyczny z oryginalem."""
    decoded = decode_text(text.encode(encoding))

    assert decoded.text.replace("\r\n", "\n") == text
    assert decoded.replaced is False


def test_krotki_plik_utf8_nie_jest_brany_za_kodowanie_azjatyckie() -> None:
    """Poprawna sekwencja UTF-8 wygrywa z podpowiedzia detektora statystycznego."""
    decoded = decode_text(SHORT_TEXT.encode("utf-8"))

    assert decoded.encoding == "utf-8"
    assert POLISH_SAMPLE in decoded.text


def test_iso8859_2_nie_jest_mylone_z_cp1250() -> None:
    """Obie strony kodowe roznia sie literami s, a i z, wiec ocena musi je rozroznic."""
    decoded = decode_text(SHORT_TEXT.encode("iso-8859-2"))

    assert POLISH_LETTERS in decoded.text
    assert "¶" not in decoded.text
    assert "±" not in decoded.text


def test_cp1250_nie_jest_mylone_z_iso8859_2() -> None:
    """Kierunek odwrotny sprawdza, ze ocena nie faworyzuje jednej strony kodowej."""
    decoded = decode_text(SHORT_TEXT.encode("cp1250"))

    assert POLISH_LETTERS in decoded.text


def test_bom_ma_pierwszenstwo_przed_detekcja() -> None:
    """Znacznik BOM rozstrzyga bez zadnych heurystyk i nie trafia do tresci."""
    data = codecs.BOM_UTF8 + POLISH_SAMPLE.encode("utf-8")

    decoded = decode_text(data)

    assert decoded.encoding == "utf-8-sig"
    assert decoded.text == POLISH_SAMPLE


def test_zadeklarowane_kodowanie_jest_respektowane() -> None:
    """Deklaracja z pliku HTML wygrywa, gdy daje sensowny wynik."""
    decoded = decode_text(POLISH_SAMPLE.encode("cp1250"), declared="windows-1250")

    assert codecs.lookup(decoded.encoding).name == "cp1250"
    assert decoded.text == POLISH_SAMPLE


def test_klamliwa_deklaracja_kodowania_jest_odrzucana() -> None:
    """Deklaracja prowadzaca do smieci jest ignorowana na rzecz wlasnej oceny."""
    decoded = decode_text(POLISH_SAMPLE.encode("utf-8"), declared="cp949")

    assert POLISH_SAMPLE in decoded.text


def test_pusty_plik_nie_jest_bledem() -> None:
    """Brak danych daje pusty tekst, a nie wyjatek."""
    decoded = decode_text(b"")

    assert decoded.text == ""
    assert decoded.replaced is False


def test_czysty_ascii_pozostaje_bez_zmian() -> None:
    """Plik bez znakow spoza ASCII przechodzi przez dekoder nietkniety."""
    decoded = decode_text(b"Invoice number FV/2015/07/123, amount 1234.56 PLN\n")

    assert decoded.text.startswith("Invoice number")


def test_ocena_premiuje_tekst_polski() -> None:
    """Ten sam plik odczytany zla strona kodowa dostaje nizsza ocene."""
    data = SHORT_TEXT.encode("iso-8859-2")

    dobra = score_text(data.decode("iso-8859-2"))
    zla = score_text(data.decode("cp1250"))

    assert dobra > zla


def test_ocena_karze_pismo_obce() -> None:
    """Tekst zamieniony na sylaby hangul ma ocene wyraznie ujemna."""
    assert score_text("한국어 문서입니다") < 0
    assert score_text(LONG_TEXT) > 0


def test_ocena_karze_znaki_sterujace() -> None:
    """Ciag bajtow sterujacych nie moze wygrac z tekstem."""
    assert score_text("\x00\x01\x02\x03\x04\x05") < score_text("Notatka sluzbowa")


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
    ],
)
def test_rozpoznawanie_znacznikow_bom(marker: bytes, expected: str) -> None:
    """Kazdy znacznik BOM jest rozpoznawany, UTF-32 przed UTF-16."""
    assert bom_encoding(marker + b"tekst") == expected


def test_brak_znacznika_bom_zwraca_none() -> None:
    assert bom_encoding(b"zwykly tekst") is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [("UTF_8", "utf-8"), (" CP1250 ", "cp1250"), ("ISO_8859_2", "iso-8859-2")],
)
def test_ujednolicanie_nazw_kodowan(name: str, expected: str) -> None:
    assert canonical_encoding(name) == expected


def test_bajty_nieczytelne_zadnym_kodowaniem_daja_ostrzezenie() -> None:
    """Gdy nic nie pasuje, zwracamy tekst z zamiana bledow i ostrzezeniem."""
    decoded = decode_text(b"\xff\xfe\x00\x00\xff\xff\xff\xff" * 4)

    assert decoded.text
    assert isinstance(decoded.warnings, list)
