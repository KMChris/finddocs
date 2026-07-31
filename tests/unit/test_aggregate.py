"""Testy scalania list kandydatow i agregacji wynikow na poziomie dokumentu."""

from __future__ import annotations

import pytest

from finddocs.search.aggregate import (
    DEFAULT_RRF_K,
    RankedCandidate,
    deduplicate_texts,
    group_by_document,
    normalize_scores,
    reciprocal_rank_fusion,
    similarity,
)

#: Lista z wyszukiwania pelnotekstowego: (chunk_id, doc_id, wlasny wynik).
LISTA_FTS = [(1, 10, 5.0), (2, 20, 4.0), (3, 30, 3.0)]

#: Lista z wyszukiwania wektorowego.
LISTA_WEKTOROWA = [(2, 20, 0.9), (4, 40, 0.8), (5, 50, 0.7)]


def scal(k: int = DEFAULT_RRF_K) -> list[RankedCandidate]:
    """Scalenie obu list z jednakowymi wagami."""
    return reciprocal_rank_fusion([("fts", LISTA_FTS, 1.0), ("vector", LISTA_WEKTOROWA, 1.0)], k=k)


# --- reciprocal rank fusion ----------------------------------------------------


def test_dokument_z_obu_list_wygrywa_z_dokumentem_z_jednej():
    scalone = scal()
    najlepszy = scalone[0]

    assert najlepszy.chunk_id == 2
    assert najlepszy.from_fts is True
    assert najlepszy.from_vector is True
    # Fragment 1 jest pierwszy na liscie FTS, ale wystepuje tylko na niej.
    tylko_fts = next(c for c in scalone if c.chunk_id == 1)
    assert najlepszy.score > tylko_fts.score


def test_rrf_zapamietuje_pozycje_i_wyniki_wlasne():
    scalone = {c.chunk_id: c for c in scal()}

    assert scalone[1].fts_rank == 1
    assert scalone[1].fts_score == 5.0
    assert scalone[1].vector_rank is None
    assert scalone[2].fts_rank == 2
    assert scalone[2].vector_rank == 1
    assert scalone[4].vector_rank == 2
    assert scalone[4].fts_score is None


def test_rrf_liczy_sume_odwrotnosci_pozycji():
    scalone = {c.chunk_id: c for c in scal(k=60)}
    assert scalone[2].score == pytest.approx(1 / 62 + 1 / 61)
    assert scalone[1].score == pytest.approx(1 / 61)


def test_rrf_uwzglednia_wagi_list():
    scalone = reciprocal_rank_fusion([("fts", LISTA_FTS, 0.0), ("vector", LISTA_WEKTOROWA, 2.0)])
    assert scalone[0].chunk_id == 2
    assert next(c for c in scalone if c.chunk_id == 1).score == 0.0


def test_rrf_zachowuje_identyfikator_dokumentu():
    assert {c.chunk_id: c.doc_id for c in scal()} == {1: 10, 2: 20, 3: 30, 4: 40, 5: 50}


def test_rrf_pustych_list():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([("fts", [], 1.0)]) == []


# --- grupowanie po dokumencie --------------------------------------------------


def kandydaci() -> list[RankedCandidate]:
    """Trzy fragmenty dokumentu 10 i jeden fragment dokumentu 20."""
    return [
        RankedCandidate(chunk_id=1, doc_id=10, score=1.0, fts_rank=1),
        RankedCandidate(chunk_id=2, doc_id=10, score=0.8, fts_rank=2),
        RankedCandidate(chunk_id=3, doc_id=10, score=0.6, vector_rank=1),
        RankedCandidate(chunk_id=4, doc_id=20, score=0.95, fts_rank=3),
    ]


def test_group_by_document_tryb_max():
    grupy = {g.doc_id: g.score for g in group_by_document(kandydaci(), combine="max")}
    assert grupy == {10: 1.0, 20: 0.95}


