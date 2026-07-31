"""Testy trybu hybrydowego.

Tryb hybrydowy laczy dwie listy: wynik dokladny i wynik semantyczny. Laczenie
idzie metoda RRF (Reciprocal Rank Fusion), a element doslowny zapytania dostaje
dodatkowa premie. Chodzi o to, zeby zapytanie w rodzaju ,,notatka ze spotkania
zarzadu 24.07.2015'' nie zgubilo daty na rzecz samego podobienstwa znaczeniowego.

Testy sprawdzaja trzy rzeczy:

* dokument z elementem doslownym wychodzi przed swojego blizniaka bez tego elementu;
* tryb hybrydowy nie gubi dokumentow, ktore znajduje tryb dokladny;
* gdy warstwa wektorowa jest niedostepna, tryb hybrydowy schodzi do trybu
  dokladnego i mowi o tym wprost.

Testy wymagajace wektorow sa pomijane, gdy w katalogu ``models/`` nie ma modelu.
"""

from __future__ import annotations

import pytest

from conftest import ACCOUNT_SPACED, SearchCorpus, SemanticCorpus
from finddocs.search.service import HYBRID_NOTE, NO_SEMANTIC_NOTE, SearchService
from finddocs.types import SearchMode, SearchRequest

# --- laczenie list z premia za element doslowny ----------------------------------


@pytest.mark.requires_model
def test_element_doslowny_wygrywa_z_bliznakiem(semantic_corpus: SemanticCorpus) -> None:
    """Dla kazdego przypadku dokument z elementem doslownym jest wyzej."""
    for case in semantic_corpus.hybrid_cases:
        response = semantic_corpus.search(case.query, mode=SearchMode.HYBRID, limit=10)
        ranking = semantic_corpus.ranking(response)

        assert case.expected_first in ranking, (
            f"{case.element}: dokument {case.expected_first} wypadl z wynikow "
            f"dla zapytania {case.query!r}"
        )
        assert ranking[0] == case.expected_first, (
            f"{case.element}: na pierwszym miejscu jest {ranking[0]}, "
            f"a powinien byc {case.expected_first}"
        )


@pytest.mark.requires_model
def test_numer_rachunku_nie_ginie_w_embeddingu(semantic_corpus: SemanticCorpus) -> None:
    """Dwa dokumenty roznia sie tylko numerem rachunku, wygrywa ten z numerem."""
    query = f"stala dyspozycja obciazania konta {ACCOUNT_SPACED}"

    ranking = semantic_corpus.ranking(
        semantic_corpus.search(query, mode=SearchMode.HYBRID, limit=10)
    )

    assert ranking.index("zlecenie-numer") < ranking.index("zlecenie-bez-numeru")


@pytest.mark.requires_model
def test_data_z_zapytania_ma_znaczenie(semantic_corpus: SemanticCorpus) -> None:
    """Dwie notatki maja te sama tresc i rozne daty. Liczy sie data z zapytania."""
    ranking = semantic_corpus.ranking(
        semantic_corpus.search(
            "notatka ze spotkania zarzadu 24.07.2015", mode=SearchMode.HYBRID, limit=10
        )
    )

    assert ranking.index("notatka-data") < ranking.index("notatka-inna-data")


@pytest.mark.requires_model
def test_fraza_w_cudzyslowie_wskazuje_klienta(semantic_corpus: SemanticCorpus) -> None:
    """Cudzyslow to zadanie doslowne, a nie podpowiedz."""
    ranking = semantic_corpus.ranking(
        semantic_corpus.search(
            'umowa o wspolpracy z klientem "Fabryka Domow"', mode=SearchMode.HYBRID, limit=10
        )
    )

    assert ranking[0] == "klient-fabryka"


@pytest.mark.requires_model
def test_tryb_hybrydowy_znajduje_wiecej_niz_dokladny(semantic_corpus: SemanticCorpus) -> None:
    """Parafraza bez wspolnych slow ma wyniki w hybrydzie, a nie ma ich w trybie dokladnym."""
    query = "jak sfinansowac wlasny dom dlugoterminowa pozyczka bankowa"

    dokladne = semantic_corpus.search(query, mode=SearchMode.EXACT, limit=10)
    hybrydowe = semantic_corpus.search(query, mode=SearchMode.HYBRID, limit=10)

    assert dokladne.hits == []
    assert "kredyt" in semantic_corpus.ranking(hybrydowe)[:3]


