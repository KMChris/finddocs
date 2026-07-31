"""Testy jakosci wyszukiwania semantycznego.

Zapytania sa parafrazami: nie maja wspolnych slow z dokumentem, ktory maja
znalezc. Wyszukiwanie dokladne nie ma tu szans, wiec test mierzy dokladnie to,
co wnosi warstwa wektorowa.

Miary policzone na korpusie z ``conftest.py``: recall@k, precision@k, MRR oraz
nDCG@k. Progi sa celowo ostrozne, bo korpus jest maly, a model dziala na CPU
w wersji INT8. Chodzi o wykrycie regresji, nie o rekord na liscie rankingowej.

Testy sa pomijane, gdy w katalogu ``models/`` nie ma modelu embeddingow.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import pytest

from conftest import SemanticCase, SemanticCorpus
from finddocs.search.service import SEMANTIC_NOTE
from finddocs.types import SearchMode

pytestmark = pytest.mark.requires_model

#: Glebokosc rankingu, na ktorej licza sie miary jakosci.
K = 5

#: Minimalny udzial zapytan, dla ktorych dokument istotny jest w pierwszej piatce.
MIN_RECALL_AT_K = 0.75

#: Minimalny sredni odwrotny rank. 0,5 odpowiada srednio drugiej pozycji.
MIN_MRR = 0.5

#: Minimalne srednie nDCG@5.
MIN_NDCG = 0.55


def _reciprocal_rank(ranking: Sequence[str], relevant: Sequence[str]) -> float:
    for position, key in enumerate(ranking, start=1):
        if key in relevant:
            return 1.0 / position
    return 0.0


def _precision_at_k(ranking: Sequence[str], relevant: Sequence[str], k: int) -> float:
    if k <= 0:
        return 0.0
    trafienia = sum(1 for key in ranking[:k] if key in relevant)
    return trafienia / k


def _recall_at_k(ranking: Sequence[str], relevant: Sequence[str], k: int) -> float:
    if not relevant:
        return 0.0
    trafienia = sum(1 for key in ranking[:k] if key in relevant)
    return trafienia / len(relevant)


def _ndcg_at_k(ranking: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """nDCG z ocena binarna: dokument jest istotny albo nie."""
    gain = 0.0
    for position, key in enumerate(ranking[:k], start=1):
        if key in relevant:
            gain += 1.0 / math.log2(position + 1)
    ideal = sum(1.0 / math.log2(position + 1) for position in range(1, min(len(relevant), k) + 1))
    return gain / ideal if ideal else 0.0


def _ranking(corpus: SemanticCorpus, case: SemanticCase) -> list[str]:
    response = corpus.search(case.query, mode=SearchMode.SEMANTIC, limit=K * 2)
    return corpus.ranking(response)


# --- pojedyncze zapytania --------------------------------------------------------


def test_kazde_zapytanie_zwraca_wyniki(semantic_corpus: SemanticCorpus) -> None:
    """Tryb semantyczny nigdy nie zwraca pustej listy dla sensownego zapytania."""
    for case in semantic_corpus.cases:
        response = semantic_corpus.search(case.query, mode=SearchMode.SEMANTIC, limit=K)
        assert response.hits, f"brak wynikow dla zapytania: {case.query}"


def test_parafraza_trafia_w_dokument_bez_wspolnych_slow(
    semantic_corpus: SemanticCorpus,
) -> None:
    """Zapytanie o kredyt hipoteczny opisany innymi slowami znajduje umowe kredytu."""
    ranking = _ranking(
        semantic_corpus,
        SemanticCase(
            query="jak sfinansowac wlasny dom dlugoterminowa pozyczka bankowa", relevant=("kredyt",)
        ),
    )

    assert "kredyt" in ranking[:3]


def test_wyszukiwanie_dokladne_nie_znajduje_parafrazy(
    semantic_corpus: SemanticCorpus,
) -> None:
    """Kontrola negatywna: bez warstwy wektorowej tych dokumentow nie da sie znalezc."""
    case = semantic_corpus.cases[0]

    response = semantic_corpus.search(case.query, mode=SearchMode.EXACT, limit=K)

    assert semantic_corpus.ranking(response) == []


# --- miary jakosci ---------------------------------------------------------------


def test_recall_at_k(semantic_corpus: SemanticCorpus) -> None:
    """Dokument istotny jest w pierwszej piatce dla wiekszosci zapytan."""
    wyniki = [
        _recall_at_k(_ranking(semantic_corpus, case), case.relevant, K)
        for case in semantic_corpus.cases
    ]
    srednia = sum(wyniki) / len(wyniki)

    assert srednia >= MIN_RECALL_AT_K, f"recall@{K} = {srednia:.2f}"


def test_mrr(semantic_corpus: SemanticCorpus) -> None:
    """Sredni odwrotny rank pokazuje, jak wysoko trafia poprawny dokument."""
    wyniki = [
        _reciprocal_rank(_ranking(semantic_corpus, case), case.relevant)
        for case in semantic_corpus.cases
    ]
    srednia = sum(wyniki) / len(wyniki)

    assert srednia >= MIN_MRR, f"MRR = {srednia:.2f}"


def test_ndcg_at_k(semantic_corpus: SemanticCorpus) -> None:
    """nDCG karze zepchniecie poprawnego dokumentu nizej w rankingu."""
    wyniki = [
        _ndcg_at_k(_ranking(semantic_corpus, case), case.relevant, K)
        for case in semantic_corpus.cases
    ]
    srednia = sum(wyniki) / len(wyniki)

    assert srednia >= MIN_NDCG, f"nDCG@{K} = {srednia:.2f}"


def test_precision_at_1_dla_zapytan_z_jednym_dokumentem(
    semantic_corpus: SemanticCorpus,
) -> None:
    """Przy jednym dokumencie istotnym precision@1 rowna sie trafieniu w czolo."""
    trafienia = 0
    for case in semantic_corpus.cases:
        ranking = _ranking(semantic_corpus, case)
        trafienia += int(_precision_at_k(ranking, case.relevant, 1) > 0)

    assert trafienia >= len(semantic_corpus.cases) // 2


# --- umowa interfejsu ------------------------------------------------------------


def test_odpowiedz_ostrzega_o_przyblizeniu(semantic_corpus: SemanticCorpus) -> None:
    """Interfejs musi powiedziec, ze ranking semantyczny nie gwarantuje kompletnosci."""
    response = semantic_corpus.search(
        semantic_corpus.cases[0].query, mode=SearchMode.SEMANTIC, limit=K
    )

    assert response.total_is_exact is False
    assert SEMANTIC_NOTE in response.notes


def test_wyniki_maja_fragmenty_i_ocene(semantic_corpus: SemanticCorpus) -> None:
    """Kazde trafienie ma co najmniej jeden fragment i wynik z zakresu 0 do 1."""
    response = semantic_corpus.search(
        semantic_corpus.cases[1].query, mode=SearchMode.SEMANTIC, limit=K
    )

    for hit in response.hits:
        assert hit.chunks, f"dokument {hit.doc_id} bez fragmentow"
        assert 0.0 <= hit.score <= 1.0


def test_ranking_jest_powtarzalny(semantic_corpus: SemanticCorpus) -> None:
    """To samo zapytanie daje ten sam ranking, bez losowosci w embeddingach."""
    case = semantic_corpus.cases[2]

    pierwszy = _ranking(semantic_corpus, case)
    drugi = _ranking(semantic_corpus, case)

    assert pierwszy == drugi


def test_puste_zapytanie_nie_wywraca_wyszukiwania(semantic_corpus: SemanticCorpus) -> None:
    """Pusty tekst konczy sie pusta odpowiedzia, a nie wyjatkiem."""
    response = semantic_corpus.search("   ", mode=SearchMode.SEMANTIC, limit=K)

    assert response.hits == []


def test_limit_wynikow_jest_respektowany(semantic_corpus: SemanticCorpus) -> None:
    """Liczba zwroconych dokumentow nie przekracza zadanego limitu."""
    response = semantic_corpus.search(
        semantic_corpus.cases[0].query, mode=SearchMode.SEMANTIC, limit=3
    )

    assert len(response.hits) <= 3


def test_model_jest_zapisany_w_metadanych_indeksu(semantic_corpus: SemanticCorpus) -> None:
    """Indeks pamieta, ktorym modelem policzono wektory."""
    status = semantic_corpus.index.status()

    assert status.model_key
    assert status.model_dimension is not None
    assert status.model_dimension > 0
    assert status.vectors > 0
    assert semantic_corpus.index.semantic_available is True
