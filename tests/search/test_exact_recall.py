"""Kompletnosc wyszukiwania dokladnego.

Wymaganie ze specyfikacji (rozdzial 26.1): jesli numer rachunku wystepuje w 17
poprawnie zaindeksowanych dokumentach, uzytkownik musi miec mozliwosc dotarcia do
wszystkich 17. Nie wolno ukrywac wynikow ani stosowac limitu w rodzaju
"pierwsze 10".
"""

from __future__ import annotations

import pytest

from conftest import (
    ACCOUNT_DOCUMENTS,
    ACCOUNT_VARIANTS,
    COMMON_WORD,
    SearchCorpus,
)
from finddocs.types import SearchFilters, SearchMode

PAGE = 5


def test_numer_rachunku_zwraca_dokladnie_17_dokumentow(corpus: SearchCorpus) -> None:
    expected = corpus.ids_with("rachunek")
    assert len(expected) == ACCOUNT_DOCUMENTS

    response = corpus.search(ACCOUNT_VARIANTS[0], mode=SearchMode.EXACT, limit=100)

    assert response.total_documents == ACCOUNT_DOCUMENTS
    assert {hit.doc_id for hit in response.hits} == expected
    assert len(response.hits) == ACCOUNT_DOCUMENTS


@pytest.mark.parametrize("query", ACCOUNT_VARIANTS)
def test_paginacja_daje_dokladnie_te_same_dokumenty(corpus: SearchCorpus, query: str) -> None:
    """Przejscie przez wszystkie strony po 5 wynikow daje komplet, bez powtorzen."""
    expected = corpus.ids_with("rachunek")

    collected = corpus.paginate(query, mode=SearchMode.EXACT, limit=PAGE)

    assert len(collected) == ACCOUNT_DOCUMENTS, "paginacja zgubila albo powielila dokumenty"
    assert len(set(collected)) == len(collected), "ten sam dokument pojawil sie na dwoch stronach"
    assert set(collected) == expected


@pytest.mark.parametrize("query", ACCOUNT_VARIANTS)
def test_kazdy_zapis_numeru_daje_ten_sam_zbior(corpus: SearchCorpus, query: str) -> None:
    """Zapis ciagly, ze spacjami i z myslnikami musi dawac identyczny wynik."""
    response = corpus.search(query, mode=SearchMode.EXACT, limit=100)

    assert response.total_documents == ACCOUNT_DOCUMENTS
    assert {hit.doc_id for hit in response.hits} == corpus.ids_with("rachunek")


def test_wyniki_obejmuja_wszystkie_trzy_zapisy_w_dokumentach(corpus: SearchCorpus) -> None:
    """Jedno zapytanie znajduje dokumenty niezaleznie od zapisu numeru w tresci."""
    response = corpus.search(ACCOUNT_VARIANTS[0], mode=SearchMode.EXACT, limit=100)
    found = {hit.doc_id for hit in response.hits}

    for feature in ("rachunek-spacje", "rachunek-myslniki", "rachunek-ciagly"):
        subset = corpus.ids_with(feature)
        assert subset, f"korpus nie ma dokumentow z cecha {feature}"
        assert subset <= found


@pytest.mark.parametrize("query", ACCOUNT_VARIANTS)
def test_all_matching_documents_zwraca_ten_sam_zbior(corpus: SearchCorpus, query: str) -> None:
    """Eksport pelnej listy musi zgadzac sie z lista przechodzona strona po stronie."""
    exported = corpus.service.all_matching_documents(query)
    paged = corpus.paginate(query, mode=SearchMode.EXACT, limit=PAGE)

    assert len(exported) == len(set(exported)) == ACCOUNT_DOCUMENTS
    assert set(exported) == set(paged) == corpus.ids_with("rachunek")


def test_brak_ukrytego_limitu_dla_zapytania_o_caly_korpus(corpus: SearchCorpus) -> None:
    """Zapytanie pasujace do wszystkich dokumentow zwraca pelna liczbe i pelna liste."""
    response = corpus.search(COMMON_WORD, mode=SearchMode.EXACT, limit=PAGE)

    assert response.total_documents == corpus.total
    assert len(response.hits) == PAGE, "pierwsza strona ma miec dokladnie tyle wynikow, ile limit"

    collected = corpus.paginate(COMMON_WORD, mode=SearchMode.EXACT, limit=PAGE)
    assert len(collected) == corpus.total
    assert set(collected) == corpus.all_ids()


def test_paginacja_dochodzi_do_ostatniego_dokumentu(corpus: SearchCorpus) -> None:
    """Ostatnia strona zawiera ostatni dokument i nic wiecej."""
    collected = corpus.paginate(COMMON_WORD, mode=SearchMode.EXACT, limit=PAGE)
    last_offset = corpus.total - 1

    tail = corpus.search(COMMON_WORD, mode=SearchMode.EXACT, limit=PAGE, offset=last_offset)
    assert [hit.doc_id for hit in tail.hits] == [collected[-1]]

    past_end = corpus.search(COMMON_WORD, mode=SearchMode.EXACT, limit=PAGE, offset=corpus.total)
    assert past_end.hits == []
    assert past_end.total_documents == corpus.total


def test_total_is_exact_w_trybie_dokladnym(corpus: SearchCorpus) -> None:
    for query in (ACCOUNT_VARIANTS[0], COMMON_WORD, "hipopotam"):
        response = corpus.search(query, mode=SearchMode.EXACT, limit=PAGE)
        assert response.total_is_exact is True
        assert response.mode is SearchMode.EXACT


def test_liczba_dokumentow_nie_zalezy_od_rozmiaru_strony(corpus: SearchCorpus) -> None:
    """Wartosc total_documents jest liczona osobno od paginacji."""
    small = corpus.search(ACCOUNT_VARIANTS[0], mode=SearchMode.EXACT, limit=1)
    large = corpus.search(ACCOUNT_VARIANTS[0], mode=SearchMode.EXACT, limit=100)

    assert small.total_documents == large.total_documents == ACCOUNT_DOCUMENTS
    assert len(small.hits) == 1


def test_filtr_nie_psuje_kompletnosci(corpus: SearchCorpus) -> None:
    """Po zawezeniu filtrem nadal widac wszystkie pasujace dokumenty."""
    filters = SearchFilters(extensions=[".pdf"])
    expected = {
        corpus.doc_ids[doc.key]
        for doc in corpus.docs
        if "rachunek" in doc.features and doc.extension == ".pdf"
    }
    assert expected, "korpus nie ma dokumentow z numerem rachunku w formacie pdf"

    response = corpus.search(ACCOUNT_VARIANTS[0], mode=SearchMode.EXACT, filters=filters, limit=100)
    collected = corpus.paginate(
        ACCOUNT_VARIANTS[0], mode=SearchMode.EXACT, filters=filters, limit=2
    )

    assert response.total_documents == len(expected)
    assert set(collected) == expected
    assert set(corpus.service.all_matching_documents(ACCOUNT_VARIANTS[0], filters)) == expected