@pytest.mark.requires_model
def test_hybryda_nie_gubi_dokumentow_trybu_dokladnego(semantic_corpus: SemanticCorpus) -> None:
    """Kazdy dokument znaleziony doslownie musi byc takze w wyniku hybrydowym."""
    query = ACCOUNT_SPACED

    dokladne = {hit.doc_id for hit in semantic_corpus.search(query, mode=SearchMode.EXACT).hits}
    hybrydowe = {
        hit.doc_id for hit in semantic_corpus.search(query, mode=SearchMode.HYBRID, limit=50).hits
    }

    assert dokladne
    assert dokladne <= hybrydowe


@pytest.mark.requires_model
def test_odpowiedz_opisuje_sposob_laczenia(semantic_corpus: SemanticCorpus) -> None:
    """Uzytkownik dostaje informacje, ze wynik powstal z polaczenia dwoch list."""
    response = semantic_corpus.search(
        "zlecenie stale obciazenia rachunku", mode=SearchMode.HYBRID, limit=5
    )

    assert HYBRID_NOTE in response.notes
    assert response.total_is_exact is False


@pytest.mark.requires_model
def test_ranking_hybrydowy_jest_powtarzalny(semantic_corpus: SemanticCorpus) -> None:
    """Dwa identyczne zapytania daja identyczny ranking."""
    query = "faktura za przesylki kurierskie na 314 zl"

    pierwszy = semantic_corpus.ranking(semantic_corpus.search(query, mode=SearchMode.HYBRID))
    drugi = semantic_corpus.ranking(semantic_corpus.search(query, mode=SearchMode.HYBRID))

    assert pierwszy == drugi


# --- zachowanie bez warstwy wektorowej -------------------------------------------


def test_bez_modelu_hybryda_schodzi_do_trybu_dokladnego(corpus: SearchCorpus) -> None:
    """Brak wektorow nie moze wylaczyc wyszukiwania, tylko ograniczyc je do trybu dokladnego."""
    response = corpus.search(ACCOUNT_SPACED, mode=SearchMode.HYBRID, limit=50)

    assert NO_SEMANTIC_NOTE in response.notes
    assert len(response.hits) > 0


def test_bez_modelu_hybryda_daje_ten_sam_zbior_co_tryb_dokladny(corpus: SearchCorpus) -> None:
    """Zejscie do trybu dokladnego zwraca dokladnie ten sam zbior dokumentow."""
    dokladne = {hit.doc_id for hit in corpus.search(ACCOUNT_SPACED, limit=50).hits}
    hybrydowe = {
        hit.doc_id for hit in corpus.search(ACCOUNT_SPACED, mode=SearchMode.HYBRID, limit=50).hits
    }

    assert dokladne == hybrydowe


def test_puste_zapytanie_w_trybie_hybrydowym(corpus: SearchCorpus) -> None:
    """Pusty tekst konczy sie pusta odpowiedzia, a nie wyjatkiem."""
    response = corpus.search("   ", mode=SearchMode.HYBRID)

    assert response.hits == []


def test_paginacja_w_trybie_hybrydowym_nie_powtarza_dokumentow(corpus: SearchCorpus) -> None:
    """Kolejne strony wyniku hybrydowego nie zwracaja tego samego dokumentu dwa razy."""
    identyfikatory = corpus.paginate(ACCOUNT_SPACED, mode=SearchMode.HYBRID, limit=5)

    assert len(identyfikatory) == len(set(identyfikatory))


def test_filtry_dzialaja_takze_w_trybie_hybrydowym(corpus: SearchCorpus) -> None:
    """Filtr typu pliku ogranicza wynik hybrydowy tak samo jak dokladny."""
    from finddocs.types import SearchFilters

    response = corpus.search(
        ACCOUNT_SPACED,
        mode=SearchMode.HYBRID,
        filters=SearchFilters(extensions=[".pdf"]),
        limit=50,
    )

    assert response.hits
    for hit in response.hits:
        assert hit.name.endswith(".pdf")


def test_liczba_fragmentow_na_dokument_jest_ograniczona(corpus: SearchCorpus) -> None:
    """Wynik pokazuje kilka najlepszych fragmentow, a nie caly dokument."""
    response = corpus.search("inwentaryzacja", mode=SearchMode.HYBRID, max_chunks=2, limit=10)

    assert response.hits
    for hit in response.hits:
        assert 1 <= len(hit.chunks) <= 2


def test_odpowiedz_podaje_tryb_faktycznie_uzyty(corpus: SearchCorpus) -> None:
    """Po zejsciu do trybu dokladnego odpowiedz nie udaje, ze liczyla wektory."""
    service = SearchService(corpus.index)

    response = service.search(SearchRequest(query=ACCOUNT_SPACED, mode=SearchMode.HYBRID, limit=5))

    assert response.mode is SearchMode.EXACT
    assert NO_SEMANTIC_NOTE in response.notes
    assert response.total_is_exact is True
    assert response.took_ms >= 0