def test_group_by_document_tryb_sum():
    grupy = {g.doc_id: g.score for g in group_by_document(kandydaci(), combine="sum")}
    assert grupy[10] == pytest.approx(2.4)
    assert grupy[20] == pytest.approx(0.95)


def test_group_by_document_tryb_max_plus_tail():
    grupy = group_by_document(kandydaci(), combine="max_plus_tail", max_chunks=3)
    najlepszy = grupy[0]

    # Najlepszy fragment plus malejacy udzial kolejnych: 1.0 + 0.8/2 + 0.6/3.
    assert najlepszy.doc_id == 10
    assert najlepszy.score == pytest.approx(1.0 + 0.4 + 0.2)
    assert grupy[1].score == pytest.approx(0.95)


def test_tryb_max_nie_premiuje_wielu_trafien_a_max_plus_tail_premiuje():
    max_wyniki = {g.doc_id: g.score for g in group_by_document(kandydaci(), combine="max")}
    tail_wyniki = {g.doc_id: g.score for g in group_by_document(kandydaci())}

    assert max_wyniki[10] > max_wyniki[20]
    assert tail_wyniki[10] > max_wyniki[10]
    assert tail_wyniki[20] == max_wyniki[20]


def test_group_by_document_sortuje_fragmenty_i_oznacza_zrodla():
    grupa = group_by_document(kandydaci())[0]

    assert [c.chunk_id for c in grupa.candidates] == [1, 2, 3]
    assert grupa.from_fts is True
    assert grupa.from_vector is True


def test_group_by_document_pusta_lista():
    assert group_by_document([]) == []


# --- deduplikacja --------------------------------------------------------------


TEKST_BAZOWY = (
    "Platnosc karta numer 384675 na kwote 314 zl zostala zaksiegowana w oddziale "
    "Lodz dnia 24 lipca 2015 roku przez pracownika dzialu obslugi klienta."
)
TEKST_PRAWIE_TAKI_SAM = TEKST_BAZOWY + " Uwaga koncowa."
TEKST_INNY = (
    "Zupelnie inny dokument opisujacy procedure udzielania kredytu hipotecznego "
    "dla klientow indywidualnych w roku 2020."
)


def test_deduplicate_texts_usuwa_prawie_identyczne_fragmenty():
    zachowane = deduplicate_texts([(1, TEKST_BAZOWY), (2, TEKST_PRAWIE_TAKI_SAM), (3, TEKST_INNY)])
    assert zachowane == [1, 3]


def test_deduplicate_texts_zachowuje_kolejnosc_wejsciowa():
    zachowane = deduplicate_texts([(3, TEKST_INNY), (1, TEKST_BAZOWY), (2, TEKST_PRAWIE_TAKI_SAM)])
    assert zachowane == [3, 1]


def test_deduplicate_texts_z_wysokim_progiem_niczego_nie_usuwa():
    zachowane = deduplicate_texts([(1, TEKST_BAZOWY), (2, TEKST_PRAWIE_TAKI_SAM)], threshold=1.01)
    assert zachowane == [1, 2]


def test_similarity_ignoruje_wielkosc_liter_i_polskie_znaki():
    assert similarity(TEKST_BAZOWY, TEKST_BAZOWY.upper()) == pytest.approx(1.0)
    assert similarity(TEKST_BAZOWY, TEKST_INNY) == 0.0
    assert similarity("", "cokolwiek") == 0.0


# --- normalizacja ocen ---------------------------------------------------------


def test_normalize_scores_odnosi_wyniki_do_najlepszego():
    grupy = group_by_document(kandydaci())
    wyniki = normalize_scores(grupy)

    assert wyniki[10] == pytest.approx(1.0)
    assert 0.0 < wyniki[20] < 1.0
    assert all(0.0 <= wartosc <= 1.0 for wartosc in wyniki.values())


def test_normalize_scores_dla_pustej_listy_i_zerowych_ocen():
    assert normalize_scores([]) == {}
    zerowe = group_by_document([RankedCandidate(chunk_id=1, doc_id=7, score=0.0)])
    assert normalize_scores(zerowe) == {7: 0.0}
