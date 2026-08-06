"""Wylaczanie indeksowania semantycznego.

Flaga ``embedding.semantic_enabled`` pomija ladowanie dostawcy embeddingow
i indeksu wektorowego. Indeks pelnotekstowy dziala normalnie, dokumenty koncza
w statusie INDEXED, a po ponownym wlaczeniu zwykle skanowanie uzupelnia
brakujace wektory, bo dokumenty bez wektorow kwalifikuja sie do przetworzenia.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from finddocs.indexing.service import IndexService
from finddocs.providers.model_manifest import find_model_dir
from finddocs.search.service import SearchService
from finddocs.types import DocumentStatus, JobKind, SearchMode, SearchRequest

CORPUS: dict[str, str] = {
    "alfa.txt": "Procedura przelewow krajowych. Slowo rozpoznawcze: kolczatka.\n",
    "beta.txt": "Harmonogram szkolen na drugi kwartal. Slowo rozpoznawcze: wiewiorka.\n",
}


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "zrodlo"
    root.mkdir(parents=True, exist_ok=True)
    for name, content in CORPUS.items():
        (root / name).write_text(content, encoding="utf-8")
    return root


def test_wylaczona_semantyka_nie_laduje_dostawcy(app_config):
    app_config.embedding.semantic_enabled = False

    service = IndexService(app_config)
    service.open(load_provider=True)
    try:
        assert service.provider is None
        assert service.vector_store is None
        assert not service.semantic_available
        # Swiadome wylaczenie nie generuje zadnych uwag startowych.
        assert service.notes == []
        assert not service.rebuild_required
        assert service.status().to_dict()["semantyka_dostepna"] is False
    finally:
        service.close()


def test_indeksowanie_bez_semantyki_daje_status_indexed(
    indexing_config, corpus, run_job, document_statuses
):
    config = indexing_config(corpus)
    config.embedding.semantic_enabled = False

    service = IndexService(config)
    service.open(load_provider=True)
    try:
        snapshot = run_job(config, service)

        assert snapshot.processed == len(CORPUS)
        assert snapshot.failed == 0
        # Bez indeksu wektorowego dokument jest kompletny, nie czesciowy.
        assert document_statuses(service) == dict.fromkeys(CORPUS, DocumentStatus.INDEXED.value)
        assert service.repository.count_vectors() == 0

        # Tryby semantyczne przelaczaja sie na dokladny i informuja o tym.
        response = SearchService(service).search(
            SearchRequest(query="kolczatka", mode=SearchMode.HYBRID)
        )
        assert response.mode is SearchMode.EXACT
        assert response.total_documents == 1
        assert any("dokładnego" in note for note in response.notes)
    finally:
        service.close()


@pytest.mark.slow
@pytest.mark.requires_model
def test_ponowne_wlaczenie_uzupelnia_wektory_zwyklym_skanowaniem(indexing_config, corpus, run_job):
    config = indexing_config(corpus)
    if find_model_dir(config.embedding.model_key) is None:
        pytest.skip("Brak lokalnego modelu embeddingow w katalogu models/.")

    config.embedding.semantic_enabled = False
    service = IndexService(config)
    service.open(load_provider=True)
    try:
        run_job(config, service)
        assert service.repository.count_vectors() == 0
    finally:
        service.close()

    config.embedding.semantic_enabled = True
    service = IndexService(config)
    service.open(load_provider=True)
    if service.provider is None or service.vector_store is None:
        service.close()
        pytest.skip("Dostawca embeddingow nie zostal zaladowany.")
    try:
        # Zwykle skanowanie, bez wymuszania: dokumenty bez wektorow i tak
        # kwalifikuja sie do ponownego przetworzenia.
        snapshot = run_job(config, service, kind=JobKind.RESCAN)

        assert snapshot.processed == len(CORPUS)
        assert service.repository.count_vectors() >= len(CORPUS)
        assert service.vector_store.count() == service.repository.count_vectors()

        response = SearchService(service).search(
            SearchRequest(query="zwierzę kolczatka", mode=SearchMode.SEMANTIC)
        )
        assert response.mode is SearchMode.SEMANTIC
        assert response.hits
    finally:
        service.close()
