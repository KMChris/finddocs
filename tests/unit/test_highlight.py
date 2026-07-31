"""Testy wyrozniania trafien i budowy fragmentow prezentowanych uzytkownikowi.

Tekst pokazywany uzytkownikowi zachowuje oryginalna pisownie. Dopasowanie idzie
po wersji zlozonej, wiec zapytanie ``lodz`` musi trafic w ``Łódź``, a numer bez
separatorow w numer zapisany grupami cyfr.
"""

from __future__ import annotations

from finddocs.search.highlight import (
    HIGHLIGHT_CLOSE,
    HIGHLIGHT_OPEN,
    apply_highlight,
    build_snippet,
    contains_all_terms,
    find_matches,
    fold_with_positions,
    highlight_to_html,
    strip_highlight,
)

TEKST = "Oddzial w miescie Łódź obsluguje rachunek 01 2345 6789 od 2015 roku."


def podswietl(tekst: str, wyrazenia: list[str]) -> str:
    """Skrot: znajdz trafienia i wstaw znaczniki."""
    return apply_highlight(tekst, find_matches(tekst, wyrazenia))


def wycinki(tekst: str, wyrazenia: list[str]) -> list[str]:
    """Fragmenty tekstu zrodlowego odpowiadajace trafieniom."""
    return [tekst[start:koniec] for start, koniec in find_matches(tekst, wyrazenia)]


# --- dopasowanie z polskimi znakami --------------------------------------------


def test_zapytanie_bez_polskich_znakow_trafia_w_polskie_slowo():
    assert wycinki(TEKST, ["lodz"]) == ["Łódź"]
    assert podswietl(TEKST, ["lodz"]) == TEKST.replace(
        "Łódź", f"{HIGHLIGHT_OPEN}Łódź{HIGHLIGHT_CLOSE}"
    )


def test_podswietlenie_zachowuje_oryginalna_pisownie():
    wynik = podswietl(TEKST, ["lodz"])
    assert "Łódź" in wynik
    assert strip_highlight(wynik) == TEKST


def test_dopasowanie_ignoruje_wielkosc_liter():
    assert wycinki("Zażółć gęślą jaźń", ["ZAZOLC"]) == ["Zażółć"]


def test_dopasowanie_nie_lapie_czesci_slowa():
    assert find_matches("Lodzianin z Lodzi", ["lodz"]) == []


def test_fold_with_positions_mapuje_pozycje_na_tekst_zrodlowy():
    zlozony = fold_with_positions("Łódź")
    assert zlozony.text == "lodz"
    assert zlozony.origin_span(0, 4) == (0, 4)


# --- numery z separatorami -----------------------------------------------------


def test_numer_bez_separatorow_trafia_w_numer_z_separatorami():
    assert wycinki(TEKST, ["0123456789"]) == ["01 2345 6789"]


def test_numer_z_myslnikami_tez_jest_znajdowany():
    tekst = "rachunek 01-2345-6789 klienta"
    assert wycinki(tekst, ["0123456789"]) == ["01-2345-6789"]


def test_krotki_numer_nie_dopuszcza_separatorow():
    # Ponizej szesciu cyfr dopuszczenie separatorow dawaloby falszywe trafienia.
    assert find_matches("rok 20 15 w tekscie", ["2015"]) == []


def test_fraza_dopuszcza_drobne_roznice_w_odstepach():
    assert wycinki("Podpisano umowe  ramowa dzisiaj", ["umowe ramowa"]) == ["umowe  ramowa"]


# --- budowa fragmentu ----------------------------------------------------------


def dlugi_tekst() -> str:
    """Trafienie ukryte w srodku dlugiego tekstu."""
    return (
        ("Wstep. " * 40) + "Platnosc karta ...384675 - 314 zl w oddziale." + (" Dalszy ciag." * 40)
    )


def test_build_snippet_skraca_tekst_wokol_trafienia():
    tekst = dlugi_tekst()
    fragment, znaleziono = build_snippet(tekst, ["384675"], max_chars=120)

    assert znaleziono is True
    assert "384675" in strip_highlight(fragment)
    assert HIGHLIGHT_OPEN in fragment
    assert len(strip_highlight(fragment)) < len(tekst)


def test_build_snippet_dodaje_wielokropki_na_obu_koncach():
    fragment, _ = build_snippet(dlugi_tekst(), ["384675"], max_chars=120)
    assert fragment.startswith("...")
    assert fragment.endswith("...")


def test_build_snippet_bez_wielokropka_gdy_tekst_krotki():
    fragment, znaleziono = build_snippet(TEKST, ["lodz"], max_chars=400)
    assert znaleziono is True
    assert not fragment.startswith("...")
    assert not fragment.endswith("...")


def test_build_snippet_bez_trafienia_zwraca_poczatek_tekstu():
    tekst = dlugi_tekst()
    fragment, znaleziono = build_snippet(tekst, ["czegostakiegoniema"], max_chars=100)

    assert znaleziono is False
    assert HIGHLIGHT_OPEN not in fragment
    assert fragment.startswith(tekst[:50])
    assert fragment.endswith("...")


def test_build_snippet_dla_pustego_tekstu():
    assert build_snippet("   ", ["cokolwiek"]) == ("", False)


def test_build_snippet_bez_wyrazen():
    fragment, znaleziono = build_snippet(TEKST, [])
    assert znaleziono is False
    assert fragment == TEKST


# --- znaczniki -----------------------------------------------------------------


def test_apply_highlight_scala_nakladajace_sie_zakresy():
    wynik = podswietl(TEKST, ["lodz", "lodz"])
    assert wynik.count(HIGHLIGHT_OPEN) == 1


def test_strip_highlight_usuwa_wszystkie_znaczniki():
    wynik = podswietl(TEKST, ["lodz", "0123456789"])
    assert wynik.count(HIGHLIGHT_OPEN) == 2
    assert strip_highlight(wynik) == TEKST


def test_highlight_to_html_zamienia_znaczniki_i_escapuje_tresc():
    wynik = highlight_to_html(podswietl("znak < i Łódź", ["lodz"]))
    assert wynik == "znak &lt; i <mark>Łódź</mark>"


def test_highlight_to_html_nie_przepuszcza_tagow_ze_zrodla():
    assert highlight_to_html("<script>alert(1)</script>") == (
        "&lt;script&gt;alert(1)&lt;/script&gt;"
    )


# --- kontrola obecnosci wszystkich wyrazen -------------------------------------


def test_contains_all_terms():
    assert contains_all_terms(TEKST, ["lodz", "0123456789"]) is True
    assert contains_all_terms(TEKST, ["lodz", "nieistnieje"]) is False
    assert contains_all_terms(TEKST, []) is True
