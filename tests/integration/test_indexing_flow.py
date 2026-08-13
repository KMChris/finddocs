"""Pelny przeplyw indeksowania katalogu lokalnego, bez modelu embeddingow.

Testy sprawdzaja cykl zycia dokumentu w indeksie: pierwsze indeksowanie, wykrycie
braku zmian, dodanie pliku, modyfikacje, usuniecie, plik uszkodzony, wznowienie po
przerwaniu oraz transakcyjnosc zapisu.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from finddocs.config import AppConfig, LocalDirSourceSettings
from finddocs.indexing.repository import Repository
from finddocs.indexing.service import IndexService
from finddocs.jobs.control import JobControl
from finddocs.types import DocumentStatus, JobKind, JobState, ProgressSnapshot

#: Male dokumenty tekstowe. Kazdy ma slowo wystepujace tylko w nim.
CORPUS: dict[str, str] = {
    "alfa.txt": (
        "Notatka pierwsza z przegladu procedur wewnetrznych.\n"
        "Slowo rozpoznawcze tego dokumentu to kolczatka.\n"
        "Dokument testowy, dane fikcyjne.\n"
    ),
    "beta.txt": (
        "Notatka druga z przegladu procedur wewnetrznych.\n"
        "Slowo rozpoznawcze tego dokumentu to wiewiorka.\n"
        "Dokument testowy, dane fikcyjne.\n"
    ),
    "gamma.txt": (
        "Notatka trzecia z przegladu procedur wewnetrznych.\n"
        "Slowo rozpoznawcze tego dokumentu to jezozwierz.\n"
        "Dokument testowy, dane fikcyjne.\n"
    ),
}


def write_corpus(root: Path, files: dict[str, str]) -> Path:
    """Zapisuje zbior testowy w podanym katalogu."""
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")
    return root


def touch_later(path: Path, seconds: int = 120) -> None:
    """Przesuwa czas modyfikacji pliku, zeby klucz zmiany na pewno byl inny."""
    info = path.stat()
    os.utime(path, (info.st_atime + seconds, info.st_mtime + seconds))


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    return write_corpus(tmp_path / "zrodlo", CORPUS)


@pytest.fixture
def prepared(indexing_config: Callable[..., AppConfig], corpus: Path) -> tuple[AppConfig, Path]:
    """Konfiguracja z jednym zrodlem lokalnym wskazujacym na zbior testowy."""
    return indexing_config(corpus), corpus


# --- pierwsze indeksowanie -------------------------------------------------------


def test_pierwsze_indeksowanie_liczy_wykryte_przetworzone_i_bledy(
    prepared: tuple[AppConfig, Path],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
    document_statuses: Callable[[IndexService], dict[str, str]],
    exact_search_count: Callable[[IndexService, str], int],
) -> None:
    config, _root = prepared

    snapshot = run_job(config, index_service)

    assert snapshot.state is JobState.COMPLETED
    assert snapshot.discovered == len(CORPUS)
    assert snapshot.processed == len(CORPUS)
    assert snapshot.failed == 0
    assert snapshot.skipped == 0
    assert snapshot.unchanged == 0
    assert snapshot.discovery_complete is True

    assert document_statuses(index_service) == dict.fromkeys(CORPUS, DocumentStatus.INDEXED.value)
    assert index_service.repository.count_chunks() >= len(CORPUS)
    assert exact_search_count(index_service, "kolczatka") == 1


# --- brak zmian ------------------------------------------------------------------


def test_ponowne_skanowanie_bez_zmian_nie_przetwarza_niczego(
    prepared: tuple[AppConfig, Path],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
) -> None:
    config, _root = prepared
    run_job(config, index_service)

    powtorne = run_job(config, index_service, kind=JobKind.RESCAN)

    assert powtorne.state is JobState.COMPLETED
    assert powtorne.discovered == len(CORPUS)
    assert powtorne.processed == 0
    assert powtorne.unchanged == len(CORPUS)
    assert powtorne.failed == 0


# --- nowy plik -------------------------------------------------------------------


def test_dodanie_pliku_przetwarza_tylko_jego(
    prepared: tuple[AppConfig, Path],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
    exact_search_count: Callable[[IndexService, str], int],
) -> None:
    config, root = prepared
    run_job(config, index_service)

    (root / "delta.txt").write_text(
        "Notatka czwarta dopisana po pierwszym indeksowaniu.\n"
        "Slowo rozpoznawcze tego dokumentu to szczypiorek.\n",
        encoding="utf-8",
    )
    snapshot = run_job(config, index_service, kind=JobKind.RESCAN)

    assert snapshot.processed == 1
    assert snapshot.unchanged == len(CORPUS)
    assert snapshot.discovered == len(CORPUS) + 1
    assert exact_search_count(index_service, "szczypiorek") == 1


# --- modyfikacja -----------------------------------------------------------------


def test_modyfikacja_pliku_usuwa_stara_tresc_z_wynikow(
    prepared: tuple[AppConfig, Path],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
    exact_search_count: Callable[[IndexService, str], int],
) -> None:
    config, root = prepared
    run_job(config, index_service)
    assert exact_search_count(index_service, "kolczatka") == 1

    plik = root / "alfa.txt"
    plik.write_text(
        "Notatka pierwsza po aktualizacji tresci dokumentu zrodlowego.\n"
        "Slowo rozpoznawcze zostalo zmienione na dziobak.\n"
        "Dokument testowy, dane fikcyjne, wersja druga.\n",
        encoding="utf-8",
    )
    touch_later(plik)

    snapshot = run_job(config, index_service, kind=JobKind.RESCAN)

    assert snapshot.processed == 1
    assert snapshot.unchanged == len(CORPUS) - 1
    assert exact_search_count(index_service, "dziobak") == 1
    # Stara tresc znika z indeksu razem ze starymi fragmentami dokumentu.
    assert exact_search_count(index_service, "kolczatka") == 0
    stare = index_service.db.query_scalar(
        "SELECT COUNT(*) FROM chunks WHERE folded LIKE '%kolczatka%'", (), 0
    )
    assert int(stare) == 0


# --- usuniecie -------------------------------------------------------------------


def test_usuniecie_pliku_znika_z_indeksu_i_z_wynikow(
    prepared: tuple[AppConfig, Path],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
    document_statuses: Callable[[IndexService], dict[str, str]],
    exact_search_count: Callable[[IndexService, str], int],
) -> None:
    config, root = prepared
    run_job(config, index_service)
    przed = int(index_service.db.query_scalar("SELECT COUNT(*) FROM documents", (), 0))

    (root / "beta.txt").unlink()
    snapshot = run_job(config, index_service, kind=JobKind.RESCAN)

    assert snapshot.deleted == 1
    po = int(index_service.db.query_scalar("SELECT COUNT(*) FROM documents", (), 0))
    assert po == przed - 1
    assert "beta.txt" not in document_statuses(index_service)
    assert exact_search_count(index_service, "wiewiorka") == 0
    assert exact_search_count(index_service, "kolczatka") == 1


# --- plik uszkodzony -------------------------------------------------------------


def test_uszkodzony_plik_nie_zatrzymuje_procesu_i_trafia_do_raportu(
    indexing_config: Callable[..., AppConfig],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
    document_statuses: Callable[[IndexService], dict[str, str]],
    tmp_path: Path,
) -> None:
    root = write_corpus(tmp_path / "zrodlo", CORPUS)
    (root / "uszkodzony.pdf").write_bytes(b"%PDF-1.7\nto nie jest poprawny plik PDF\n")
    config = indexing_config(root)

    snapshot = run_job(config, index_service)

    assert snapshot.state is JobState.COMPLETED
    assert snapshot.discovered == len(CORPUS) + 1
    assert snapshot.processed == len(CORPUS)
    assert snapshot.failed == 1

    statusy = document_statuses(index_service)
    assert statusy["uszkodzony.pdf"] == DocumentStatus.CORRUPTED.value
    assert statusy["alfa.txt"] == DocumentStatus.INDEXED.value

    niewyszukiwalne = index_service.repository.non_searchable_documents()
    assert [d.name for d in niewyszukiwalne] == ["uszkodzony.pdf"]
    assert niewyszukiwalne[0].error_code is not None
    assert index_service.repository.recent_errors()


# --- postep ----------------------------------------------------------------------


def test_postep_zna_liczbe_plikow_przed_koncem_wykrywania(
    prepared: tuple[AppConfig, Path],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
) -> None:
    """Bez mianownika pasek postepu chodzi bez wartosci przez cale zadanie."""
    config, _root = prepared
    ulamki: list[float | None] = []

    def zapamietaj(snapshot: ProgressSnapshot) -> None:
        if not snapshot.discovery_complete:
            ulamki.append(snapshot.progress_fraction)

    snapshot = run_job(config, index_service, on_progress=zapamietaj)

    assert snapshot.estimated_total == len(CORPUS)
    # Pierwsze zgloszenia sa sprzed policzenia plikow, ale w trakcie
    # przetwarzania postep jest juz wyrazony ulamkiem.
    assert any(wartosc is not None for wartosc in ulamki)
    assert all(0.0 <= wartosc <= 0.99 for wartosc in ulamki if wartosc is not None)


def test_kazdy_przebieg_liczy_pliki_od_nowa(
    prepared: tuple[AppConfig, Path],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
) -> None:
    """Mianownik pochodzi z policzenia zrodla, nie z liczby dokumentow w bazie.

    Liczba z poprzedniego przebiegu bywa mocno za mala. Gdy licznik
    przetworzonych ja przekroczy, pasek staje na koncu skali i zostaje tam do
    konca zadania, czyli mowi ,,prawie gotowe'' przez wieksza czesc pracy.
    """
    config, root = prepared
    run_job(config, index_service)
    for numer in range(5):
        (root / f"dopisany-{numer}.txt").write_text(
            f"Notatka dopisana po pierwszym indeksowaniu, numer {numer}.\n", encoding="utf-8"
        )

    snapshot = run_job(config, index_service, kind=JobKind.RESCAN)

    assert snapshot.estimated_total == len(CORPUS) + 5
    assert snapshot.discovered == len(CORPUS) + 5


def test_postep_mowi_ktore_zrodlo_z_ilu(
    indexing_config: Callable[..., AppConfig],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
    tmp_path: Path,
) -> None:
    """Przy kilku zrodlach same liczniki plikow nie mowia, ile pracy zostalo."""
    pierwszy = write_corpus(tmp_path / "pierwsze", CORPUS)
    drugi = write_corpus(tmp_path / "drugie", {"delta.txt": "Notatka czwarta.\n"})
    config = indexing_config(pierwszy)
    config.sources.append(replace(config.sources[0], source_id="drugie", label="Drugie źródło"))
    config.sources[1].local = LocalDirSourceSettings(root_path=str(drugi))
    pozycje: list[tuple[int, int]] = []

    snapshot = run_job(
        config,
        index_service,
        on_progress=lambda s: pozycje.append((s.source_index, s.source_count)),
    )

    assert snapshot.source_count == 2
    assert snapshot.source_index == 2
    assert (1, 2) in pozycje
    assert (2, 2) in pozycje
    assert snapshot.estimated_total == len(CORPUS) + 1


# --- slady po nieudanych probach -------------------------------------------------


def test_pelne_przeindeksowanie_zapomina_stare_bledy(
    indexing_config: Callable[..., AppConfig],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
    tmp_path: Path,
) -> None:
    """Naprawiony plik znika z obu list, bo pelny przebieg zaczyna od pustej."""
    root = write_corpus(tmp_path / "zrodlo", CORPUS)
    uszkodzony = root / "uszkodzony.pdf"
    uszkodzony.write_bytes(b"%PDF-1.7\nto nie jest poprawny plik PDF\n")
    config = indexing_config(root)

    run_job(config, index_service, kind=JobKind.FULL_INDEX, force_reindex=True)
    assert [d.name for d in index_service.repository.non_searchable_documents()] == [
        "uszkodzony.pdf"
    ]
    assert index_service.repository.recent_errors()

    uszkodzony.unlink()
    run_job(config, index_service, kind=JobKind.FULL_INDEX, force_reindex=True)

    assert index_service.repository.non_searchable_documents() == []
    assert index_service.repository.recent_errors() == []


def test_powtorzony_blad_wraca_na_liste_bez_duplikatow(
    indexing_config: Callable[..., AppConfig],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
    tmp_path: Path,
) -> None:
    """Ten sam plik psuje sie raz po raz, ale zostawia jeden wpis, nie stos."""
    root = write_corpus(tmp_path / "zrodlo", CORPUS)
    (root / "uszkodzony.pdf").write_bytes(b"%PDF-1.7\nto nie jest poprawny plik PDF\n")
    config = indexing_config(root)

    run_job(config, index_service, kind=JobKind.FULL_INDEX, force_reindex=True)
    po_pierwszym = index_service.repository.recent_errors()
    run_job(config, index_service, kind=JobKind.FULL_INDEX, force_reindex=True)
    po_drugim = index_service.repository.recent_errors()

    assert len(po_pierwszym) == 1
    assert len(po_drugim) == 1
    assert [d.name for d in index_service.repository.non_searchable_documents()] == [
        "uszkodzony.pdf"
    ]


def test_wpis_skierowany_do_ponownego_przetworzenia_znika_i_wraca(
    indexing_config: Callable[..., AppConfig],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
    tmp_path: Path,
) -> None:
    """Usuniecie wpisu z listy oddaje plik do ponownego skanowania.

    Bez wyczyszczenia klucza zmiany kolejne skanowanie uznaloby niezmieniony
    plik za zalatwiony i wpis nigdy by nie wrocil ani nie zostal potwierdzony.
    """
    root = write_corpus(tmp_path / "zrodlo", CORPUS)
    (root / "uszkodzony.pdf").write_bytes(b"%PDF-1.7\nto nie jest poprawny plik PDF\n")
    config = indexing_config(root)
    run_job(config, index_service, kind=JobKind.FULL_INDEX, force_reindex=True)
    repository = index_service.repository
    doc_id = repository.non_searchable_documents()[0].doc_id

    with index_service.db.transaction():
        assert repository.requeue_documents([doc_id]) == 1

    assert repository.recent_errors() == []
    assert repository.non_searchable_documents(include_pending=False) == []
    record = repository.get_document(doc_id)
    assert record is not None
    assert record.status is DocumentStatus.PENDING

    snapshot = run_job(config, index_service, kind=JobKind.RESCAN)

    assert snapshot.failed == 1
    assert len(repository.recent_errors()) == 1
    assert [d.name for d in repository.non_searchable_documents()] == ["uszkodzony.pdf"]


# --- checkpointy -----------------------------------------------------------------


def test_checkpoint_pozwala_dokonczyc_przerwane_zadanie(
    indexing_config: Callable[..., AppConfig],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
    document_statuses: Callable[[IndexService], dict[str, str]],
    source_id: str,
    tmp_path: Path,
) -> None:
    pliki = {
        f"plik-{numer}.txt": (
            f"Notatka numer {numer} z przegladu procedur wewnetrznych.\n"
            f"Slowo rozpoznawcze tego dokumentu to znacznik{numer}.\n"
        )
        for numer in range(1, 6)
    }
    root = write_corpus(tmp_path / "zrodlo", pliki)
    config = indexing_config(root)
    config.indexing.checkpoint_every = 1

    control = JobControl()

    def przerwij(snapshot: ProgressSnapshot) -> None:
        if snapshot.processed >= 2:
            control.cancel()

    pierwszy = run_job(
        config,
        index_service,
        control=control,
        on_progress=przerwij,
        resume_job_id="zadanie-testowe",
    )

    assert pierwszy.state is JobState.CANCELLED
    assert pierwszy.processed == 2
    checkpoint = index_service.repository.get_checkpoint(source_id, "zadanie-testowe")
    assert checkpoint is not None
    assert int(checkpoint["processed"]) == 2

    drugi = run_job(
        config,
        index_service,
        control=JobControl(),
        resume_job_id="zadanie-testowe",
    )

    assert drugi.state is JobState.COMPLETED
    # Wznowione zadanie wylicza wylacznie pliki pozostale po przerwaniu.
    assert drugi.discovered == len(pliki) - 2
    assert drugi.processed == len(pliki)

    assert document_statuses(index_service) == dict.fromkeys(pliki, DocumentStatus.INDEXED.value)
    proby = index_service.db.query_all("SELECT name, attempt_count FROM documents")
    # Kazdy dokument zostal przetworzony dokladnie raz, nic nie liczylo sie dwa razy.
    assert {int(row["attempt_count"]) for row in proby} == {1}


# --- transakcyjnosc --------------------------------------------------------------


def test_blad_zapisu_nie_zostawia_dokumentu_w_polowicznym_stanie(
    prepared: tuple[AppConfig, Path],
    index_service: IndexService,
    run_job: Callable[..., ProgressSnapshot],
    exact_search_count: Callable[[IndexService, str], int],
    source_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _root = prepared
    oryginalna = Repository.finalize_document
    wywolania: list[int] = []

    def wybuchowa(self: Repository, doc_id: int, **kwargs: object) -> None:
        """Przerywa zapis pierwszego dokumentu juz po wstawieniu jego fragmentow."""
        wywolania.append(doc_id)
        if len(wywolania) == 1:
            raise RuntimeError("Celowy blad zapisu dokumentu w tescie.")
        oryginalna(self, doc_id, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Repository, "finalize_document", wybuchowa)

    snapshot = run_job(config, index_service)

    assert snapshot.state is JobState.COMPLETED
    assert snapshot.failed == 1
    assert snapshot.processed == len(CORPUS) - 1

    zepsuty = index_service.repository.find_document(source_id, "alfa.txt")
    assert zepsuty is not None
    assert zepsuty.status is DocumentStatus.ERROR
    assert zepsuty.chunk_count == 0
    assert zepsuty.fts_indexed is False
    # Transakcja zostala wycofana, wiec po nieudanym zapisie nie ma zadnych fragmentow.
    pozostale = index_service.db.query_scalar(
        "SELECT COUNT(*) FROM chunks WHERE doc_id = ?", (zepsuty.doc_id,), 0
    )
    assert int(pozostale) == 0
    assert exact_search_count(index_service, "kolczatka") == 0

    raport = index_service.consistency()
    assert raport.orphan_chunks == 0
    assert raport.is_healthy is True
    assert exact_search_count(index_service, "wiewiorka") == 1
