"""Testy naglowka kontekstu dokumentu doklejanego przed osadzeniem.

Naglowek wchodzi wylacznie do tekstu podawanego dostawcy embeddingow, wiec
jego format musi byc stabilny: zmiana wymaga podniesienia EMBED_CONTEXT_VERSION.
Testy pilnuja skladu naglowka, obslugi dokumentow podrzednych i obcinania
patologicznie dlugich sciezek.
"""

from __future__ import annotations

from finddocs.providers.context import (
    MAX_PATH_CHARS,
    document_context_header,
    enrich_passages,
)


def test_naglowek_zawiera_nazwe_i_katalog() -> None:
    header = document_context_header("umowa.pdf", "Umowy/2015/umowa.pdf")

    assert header == "Plik: umowa.pdf\nŚcieżka: Umowy/2015"


def test_plik_w_korzeniu_ma_tylko_linie_nazwy() -> None:
    header = document_context_header("notatka.txt", "notatka.txt")

    assert header == "Plik: notatka.txt"


def test_biblioteka_poprzedza_katalog() -> None:
    header = document_context_header("raport.xlsx", "Raporty/2015/raport.xlsx", library="Dokumenty")

    assert header == "Plik: raport.xlsx\nŚcieżka: Dokumenty/Raporty/2015"


def test_biblioteka_nie_jest_dublowana_gdy_otwiera_sciezke() -> None:
    header = document_context_header(
        "raport.xlsx", "Dokumenty/Raporty/raport.xlsx", library="Dokumenty"
    )

    assert header == "Plik: raport.xlsx\nŚcieżka: Dokumenty/Raporty"


def test_dokument_podrzedny_dostaje_sciezke_rodzica() -> None:
    """Zalacznik ma sciezke logiczna "rodzic :: nazwa" i separator nie moze zostac."""
    header = document_context_header("zestawienie.csv", "Poczta/wiadomosc.eml :: zestawienie.csv")

    assert header == "Plik: zestawienie.csv\nŚcieżka: Poczta/wiadomosc.eml"


def test_ukosniki_windows_sa_ujednolicane() -> None:
    header = document_context_header("plik.txt", "Katalog\\Podkatalog\\plik.txt")

    assert header == "Plik: plik.txt\nŚcieżka: Katalog/Podkatalog"


def test_brak_danych_daje_pusty_naglowek() -> None:
    assert document_context_header("", "") == ""


def test_dluga_sciezka_zachowuje_koncowe_segmenty() -> None:
    czlony = [f"katalog-{i:03d}" for i in range(60)]
    logical = "/".join([*czlony, "plik.txt"])

    header = document_context_header("plik.txt", logical)

    linia = header.splitlines()[1]
    assert linia.startswith("Ścieżka: …/")
    assert linia.endswith("katalog-059")
    assert len(linia) <= len("Ścieżka: …/") + MAX_PATH_CHARS
    # Najblizsze katalogi niosa najwiecej znaczenia, wiec zostaja koncowe.
    assert "katalog-000" not in linia


def test_pojedynczy_segment_dluzszy_niz_limit_jest_obcinany() -> None:
    logical = "a" * (MAX_PATH_CHARS * 2) + "/plik.txt"

    header = document_context_header("plik.txt", logical)

    linia = header.splitlines()[1]
    assert len(linia) <= len("Ścieżka: …/") + MAX_PATH_CHARS


def test_enrich_passages_dokleja_naglowek_do_kazdego_fragmentu() -> None:
    teksty = ["pierwszy fragment", "drugi fragment"]

    wynik = enrich_passages(teksty, "Plik: a.txt")

    assert wynik == [
        "Plik: a.txt\npierwszy fragment",
        "Plik: a.txt\ndrugi fragment",
    ]
    # Lista wejsciowa pozostaje nietknieta.
    assert teksty == ["pierwszy fragment", "drugi fragment"]


def test_enrich_passages_z_pustym_naglowkiem_nic_nie_zmienia() -> None:
    teksty = ["fragment"]

    assert enrich_passages(teksty, "") is teksty
